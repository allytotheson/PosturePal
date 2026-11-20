// PosturePal: three independent six-axis VQFs; heading-invariant regional tilt.
// See ../../docs/SETUP.md before enabling haptics. nRF52840 BLE support; no persistent storage.
#include <Arduino.h>
#if defined(ARDUINO_ARCH_SAMD)
#if !defined(USE_TINYUSB)
#error "PosturePal on SAMD requires Tools > USB Stack > TinyUSB; see docs/FEATHER_M4.md."
#endif
#if !defined(VQF_SINGLE_PRECISION)
#error "PosturePal on SAMD requires compiler.cpp.extra_flags=-DVQF_SINGLE_PRECISION; see docs/FEATHER_M4.md."
#endif
#include <Adafruit_TinyUSB.h>
#endif
#include <Wire.h>
#if defined(POSTUREPAL_REQUIRE_HW_WIRE) && !defined(POSTUREPAL_WIRE_HW_BOUNDARIES)
#error "Expected build-local nRF Wire hardware-boundary override; use tools/build.py."
#endif
#include <Adafruit_LSM6DSOX.h>
#include <Adafruit_DRV2605.h>
#include <cstdarg>
#include <cstdio>
#include "vqf.hpp"
#include "PostureCore.h"
#include "CheckedBus.h"
#include "PostureBle.h"

#if defined(__FAST_MATH__)
#error "PosturePal/VQF requires IEEE NaN handling. Set compiler.optimization_flag=-O2; see docs/SETUP.md."
#endif

namespace {
constexpr uint8_t ADDR[3]={0x6a,0x6a,0x6a}; // Separate mux channels isolate identical addresses.
constexpr uint8_t MOTOR_RTP=127; // Full positive signed RTP, bounded by explicit OD_CLAMP below.
constexpr uint8_t MOTOR_OD_CLAMP=138; // ERM open-loop: 0.02159 V/count -> nominal 2.979 V.
constexpr double G=9.80665, TS=1.0/104.0;
constexpr uint32_t POLL_US=1000, SETTLE_MS=3000, CAL_TIMEOUT_MS=60000;
VQFParams filterParameters() {
  VQFParams p; p.magDistRejectionEnabled=false; // No magnetometers supplied.
  p.tauAcc=1.0; // Stronger gravity correction; more sensitive to linear acceleration.
  return p; // Rest AND motion bias estimation remain enabled.
}
enum class State { SETTLING,CALIBRATING,MONITORING,ALERT,PAUSED,FAULT };
const char* stateName(State s) {
  switch(s) {
    case State::SETTLING:return "SETTLING"; case State::CALIBRATING:return "CALIBRATING";
    case State::MONITORING:return "MONITORING"; case State::ALERT:return "ALERT";
    case State::PAUSED:return "PAUSED"; default:return "FAULT";
  }
}
// Bounded queue: no Serial.print() or wait-for-USB in the acquisition path.
class Logger {
  char queue[2048]; size_t head=0,tail=0,used=0;
public:
  uint32_t dropped=0;
  void line(const char* format,...) {
    if(!Serial&&!ppble::connected()) { ++dropped; return; }
    char text[640]; va_list args; va_start(args,format);
    int n=vsnprintf(text,sizeof(text)-1,format,args); va_end(args);
    if(n<0||size_t(n)>=sizeof(text)-1) { ++dropped; return; }
    text[n++]='\n';
    ppble::line(text,size_t(n));
    if(!Serial) return;
    if(size_t(n)>sizeof(queue)-used) {++dropped;return;}
    for(int i=0;i<n;i++) { queue[head]=text[i]; head=(head+1)%sizeof(queue); }
    used+=size_t(n);
  }
  void drain() {
    ppble::drain();
    if(!Serial) { used=0; tail=head; return; }
    int room=Serial.availableForWrite();
    if(room<=0||!used) return;
    size_t n=used; if(n>64) n=64; if(n>size_t(room)) n=size_t(room);
    if(n>sizeof(queue)-tail) n=sizeof(queue)-tail;
    size_t sent=Serial.write(reinterpret_cast<const uint8_t*>(queue+tail),n);
    tail=(tail+sent)%sizeof(queue); used-=sent;
  }
};

class PosturePal {
  pp::CheckedBus<TwoWire> bus;
  pp::Motor<pp::CheckedBus<TwoWire>> motor;
  Adafruit_LSM6DSOX imu[3];
  Adafruit_DRV2605 drv;
  VQF filters[3];
  pp::Alignment alignment[3];
  pp::Settings settings;
  pp::AlertLogic alerts;
  pp::Calibration calibration;
  Logger log;
  State state=State::PAUSED;
  bool mountConfigured=false,mountOK=false,baselineValid=false,geometryValid=false;
  uint32_t busHz=400000; // Diagnostic selection; default remains 400 kHz.
  bool motorEnabled=true; // Explicit sensor-only mode is RAM-only; hardware mode stays the default.
  bool have[3]={},newSample[3]={},rest[3]={};
  double accelerationNorm[3]={},tilt[3]={},regional[2]={},baseline[2]={},deviation[2]={};
  double angularSpeedDps[3]={};
  double sensorNeutral[3]={};
  const char* calWaitReason="hold neutral";
  pp::Vec up[3]={};
  pp::Vec measuredUp[3]={}; // Accelerometer-only reference, meaningful when held still.
  uint32_t stamp[3]={},samples[3]={},maxGap[3]={};
  uint32_t bootUs=0,stateStart=0,calStart=0,lastPoll=0,lastDiag=0,lastMotor=0,skew=0;
  uint32_t previousTick=0,maxTickGap=0,maxPollGap=0,lastTickGap=0;
  uint32_t lastPollGap=0;
  bool haveTick=false;
  uint32_t maxNotReadyAge[3]={};uint8_t lastNotReady[3]={};
  // Keep the acquisition path allocation/printing-free. Freeze these rings in FAULT.
  static constexpr uint8_t TRACE_DEPTH=32;
  struct PollTrace { uint32_t at,age,tick,poll,bus;uint8_t ready,result; };
  PollTrace pollTrace[3][TRACE_DEPTH]={};
  uint8_t traceNext[3]={},traceCount[3]={};
  uint8_t traceSensor=0,pendingTrace=TRACE_DEPTH;
  uint32_t lastTraceOutput=0;
  uint32_t lastConfigCheck=0,lastCalProgress=0;
  uint32_t maxLoopUs=0,maxFilterUs=0,maxDiagUs=0,maxCommandUs=0;
  // Integer-only rolling trace; formatting is deferred until sampling has faulted.
  struct TimingRow {
    uint32_t at=0, gap=0, command=0, acquire[3]={}, evaluation=0, maintenance=0, diag=0, usb=0;
    uint8_t ready[3]={};
  } trace[32], currentTiming;
  uint8_t traceHead=0,loopTraceCount=0,tracePending=0,traceRead=0;
  uint32_t lastTracePrint=0;
  bool traceFrozen=false;
  uint8_t configSensor=0;
  uint8_t pendingSense=3; // Three means idle; emit requested detail over separate loops.
  uint8_t scanStep=16; // Fault-only bus diagnostic: eight channels at two clock rates.
  char input[160]={}; size_t inputLength=0; bool inputOverflow=false;
  char faultMessage[100]="none";

  void transition(State next,const char* reason) {
    state=next; stateStart=millis();
    log.line("EVENT state=%s reason=%s",stateName(state),reason);
  }
  void fault(const char* reason) {
    strncpy(faultMessage,reason,sizeof(faultMessage)-1);
    faultMessage[sizeof(faultMessage)-1]=0;
    baselineValid=false; geometryValid=false; alerts.reset(); calibration.reset();
    // Best effort; never recurse into fault handling if shutdown also fails.
    bool stopped=!motorEnabled||motor.stop(); lastMotor=millis();
    transition(State::FAULT,reason);
    log.line("ERROR stop=%s; retry required",!motorEnabled?"motor-disabled":stopped?"registers-confirmed":"UNKNOWN");
  }
  bool stopOrFault() {
    if(!motorEnabled) { motor.requested=false;motor.confirmed=pp::MotorConfirmation::UNKNOWN;return true; }
    if(motor.stop()) { lastMotor=millis(); return true; }
    fault("motor stop transaction/readback failed"); return false;
  }
  bool imuConfig(uint8_t i) {
    return bus.select(i) && bus.verify(ADDR[i],0x0f,0x6c) &&
      bus.verify(ADDR[i],0x10,0x40) && // CTRL1_XL: 104 Hz, +/-2g, LPF2 disabled
      bus.verify(ADDR[i],0x11,0x40) && // CTRL2_G: 104 Hz, +/-250 dps
      bus.verify(ADDR[i],0x12,0x44,0x47); // BDU, IF_INC; no boot/reset
  }
  void beginCalibration() {
    if(!mountOK) { log.line("ERR set axes and complete mount-ok first"); return; }
    if(!stopOrFault()) return;
    baselineValid=false; alerts.reset(); calibration.reset();
    calWaitReason="hold neutral";
    transition(State::SETTLING,"hold neutral; 3 s settle, then 2 s continuously still");
  }
  bool initialize() {
    baselineValid=false; geometryValid=false; alerts.reset(); calibration.reset();
    pendingTrace=TRACE_DEPTH;
    traceHead=loopTraceCount=tracePending=0; traceFrozen=false; previousTick=0;
    for(uint8_t i=0;i<3;i++) {
      have[i]=newSample[i]=rest[i]=false; stamp[i]=samples[i]=maxGap[i]=0;
      maxNotReadyAge[i]=0;lastNotReady[i]=0;
      traceNext[i]=traceCount[i]=0;
      filters[i].resetState();
    }
    if(motorEnabled) {
      log.line("MODE hardware motor enabled (default after reset); buzz reports drive request, not measured vibration");
      // DRV2605L is on upstream SDA/SCL at 0x5A; no mux channel selection.
      // stop() works without the Adafruit driver object being initialized.
      if(!motor.stop()) { fault("initial motor stop failed; check upstream DRV2605L 0x5A"); return false; }
      if(!drv.begin(&Wire)) { fault("DRV2605L initialization failed"); return false; }
      uint8_t feedback,control3;
      if(!bus.read(0x5a,0x1a,&feedback,1)||!bus.read(0x5a,0x1d,&control3,1)||
         !bus.writeVerify(0x5a,0x1a,uint8_t(feedback&0x7f))||
         !bus.writeVerify(0x5a,0x1d,uint8_t((control3|0x20)&~0x48))|| // ERM OL, signed RTP, supply compensation enabled.
         !bus.writeVerify(0x5a,0x17,MOTOR_OD_CLAMP)||
         !motor.stop()||!motor.check(MOTOR_RTP)) {
        fault("ERM/open-loop/signed-RTP configuration failed"); return false;
      }
    } else log.line("MODE sensor-only; physical motor disabled; buzz reports alert decision");
    for(uint8_t i=0;i<3;i++) {
      if(!bus.select(i)) {
        char reason[100];snprintf(reason,sizeof(reason),"mux 0x70 select failed for IMU channel %u; use scan",unsigned(i));
        fault(reason);return false;
      }
      if(!imu[i].begin_I2C(ADDR[i],&Wire)) {
        char reason[100];snprintf(reason,sizeof(reason),"IMU init failed channel=%u addr=0x%02X; use scan",unsigned(i),unsigned(ADDR[i]));
        fault(reason); return false;
      }
      imu[i].setAccelRange(LSM6DS_ACCEL_RANGE_2_G);
      imu[i].setGyroRange(LSM6DS_GYRO_RANGE_250_DPS);
      imu[i].setAccelDataRate(LSM6DS_RATE_104_HZ);
      imu[i].setGyroDataRate(LSM6DS_RATE_104_HZ);
      if(!bus.writeVerify(ADDR[i],0x12,0x44)||!imuConfig(i)) {
        fault("IMU configuration readback mismatch"); return false;
      }
      // Discard initialization-era data. No filter update for this discarded sample.
      uint8_t discard[12];
      if(!bus.read(ADDR[i],0x22,discard,sizeof(discard))) { fault("initial IMU drain failed"); return false; }
    }
    // BusIO device begin() calls Wire.begin(), resetting SAMD's clock to 100 kHz.
    // Restore fast mode AFTER every device has initialized, also on retry.
    Wire.setClock(busHz);
    // Initializing other sensors can leave earlier sensors holding a stale BDU sample.
    for(uint8_t i=0;i<3;i++) {
      uint8_t discard[12];
      if(!bus.select(i)||!bus.read(ADDR[i],0x22,discard,12)) { fault("IMU startup flush failed"); return false; }
    }
    bootUs=lastPoll=micros(); lastMotor=lastConfigCheck=millis();
    haveTick=false;maxTickGap=maxPollGap=lastTickGap=lastPollGap=0;
    if(mountOK) beginCalibration();
    else transition(State::PAUSED,"unverified axes: use axes <headward> <outward>, then mount-ok");
    return state!=State::FAULT;
  }
  static int16_t signedLE(const uint8_t* bytes) {
    uint16_t raw=uint16_t(bytes[0])|(uint16_t(bytes[1])<<8);
    int32_t value=raw; if(raw&0x8000) value-=65536;
    return int16_t(value);
  }
  void recordPoll(uint8_t i,uint32_t start,uint8_t ready,uint8_t result) {
    uint32_t now=micros();
    pollTrace[i][traceNext[i]]={now,have[i]?now-stamp[i]:0,lastTickGap,lastPollGap,now-start,ready,result};
    traceNext[i]=(traceNext[i]+1)%TRACE_DEPTH;
    if(traceCount[i]<TRACE_DEPTH)++traceCount[i];
  }
  bool acquisitionFault(uint8_t i,const char* message) {
    char reason[100];snprintf(reason,sizeof(reason),"%s imu=%u channel=%u",message,unsigned(i),unsigned(i));
    fault(reason);return false;
  }
  bool acquire(uint8_t i) {
    uint32_t start=micros();
    if(!bus.select(i)) {recordPoll(i,start,0xff,2);return acquisitionFault(i,"mux select failed during sampling");}
    uint8_t ready;
    if(!bus.read(ADDR[i],0x1e,&ready,1)) {recordPoll(i,start,0xff,3);return acquisitionFault(i,"IMU status read failed");}
    currentTiming.ready[i]=ready;
    uint32_t now=micros();
    if((ready&3)!=3) {
      recordPoll(i,start,ready,0);
      lastNotReady[i]=ready;
      uint32_t age=have[i]?now-stamp[i]:0;
      if(age>maxNotReadyAge[i])maxNotReadyAge[i]=age;
      if(pp::elapsed(now,have[i]?stamp[i]:bootUs,pp::STALE_US)) return acquisitionFault(i,"IMU stale/data-ready timeout");
      return true;
    }
    uint8_t bytes[12];
    // OUTX_L_G 0x22 through OUTZ_H_A 0x2d, little endian, gyro then acceleration.
    if(!bus.read(ADDR[i],0x22,bytes,12)) {recordPoll(i,start,ready,4);return acquisitionFault(i,"IMU short read or NACK");}
    now=micros();
    bool gap=pp::sampleGap(now,stamp[i],have[i]);
    recordPoll(i,start,ready,gap?5:1);
    if(gap) {
      char reason[100];
      snprintf(reason,sizeof(reason),"IMU gap imu=%u gap_us=%lu limit_us=%lu tick_gap_us=%lu",unsigned(i),
        (unsigned long)(now-stamp[i]),(unsigned long)pp::GAP_US,(unsigned long)lastTickGap);
      fault(reason); return false;
    }
    if(have[i] && now-stamp[i]>maxGap[i]) maxGap[i]=now-stamp[i];
    vqf_real_t gyr[3],acc[3];
    for(int j=0;j<3;j++) {
      int16_t g=signedLE(bytes+2*j),a=signedLE(bytes+6+2*j);
      if(g>=32000||g<=-32000||a>=32000||a<=-32000) {
        bool gyro=g>=32000||g<=-32000;
        char reason[100];
        snprintf(reason,sizeof(reason),"IMU near full-scale imu=%u channel=%u source=%s axis=%c raw=%d limit=32000",
          unsigned(i),unsigned(i),gyro?"gyro":"accel",char('X'+j),int(gyro?g:a));
        fault(reason); return false;
      }
      gyr[j]=g*0.00875/pp::DEG; // +/-250 dps: 8.75 mdps/LSB -> rad/s
      acc[j]=a*0.000061*G;     // +/-2g: 0.061 mg/LSB -> m/s^2
    }
    accelerationNorm[i]=std::sqrt(acc[0]*acc[0]+acc[1]*acc[1]+acc[2]*acc[2]);
    angularSpeedDps[i]=std::sqrt(double(gyr[0])*gyr[0]+double(gyr[1])*gyr[1]+double(gyr[2])*gyr[2])*pp::DEG;
    if(accelerationNorm[i]<0.1*G) { fault("near-zero acceleration / free fall"); return false; }
    measuredUp[i]={acc[0]/accelerationNorm[i],acc[1]/accelerationNorm[i],acc[2]/accelerationNorm[i]};
    uint32_t filterStart=micros();
    filters[i].update(gyr,acc);
    uint32_t filterUs=micros()-filterStart; if(filterUs>maxFilterUs) maxFilterUs=filterUs;
    rest[i]=filters[i].getRestDetected();
    vqf_real_t q[4]; filters[i].getQuat6D(q);
    if(!pp::upFromQuaternion(q,alignment[i],up[i])) { fault("invalid filter quaternion"); return false; }
    stamp[i]=now; have[i]=newSample[i]=true; ++samples[i];
    return true;
  }
  void evaluate() {
    uint32_t now=millis();
    if(!newSample[0]||!newSample[1]||!newSample[2]) return;
    if(!pp::freshFrame(micros(),stamp,skew)) { fault("stale/skewed regional frame"); return; }
    geometryValid=true;
    for(uint8_t i=0;i<3;i++) {
      newSample[i]=false;
      if(!pp::sagittalTilt(up[i],tilt[i])) geometryValid=false;
    }
    if(!geometryValid) {
      if(mountOK) fault("sagittal projection undefined; check sensor orientation");
      return; // Before axes are verified, raw up vectors are still available for setup.
    }
    pp::regions(tilt,regional);
    if(state==State::SETTLING && pp::elapsed(now,stateStart,SETTLE_MS)) {
      calibration.reset(); calStart=now;
      transition(State::CALIBRATING,"2 s neutral averaging; movement restarts window");
    }
    if(state==State::CALIBRATING) {
      bool still=true;
      // VQF's bias-estimator rest flag is deliberately strict; do not use it as
      // a wearable calibration gate. Use explicit motion/gravity limits instead.
      const char* motionReason[3]={"upper sensor moving too quickly","middle sensor moving too quickly","lower sensor moving too quickly"};
      const char* accelReason[3]={"upper sensor acceleration not steady","middle sensor acceleration not steady","lower sensor acceleration not steady"};
      for(uint8_t i=0;i<3;i++) {
        if(angularSpeedDps[i]>5.0) { still=false;calWaitReason=motionReason[i];break; }
        if(std::fabs(accelerationNorm[i]-G)>0.10*G) { still=false;calWaitReason=accelReason[i];break; }
      }
      if(calibration.add(now,tilt,regional,still)) {
        calibration.baseline(baseline);calibration.sensorBaseline(sensorNeutral);baselineValid=true;alerts.reset();
        transition(State::MONITORING,"neutral saved in RAM");
      } else {
        if(still&&!calibration.tracking) calWaitReason="posture changed too much; capture restarted";
        if(pp::elapsed(now,calStart,CAL_TIMEOUT_MS)) fault("calibration timeout; use status for last calibration blocker");
      }
    }
    if(!baselineValid) return;
    for(int i=0;i<2;i++) deviation[i]=pp::wrap(regional[i]-baseline[i]);
    if(state!=State::MONITORING && state!=State::ALERT) return;
    alerts.update(deviation,now,settings);
    if(alerts.alert && state!=State::ALERT) {
      if(motorEnabled&&(!bus.verify(0x5a,0x17,MOTOR_OD_CLAMP)||!motor.start(MOTOR_RTP))) {
        fault("motor voltage clamp/start verification failed"); return;
      }
      lastMotor=now; transition(State::ALERT,"regional persistence reached");
    } else if(!alerts.alert && state==State::ALERT) {
      if(stopOrFault()) transition(State::MONITORING,"both regions within recovery limits");
    }
  }
  void status() {
    log.line("POSTUREPAL firmware=feather-v4-timing calibration=3s-settle+2s-still vqf_bits=%u",unsigned(sizeof(vqf_real_t)*8));
    log.line("PROTOCOL version=1 transport=newline-ascii");
    log.line("BUS_CONFIG hz=%lu",(unsigned long)busHz);
#if defined(POSTUREPAL_WIRE_HW_BOUNDARIES)
    log.line("BUS_DRIVER nrf52-hardware-boundaries");
#else
    log.line("BUS_DRIVER platform-default");
#endif
    log.line("MAPPING imu0=T3 imu1=T12 imu2=L5 trace_frozen=%d log_dropped=%lu",traceFrozen,(unsigned long)log.dropped);
    log.line("FILTER tau_acc_s=1.0 baseline=fixed; use sense for gravity comparison");
    log.line("CAL_INFO gate=gyro-and-gravity max_speed_dps=5 max_accel_error_percent=10 max_sway_deg=2 last_blocker=%s",calWaitReason);
    log.line("TIMING max_loop_us=%lu max_filter_us=%lu max_diag_us=%lu max_command_us=%lu gap_limit_us=%lu",
      (unsigned long)maxLoopUs,(unsigned long)maxFilterUs,(unsigned long)maxDiagUs,
      (unsigned long)maxCommandUs,(unsigned long)pp::GAP_US);
    log.line("SCHED max_tick_gap_us=%lu max_poll_gap_us=%lu last_tick_gap_us=%lu",
      (unsigned long)maxTickGap,(unsigned long)maxPollGap,(unsigned long)lastTickGap);
    for(uint8_t i=0;i<3;i++)log.line("IMU_TIMING imu=%u samples=%lu max_sample_gap_us=%lu max_notready_age_us=%lu last_notready=0x%02X",
      unsigned(i),(unsigned long)samples[i],(unsigned long)maxGap[i],(unsigned long)maxNotReadyAge[i],unsigned(lastNotReady[i]));
    log.line("STATUS state=%s mount_configured=%d mount_ok=%d baseline_valid=%d geometry_valid=%d fault=%s",
      stateName(state),mountConfigured,mountOK,baselineValid,geometryValid,faultMessage);
    log.line("MOTOR buzz=%d motor=%s enabled=%d",motorEnabled?motor.requested:alerts.alert,
      !motorEnabled?"DISABLED":motor.confirmed==pp::MotorConfirmation::UNKNOWN?"UNKNOWN":motor.confirmed==pp::MotorConfirmation::ON?"ON_REG":"OFF_REG",motorEnabled);
    log.line("ACTUATOR Adafruit_1201 ERM open-loop signed-RTP; OD_CLAMP=%u full_scale_nominal_v=2.979 supply_compensation=on",MOTOR_OD_CLAMP);
    log.line("SETTINGS trigger=%.2f,%.2f recovery=%.2f,%.2f duration_ms=%lu motor_rtp=%u (TUNING VALUES)",
      settings.trigger[0],settings.trigger[1],settings.recovery[0],settings.recovery[1],
      (unsigned long)settings.durationMs,MOTOR_RTP);
    log.line("BASELINE valid=%d sag=%.3f,%.3f",baselineValid,baseline[0],baseline[1]);
    for(int i=0;i<3;i++) log.line("AXES imu=%d forward=%.2f,%.2f,%.2f left=%.2f,%.2f,%.2f head=%.2f,%.2f,%.2f",
      i,alignment[i].m[0][0],alignment[i].m[0][1],alignment[i].m[0][2],
      alignment[i].m[1][0],alignment[i].m[1][1],alignment[i].m[1][2],
      alignment[i].m[2][0],alignment[i].m[2][1],alignment[i].m[2][2]);
  }
  void help() {
    log.line("COMMANDS scan (in FAULT): check IMU IDs on all mux channels at 100/400 kHz");
    log.line("COMMANDS timing: replay frozen fault trace; retry clears trace");
    log.line("COMMANDS help | status | sense | axes <headward signed axis> <outward signed axis> | mount-ok");
    log.line("COMMANDS motor off (sensor-only) | motor on (require driver); mode resets on reboot");
    log.line("COMMANDS calibrate | pause | resume | retry | set <upperTrigger> <upperRecovery> <lowerTrigger> <lowerRecovery> <durationMs>");
    log.line("COMMANDS bus-rate <100000|400000> (FAULT/PAUSED only; reinitializes sensors)");
    log.line("COMMANDS trace <0|1|2> (FAULT only): last 32 polls for one IMU; request before retry");
    log.line("EXAMPLE axes +Y +Z only if +Y points headward and +Z outward; mount-ok then hold neutral for about 5 s");
  }
  void command(char* commandText=nullptr) {
    char* tokens[8]; int count=0; char* save=nullptr;
    for(char* t=strtok_r(commandText?commandText:input," \t",&save);t;t=strtok_r(nullptr," \t",&save)) {
      if(count==8) { log.line("ERR too many arguments"); return; } tokens[count++]=t;
    }
    if(!count) return;
    if(count==1&&!strcmp(tokens[0],"help")) { help(); return; }
    if(count==1&&!strcmp(tokens[0],"status")) { status(); return; }
    if(count>=1&&!strcmp(tokens[0],"trace")) {
      if(count!=2||strlen(tokens[1])!=1||tokens[1][0]<'0'||tokens[1][0]>'2') {log.line("ERR trace requires one IMU index 0, 1 or 2");return;}
      if(state!=State::FAULT) {log.line("ERR trace requires FAULT; acquisition must be stopped");return;}
      if(pendingTrace<TRACE_DEPTH) {log.line("ERR trace output busy; wait for TRACE end");return;}
      traceSensor=uint8_t(tokens[1][0]-'0');pendingTrace=0;lastTraceOutput=millis();
      log.line("TRACE begin imu=%u count=%u oldest-first; result=0:waiting,1:sample,2:mux,3:status,4:data,5:gap",unsigned(traceSensor),unsigned(traceCount[traceSensor]));
      return;
    }
    if(count==1&&!strcmp(tokens[0],"timing")) {
      if(!traceFrozen) { log.line("TIMING trace available after a sampling fault"); return; }
      traceRead=(traceHead+32-loopTraceCount)%32;tracePending=loopTraceCount;return;
    }
    if(count==1&&(!strcmp(tokens[0],"motor-on")||!strcmp(tokens[0],"motor-off"))) {
      log.line("ERR use motor on or motor off with a space; mode unchanged");return;
    }
    if(count==1&&!strcmp(tokens[0],"scan")) {
      if(state!=State::FAULT) { log.line("ERR scan requires FAULT; it is a bus diagnostic, not a monitoring command");return; }
      scanStep=0;log.line("BUS scan starting; expected LSM6DSOX WHO_AM_I=0x6C; channels 0/1/2 normally use 0x6A");return;
    }
    if(count==1&&!strcmp(tokens[0],"sense")) {
      pendingSense=0;
      return;
    }
    if(count==2&&!strcmp(tokens[0],"motor")&&(!strcmp(tokens[1],"off")||!strcmp(tokens[1],"on"))) {
      bool enable=!strcmp(tokens[1],"on");
      if(!enable&&motorEnabled) {
        // One best-effort shutdown before opting out; disconnected hardware is not required.
        if(!motor.stop()) log.line("NOTICE motor stop unconfirmed; sensor-only mode cannot guarantee physical shutdown");
      }
      motorEnabled=enable;motor.requested=false;motor.confirmed=pp::MotorConfirmation::UNKNOWN;
      strcpy(faultMessage,"none");initialize();return;
    }
    if(count==2&&!strcmp(tokens[0],"bus-rate")) {
      if(state!=State::FAULT&&state!=State::PAUSED) { log.line("ERR bus-rate requires FAULT or PAUSED");return; }
      if(strcmp(tokens[1],"100000")&&strcmp(tokens[1],"400000")) { log.line("ERR bus-rate must be 100000 or 400000");return; }
      busHz=!strcmp(tokens[1],"100000")?100000:400000;
      Wire.setClock(busHz);strcpy(faultMessage,"none");initialize();return;
    }
    if(count==1&&!strcmp(tokens[0],"retry")) { strcpy(faultMessage,"none"); initialize(); return; }
    if(state==State::FAULT) { log.line("ERR FAULT latched; use retry after correcting cause"); return; }
    if(!strcmp(tokens[0],"set")) {
      pp::Settings next;
      if(!pp::parseSettings(tokens,count,next)) { log.line("ERR set: finite degrees 0 < recovery < trigger <=90; integer duration 1..3600000 ms"); return; }
      if(!stopOrFault()) return;
      settings=next; alerts.reset();
      if(state==State::ALERT) transition(State::MONITORING,"settings changed; persistence reset");
      log.line("ACK settings applied; regional timers reset"); return;
    }
    if(count==3&&!strcmp(tokens[0],"axes")) {
      pp::Alignment next;
      if(!pp::makeAlignment(tokens[1],tokens[2],next)) { log.line("ERR axes must be perpendicular signed +X/-X/+Y/-Y/+Z/-Z"); return; }
      if(!stopOrFault()) return;
      for(int i=0;i<3;i++) alignment[i]=next;
      mountConfigured=true; mountOK=false; baselineValid=false; geometryValid=false;
      alerts.reset(); calibration.reset();
      transition(State::PAUSED,"common axes changed; verify fixtures then mount-ok"); return;
    }
    if(count==1&&!strcmp(tokens[0],"mount-ok")) {
      if(!mountConfigured||!geometryValid) { log.line("ERR configure axes; wait for valid tilt diagnostics and verify physical mapping first"); return; }
      mountOK=true; beginCalibration(); return;
    }
    if(count==1&&!strcmp(tokens[0],"calibrate")) { beginCalibration(); return; }
    if(count==1&&!strcmp(tokens[0],"pause")) {
      if(!stopOrFault()) return;
      alerts.reset(); calibration.reset(); transition(State::PAUSED,"user pause; filters continue"); return;
    }
    if(count==1&&!strcmp(tokens[0],"resume")) {
      if(!mountOK) { log.line("ERR mounting not acknowledged"); return; }
      if(!baselineValid) { beginCalibration(); return; }
      if(!stopOrFault()) return;
      alerts.reset(); transition(State::MONITORING,"user resume"); return;
    }
    log.line("ERR unknown command or argument count; use help");
  }
  void serialInput() {
    // Bounded input processing: sustained host traffic cannot monopolize sampling.
    for(int budget=0;budget<32 && Serial.available();budget++) {
      int c=Serial.read();
      if(c=='\r') continue;
      if(c=='\n') {
        if(inputOverflow) log.line("ERR command too long; discarded");
        else { input[inputLength]=0; command(); }
        inputLength=0; inputOverflow=false;
      } else if(c>=32 && c<=126) {
        if(inputLength<sizeof(input)-1) input[inputLength++]=char(c); else inputOverflow=true;
      } else inputOverflow=true; // Never execute a silently truncated/binary command.
    }
  }
  void diagnostics() {
    uint32_t now=millis();
    if(state==State::SETTLING||state==State::CALIBRATING) {
      if(pp::elapsed(now,lastCalProgress,1000)) {
        lastCalProgress=now;
        log.line("CAL %s",state==State::SETTLING?"hold neutral; filters settling":
          calibration.tracking?"keep still; capturing neutral":calWaitReason);
      }
      return;
    }
    if(state!=State::MONITORING&&state!=State::ALERT) return;
    if(!baselineValid||!geometryValid||!pp::elapsed(now,lastDiag,1000)) return;
    lastDiag=now;
    // Command flag, not a physical vibration measurement. Faults are reported separately.
    log.line("upper_deg=%.2f lower_deg=%.2f buzz=%d",deviation[0],deviation[1],motorEnabled?motor.requested:alerts.alert);
  }

  void senseDiagnostics() {
    if(pendingSense>=3) return;
    uint8_t i=pendingSense++;
    double gravityTilt=0;
    bool projected=have[i]&&pp::sagittalTilt(alignment[i].apply(measuredUp[i]),gravityTilt);
    bool quiet=projected&&std::fabs(accelerationNorm[i]-G)<=0.10*G&&angularSpeedDps[i]<=5;
    uint32_t runtime=micros()-bootUs;
    const char* names[3]={"T3","T12","L5"};
    log.line("SENSE imu=%u site=%s valid=%d neutral_valid=%d vqf_deg=%.2f neutral_delta_deg=%.2f gravity_deg=%.2f gravity_quiet=%d filter_minus_gravity_deg=%.2f gyro_dps=%.2f rest=%d mean_hz=%.1f",
      unsigned(i),names[i],have[i]&&geometryValid&&state!=State::FAULT,baselineValid,
      tilt[i],baselineValid?pp::wrap(tilt[i]-sensorNeutral[i]):0,gravityTilt,quiet,
      projected?pp::wrap(tilt[i]-gravityTilt):0,angularSpeedDps[i],rest[i],
      runtime?double(samples[i])*1000000.0/runtime:0);
  }

  void busDiagnostics() {
    if(scanStep>=16) return;
    if(state!=State::FAULT) {scanStep=16;Wire.setClock(busHz);return;}
    uint32_t hz=scanStep<8?100000:400000;
    uint8_t channel=scanStep%8;++scanStep;
    Wire.setClock(hz);
    if(!bus.select(channel)) log.line("BUS hz=%lu channel=%u mux_0x70=FAIL",(unsigned long)hz,unsigned(channel));
    else for(uint8_t addr=0x6a;addr<=0x6b;addr++) {
      uint8_t id=0;
      bool ok=bus.read(addr,0x0f,&id,1);
      log.line("BUS hz=%lu channel=%u addr=0x%02X read=%s id=0x%02X lsm6dsox=%d",
        (unsigned long)hz,unsigned(channel),unsigned(addr),ok?"OK":"FAIL",unsigned(id),ok&&id==0x6c);
    }
    if(scanStep==16) {Wire.setClock(busHz);log.line("BUS scan complete; send retry after correcting connections/mapping");}
  }

  void traceDiagnostics() {
    if(pendingTrace>=TRACE_DEPTH) return;
    if(state!=State::FAULT) {pendingTrace=TRACE_DEPTH;return;}
    if(!pp::elapsed(millis(),lastTraceOutput,100)) return;
    lastTraceOutput=millis();
    uint8_t count=traceCount[traceSensor];
    if(pendingTrace>=count) {log.line("TRACE end imu=%u",unsigned(traceSensor));pendingTrace=TRACE_DEPTH;return;}
    uint8_t oldest=(traceNext[traceSensor]+TRACE_DEPTH-count)%TRACE_DEPTH;
    const PollTrace& p=pollTrace[traceSensor][(oldest+pendingTrace)%TRACE_DEPTH];
    log.line("TRACE imu=%u row=%u at_us=%lu age_us=%lu tick_us=%lu poll_us=%lu bus_us=%lu ready=0x%02X result=%u",
      unsigned(traceSensor),unsigned(pendingTrace++),(unsigned long)p.at,(unsigned long)p.age,
      (unsigned long)p.tick,(unsigned long)p.poll,(unsigned long)p.bus,unsigned(p.ready),unsigned(p.result));
    if(pendingTrace>=count) {log.line("TRACE end imu=%u",unsigned(traceSensor));pendingTrace=TRACE_DEPTH;}
  }

public:
  PosturePal():bus(Wire),motor(bus),filters{VQF(filterParameters(),TS),VQF(filterParameters(),TS),VQF(filterParameters(),TS)} {
    for(int i=0;i<3;i++) alignment[i]={{{1,0,0},{0,1,0},{0,0,1}}}; // UNVERIFIED placeholder
  }
  void begin() {
    Serial.begin(115200); // No wait: battery operation must not depend on a USB host.
    ppble::begin();
    Wire.begin(); Wire.setClock(busHz);
    initialize(); help();
  }
  void tick() {
    uint32_t loopStart=micros();
    if(haveTick) {lastTickGap=loopStart-previousTick;if(lastTickGap>maxTickGap)maxTickGap=lastTickGap;}
    previousTick=loopStart;haveTick=true;
    currentTiming=TimingRow{};currentTiming.at=loopStart;
    currentTiming.gap=lastTickGap;
    serialInput();
    char bleCommand[160];
    if(ppble::take(bleCommand)) command(bleCommand);
    uint32_t commandUs=micros()-loopStart; if(commandUs>maxCommandUs) maxCommandUs=commandUs;
    currentTiming.command=commandUs;
    if(state!=State::FAULT) {
      uint32_t us=micros();
      if(pp::elapsed(us,lastPoll,POLL_US)) {
        uint32_t pollGap=us-lastPoll;lastPollGap=pollGap;if(pollGap>maxPollGap)maxPollGap=pollGap;
        lastPoll=us;
        for(uint8_t i=0;i<3;i++) {
          uint32_t start=micros();bool ok=acquire(i);
          currentTiming.acquire[i]=micros()-start;if(!ok) break;
        }
        uint32_t evalStart=micros();
        if(state!=State::FAULT) evaluate();
        currentTiming.evaluation=micros()-evalStart;
      }
      uint32_t maintenanceStart=micros();
      uint32_t now=millis();
      if(state!=State::FAULT && pp::elapsed(now,lastMotor,250)) {
        lastMotor=now;
        if(motorEnabled&&(!motor.check(MOTOR_RTP)||!bus.verify(0x5a,0x17,MOTOR_OD_CLAMP)))
          fault("motor state/status/voltage-clamp verification failed");
      }
      if(state!=State::FAULT && pp::elapsed(now,lastConfigCheck,1000)) {
        lastConfigCheck=now;
        if(!imuConfig(configSensor)) fault("periodic IMU configuration/identity check failed");
        configSensor=(configSensor+1)%3;
      }
      currentTiming.maintenance=micros()-maintenanceStart;
    } else if(pp::elapsed(millis(),lastMotor,250)) {
      lastMotor=millis(); if(motorEnabled) motor.stop(); // Remain latched FAULT even if shutdown succeeds.
    }
    uint32_t diagStart=micros();
    diagnostics();
    senseDiagnostics();
    busDiagnostics();
    traceDiagnostics();
    uint32_t diagUs=micros()-diagStart; if(diagUs>maxDiagUs) maxDiagUs=diagUs;
    currentTiming.diag=diagUs;
    uint32_t usbStart=micros();log.drain();currentTiming.usb=micros()-usbStart;
    if(!traceFrozen) {
      trace[traceHead]=currentTiming;traceHead=(traceHead+1)%32;
      if(loopTraceCount<32) ++loopTraceCount;
      if(state==State::FAULT) {
        traceFrozen=true;traceRead=(traceHead+32-loopTraceCount)%32;tracePending=loopTraceCount;
      }
    }
    // Pace post-fault output so it does not flood the bounded serial queue.
    if(tracePending && pp::elapsed(millis(),lastTracePrint,20)) {
      lastTracePrint=millis();const TimingRow& r=trace[traceRead];
      log.line("LOOP_TRACE at_us=%lu tick_gap=%lu cmd=%lu read_us=%lu,%lu,%lu ready_hex=%02X,%02X,%02X eval=%lu maint=%lu diag=%lu usb=%lu",
        (unsigned long)r.at,(unsigned long)r.gap,(unsigned long)r.command,
        (unsigned long)r.acquire[0],(unsigned long)r.acquire[1],(unsigned long)r.acquire[2],
        unsigned(r.ready[0]),unsigned(r.ready[1]),unsigned(r.ready[2]),
        (unsigned long)r.evaluation,(unsigned long)r.maintenance,(unsigned long)r.diag,(unsigned long)r.usb);
      traceRead=(traceRead+1)%32;--tracePending;
      if(!tracePending) log.line("LOOP_TRACE end");
    }
    uint32_t loopUs=micros()-loopStart; if(loopUs>maxLoopUs) maxLoopUs=loopUs;
  }
};
PosturePal device;
} // namespace

void setup() { device.begin(); }
void loop() { device.tick(); }
