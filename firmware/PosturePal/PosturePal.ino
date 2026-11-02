// PosturePal: three independent six-axis VQFs; heading-invariant regional tilt.
// See ../../docs/SETUP.md before enabling haptics. No BLE or persistent storage.
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_LSM6DSOX.h>
#include <Adafruit_DRV2605.h>
#include <cstdarg>
#include <cstdio>
#include "vqf.hpp"
#include "PostureCore.h"
#include "CheckedBus.h"

#if defined(__FAST_MATH__)
#error "PosturePal/VQF requires IEEE NaN handling. Set compiler.optimization_flag=-O2; see docs/SETUP.md."
#endif

namespace {
constexpr uint8_t ADDR[3]={0x6b,0x6a,0x6a};
constexpr uint8_t MOTOR_RTP=32; // Initial LOW drive setting, not a verified motor voltage.
constexpr double G=9.80665, TS=1.0/104.0;
constexpr uint32_t POLL_US=1000, SETTLE_MS=10000, CAL_TIMEOUT_MS=60000;
VQFParams filterParameters() {
  VQFParams p; p.magDistRejectionEnabled=false; // No magnetometers supplied.
  return p; // tauAcc=3 s, rest AND motion bias estimation enabled.
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
    if(!Serial) { ++dropped; return; }
    char text[640]; va_list args; va_start(args,format);
    int n=vsnprintf(text,sizeof(text)-1,format,args); va_end(args);
    if(n<0||size_t(n)>=sizeof(text)-1||size_t(n+1)>sizeof(queue)-used) { ++dropped; return; }
    text[n++]='\n';
    for(int i=0;i<n;i++) { queue[head]=text[i]; head=(head+1)%sizeof(queue); }
    used+=size_t(n);
  }
  void drain() {
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
  bool have[3]={},newSample[3]={},rest[3]={};
  double accelerationNorm[3]={},tilt[6]={},regional[4]={},baseline[4]={},deviation[4]={};
  pp::Vec up[3]={};
  uint32_t stamp[3]={},samples[3]={},maxGap[3]={};
  uint32_t bootUs=0,stateStart=0,calStart=0,lastPoll=0,lastDiag=0,lastMotor=0,skew=0;
  uint32_t lastConfigCheck=0;
  uint8_t configSensor=0;
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
    bool stopped=motor.stop(); lastMotor=millis();
    transition(State::FAULT,reason);
    log.line("ERROR stop=%s; retry required",stopped?"registers-confirmed":"UNKNOWN");
  }
  bool stopOrFault() {
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
    transition(State::SETTLING,"hold neutral; 10 s settle, then 5 s continuously still");
  }
  bool initialize() {
    baselineValid=false; geometryValid=false; alerts.reset(); calibration.reset();
    for(uint8_t i=0;i<3;i++) {
      have[i]=newSample[i]=rest[i]=false; stamp[i]=samples[i]=maxGap[i]=0;
      filters[i].resetState();
    }
    // stop() works without the Adafruit driver object being initialized.
    if(!motor.stop()) { fault("initial motor stop failed; check mux 3 / DRV2605L"); return false; }
    if(!bus.select(3)||!drv.begin(&Wire)) { fault("DRV2605L initialization failed"); return false; }
    uint8_t feedback,control3;
    if(!bus.read(0x5a,0x1a,&feedback,1)||!bus.read(0x5a,0x1d,&control3,1)||
       !bus.writeVerify(0x5a,0x1a,uint8_t(feedback&0x7f))||
       !bus.writeVerify(0x5a,0x1d,uint8_t((control3|0x20)&~0x08))||
       !motor.stop()||!motor.check(MOTOR_RTP)) {
      fault("ERM/open-loop/signed-RTP configuration failed"); return false;
    }
    for(uint8_t i=0;i<3;i++) {
      if(!bus.select(i)||!imu[i].begin_I2C(ADDR[i],&Wire)) {
        fault("LSM6DSOX initialization failed; check channel/address"); return false;
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
    // Initializing other sensors can leave earlier sensors holding a stale BDU sample.
    for(uint8_t i=0;i<3;i++) {
      uint8_t discard[12];
      if(!bus.select(i)||!bus.read(ADDR[i],0x22,discard,12)) { fault("IMU startup flush failed"); return false; }
    }
    bootUs=lastPoll=micros(); lastMotor=lastConfigCheck=millis();
    if(mountOK) beginCalibration();
    else transition(State::PAUSED,"unverified axes: use axes <headward> <outward>, then mount-ok");
    return state!=State::FAULT;
  }
  static int16_t signedLE(const uint8_t* bytes) {
    uint16_t raw=uint16_t(bytes[0])|(uint16_t(bytes[1])<<8);
    int32_t value=raw; if(raw&0x8000) value-=65536;
    return int16_t(value);
  }
  bool acquire(uint8_t i) {
    if(!bus.select(i)) { fault("mux select failed during sampling"); return false; }
    uint8_t ready;
    if(!bus.read(ADDR[i],0x1e,&ready,1)) { fault("IMU status read failed"); return false; }
    uint32_t now=micros();
    if((ready&3)!=3) {
      if(pp::elapsed(now,have[i]?stamp[i]:bootUs,pp::STALE_US)) { fault("IMU stale/data-ready timeout"); return false; }
      return true;
    }
    uint8_t bytes[12];
    // OUTX_L_G 0x22 through OUTZ_H_A 0x2d, little endian, gyro then acceleration.
    if(!bus.read(ADDR[i],0x22,bytes,12)) { fault("IMU short read or NACK"); return false; }
    now=micros();
    if(pp::sampleGap(now,stamp[i],have[i])) { fault("IMU acquisition gap; sample continuity lost"); return false; }
    if(have[i] && now-stamp[i]>maxGap[i]) maxGap[i]=now-stamp[i];
    vqf_real_t gyr[3],acc[3];
    for(int j=0;j<3;j++) {
      int16_t g=signedLE(bytes+2*j),a=signedLE(bytes+6+2*j);
      if(g>=32000||g<=-32000||a>=32000||a<=-32000) { fault("IMU near full-scale; invalid posture estimate"); return false; }
      gyr[j]=g*0.00875/pp::DEG; // +/-250 dps: 8.75 mdps/LSB -> rad/s
      acc[j]=a*0.000061*G;     // +/-2g: 0.061 mg/LSB -> m/s^2
    }
    accelerationNorm[i]=std::sqrt(acc[0]*acc[0]+acc[1]*acc[1]+acc[2]*acc[2]);
    if(accelerationNorm[i]<0.1*G) { fault("near-zero acceleration / free fall"); return false; }
    filters[i].update(gyr,acc);
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
      if(!pp::tilts(up[i],tilt[i],tilt[i+3])) geometryValid=false;
    }
    if(!geometryValid) {
      if(mountOK) fault("near-singular tilt projection; outside seated measurement envelope");
      return; // Before axes are verified, raw up vectors are still available for setup.
    }
    pp::regions(tilt,regional);
    if(state==State::SETTLING && pp::elapsed(now,stateStart,SETTLE_MS)) {
      calibration.reset(); calStart=now;
      transition(State::CALIBRATING,"5 s neutral averaging; movement restarts window");
    }
    if(state==State::CALIBRATING) {
      bool still=true;
      for(uint8_t i=0;i<3;i++) if(!rest[i]||std::fabs(accelerationNorm[i]-G)>0.05*G) still=false;
      if(calibration.add(now,tilt,regional,still)) {
        calibration.baseline(baseline); baselineValid=true; alerts.reset();
        log.line("BASELINE sag=%.3f,%.3f lateral=%.3f,%.3f samples=%lu p2p_deg=%.3f,%.3f,%.3f,%.3f,%.3f,%.3f",
          baseline[0],baseline[1],baseline[2],baseline[3],(unsigned long)calibration.count,
          calibration.hi[0]-calibration.lo[0],calibration.hi[1]-calibration.lo[1],calibration.hi[2]-calibration.lo[2],
          calibration.hi[3]-calibration.lo[3],calibration.hi[4]-calibration.lo[4],calibration.hi[5]-calibration.lo[5]);
        transition(State::MONITORING,"neutral saved in RAM");
      } else if(pp::elapsed(now,calStart,CAL_TIMEOUT_MS)) fault("calibration timeout; unable to hold stable neutral");
    }
    if(!baselineValid) return;
    for(int i=0;i<4;i++) deviation[i]=pp::wrap(regional[i]-baseline[i]);
    if(state!=State::MONITORING && state!=State::ALERT) return;
    alerts.update(deviation,now,settings);
    if(alerts.alert && state!=State::ALERT) {
      if(!motor.start(MOTOR_RTP)) { fault("motor start/writeback failed"); return; }
      lastMotor=now; transition(State::ALERT,"regional persistence reached");
    } else if(!alerts.alert && state==State::ALERT) {
      if(stopOrFault()) transition(State::MONITORING,"both regions within recovery limits");
    }
  }
  void status() {
    log.line("STATUS state=%s mount_configured=%d mount_ok=%d baseline_valid=%d geometry_valid=%d fault=%s",
      stateName(state),mountConfigured,mountOK,baselineValid,geometryValid,faultMessage);
    log.line("SETTINGS trigger=%.2f,%.2f recovery=%.2f,%.2f duration_ms=%lu motor_rtp=%u (TUNING VALUES)",
      settings.trigger[0],settings.trigger[1],settings.recovery[0],settings.recovery[1],
      (unsigned long)settings.durationMs,MOTOR_RTP);
    log.line("BASELINE valid=%d sag=%.3f,%.3f lateral=%.3f,%.3f",baselineValid,baseline[0],baseline[1],baseline[2],baseline[3]);
    for(int i=0;i<3;i++) log.line("AXES imu=%d forward=%.2f,%.2f,%.2f left=%.2f,%.2f,%.2f head=%.2f,%.2f,%.2f",
      i,alignment[i].m[0][0],alignment[i].m[0][1],alignment[i].m[0][2],
      alignment[i].m[1][0],alignment[i].m[1][1],alignment[i].m[1][2],
      alignment[i].m[2][0],alignment[i].m[2][1],alignment[i].m[2][2]);
  }
  void help() {
    log.line("COMMANDS help | status | axes <headward signed axis> <outward signed axis> | mount-ok");
    log.line("COMMANDS calibrate | pause | resume | retry | set <upperTrigger> <upperRecovery> <lowerTrigger> <lowerRecovery> <durationMs>");
    log.line("EXAMPLE axes +Y +Z only if +Y points headward and +Z outward; mount-ok then holds neutral for >=15 s");
  }
  void command() {
    char* tokens[8]; int count=0; char* save=nullptr;
    for(char* t=strtok_r(input," \t",&save);t;t=strtok_r(nullptr," \t",&save)) {
      if(count==8) { log.line("ERR too many arguments"); return; } tokens[count++]=t;
    }
    if(!count) return;
    if(count==1&&!strcmp(tokens[0],"help")) { help(); return; }
    if(count==1&&!strcmp(tokens[0],"status")) { status(); return; }
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
    uint32_t now=millis(); if(!pp::elapsed(now,lastDiag,200)) return; lastDiag=now;
    uint32_t us=micros();
    log.line("DATA ms=%lu state=%s valid=%d sag=%.2f,%.2f lat=%.2f,%.2f total=%.2f base=%.2f,%.2f trig=%.2f,%.2f rec=%.2f,%.2f dur=%lu timer=%lu,%lu motor_req=%d motor=%s age_us=%lu,%lu,%lu skew_us=%lu rest=%d%d%d dropped=%lu",
      (unsigned long)now,stateName(state),baselineValid&&geometryValid&&state!=State::FAULT,
      deviation[0],deviation[1],deviation[2],deviation[3],pp::wrap(deviation[0]+deviation[1]),
      baseline[0],baseline[1],settings.trigger[0],settings.trigger[1],settings.recovery[0],settings.recovery[1],
      (unsigned long)settings.durationMs,
      (unsigned long)(alerts.timing[0]?now-alerts.start[0]:0),(unsigned long)(alerts.timing[1]?now-alerts.start[1]:0),
      motor.requested,motor.confirmed==pp::MotorConfirmation::UNKNOWN?"UNKNOWN":motor.confirmed==pp::MotorConfirmation::ON?"ON_REG":"OFF_REG",
      (unsigned long)(have[0]?us-stamp[0]:UINT32_MAX),(unsigned long)(have[1]?us-stamp[1]:UINT32_MAX),
      (unsigned long)(have[2]?us-stamp[2]:UINT32_MAX),(unsigned long)skew,rest[0],rest[1],rest[2],(unsigned long)log.dropped);
    // Raw up vectors expose incorrect orientation even when projected tilt is singular.
    log.line("SENSE upBody=%.3f,%.3f,%.3f;%.3f,%.3f,%.3f;%.3f,%.3f,%.3f tilt=%.2f,%.2f,%.2f samples=%lu,%lu,%lu maxgap_us=%lu,%lu,%lu cal_n=%lu",
      up[0].x,up[0].y,up[0].z,up[1].x,up[1].y,up[1].z,up[2].x,up[2].y,up[2].z,tilt[0],tilt[1],tilt[2],
      (unsigned long)samples[0],(unsigned long)samples[1],(unsigned long)samples[2],
      (unsigned long)maxGap[0],(unsigned long)maxGap[1],(unsigned long)maxGap[2],(unsigned long)calibration.count);
  }
public:
  PosturePal():bus(Wire),motor(bus),filters{VQF(filterParameters(),TS),VQF(filterParameters(),TS),VQF(filterParameters(),TS)} {
    for(int i=0;i<3;i++) alignment[i]={{{1,0,0},{0,1,0},{0,0,1}}}; // UNVERIFIED placeholder
  }
  void begin() {
    Serial.begin(115200); // No wait: battery operation must not depend on a USB host.
    Wire.begin(); Wire.setClock(400000);
    initialize(); help();
  }
  void tick() {
    serialInput();
    if(state!=State::FAULT) {
      uint32_t us=micros();
      if(pp::elapsed(us,lastPoll,POLL_US)) {
        lastPoll=us;
        for(uint8_t i=0;i<3;i++) if(!acquire(i)) break;
        if(state!=State::FAULT) evaluate();
      }
      uint32_t now=millis();
      if(state!=State::FAULT && pp::elapsed(now,lastMotor,250)) {
        lastMotor=now; if(!motor.check(MOTOR_RTP)) fault("motor state/status verification failed");
      }
      if(state!=State::FAULT && pp::elapsed(now,lastConfigCheck,1000)) {
        lastConfigCheck=now;
        if(!imuConfig(configSensor)) fault("periodic IMU configuration/identity check failed");
        configSensor=(configSensor+1)%3;
      }
    } else if(pp::elapsed(millis(),lastMotor,250)) {
      lastMotor=millis(); motor.stop(); // Remain latched FAULT even if shutdown succeeds.
    }
    diagnostics(); log.drain();
  }
};
PosturePal device;
} // namespace

void setup() { device.begin(); }
void loop() { device.tick(); }
