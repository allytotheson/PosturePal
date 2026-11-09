// Execute the actual sketch state machine and official VQF, with a simulated I2C bus.
// This does NOT model bus timing, motor physics, electrical faults or garment motion.
#include "Arduino.h"
#include "Wire.h"
#include <cassert>
#include <cstdio>
uint32_t fakeUs=0;
FakeSerial Serial;
TwoWire Wire;
#include "../firmware/PosturePal/PosturePal.ino"

static void advance(uint32_t ms) {for(uint32_t i=0;i<ms;i++){fakeUs+=1000;loop();}}
static bool outputHas(const char* s) {return Serial.output.find(s)!=std::string::npos;}
static void send(const char* s) {Serial.output.clear();Serial.input=std::string(s)+"\n";advance(100);}
static void move(double a,double b,double c,uint32_t ms) {
  double start[3]={Wire.angle[0],Wire.angle[1],Wire.angle[2]},target[3]={a,b,c};
  for(int j=0;j<3;j++)Wire.gyroY[j]=(target[j]-start[j])*1000/ms;
  for(uint32_t i=1;i<=ms;i++) {
    for(int j=0;j<3;j++)Wire.angle[j]=start[j]+(target[j]-start[j])*i/ms;
    advance(1);
  }
  for(int j=0;j<3;j++)Wire.gyroY[j]=0;
}
int main() {
  setup();advance(3000);
  assert(Wire.clockHz==400000);
  assert(Wire.motorRegs[0x17]==138);assert((Wire.motorRegs[0x1d]&0x68)==0x20);
  assert(!outputHas("upper_deg="));assert(!outputHas("SENSE"));
  send("sense");assert(outputHas("SENSE imu=0")); // Explicit diagnostics remain available.
  send("status");assert(outputHas("trigger=7.50,7.50 recovery=4.00,4.00 duration_ms=2000"));
  assert(Wire.motorRegs[2]==0); send("resume");assert(outputHas("ERR mounting"));
  send("mount-ok");assert(outputHas("ERR configure axes"));
  // Virtual fixture: +Z headward and -X outward -> identity mapping.
  send("axes +Z -X");send("mount-ok");assert(outputHas("SETTLING"));
  advance(5500);send("status");assert(outputHas("state=MONITORING"));assert(outputHas("baseline_valid=1"));
  assert(outputHas("POSTUREPAL firmware=feather-v3"));
  assert(outputHas("TIMING max_loop_us="));
  send("calibrate");advance(3200);assert(outputHas("CAL "));
  assert(!outputHas("upper_deg="));assert(!outputHas("BASELINE sag="));
  advance(2300);send("status");assert(outputHas("state=MONITORING"));
  Serial.output.clear();advance(3000);
  size_t lines=0,pos=0;
  while((pos=Serial.output.find("upper_deg=",pos))!=std::string::npos) { ++lines; ++pos; }
  assert(lines==3); // One compact reading per second.
  // Simulated fixed gyro bias: no neutral drift alert, no baseline adaptation
  // during a sustained slouch, and recovery when the actual fixture returns.
  Wire.gyroBiasY[2]=1.0;advance(30000);assert(Wire.motorRegs[2]==0);
  move(15,5,0,2000);advance(20000);assert(Wire.motorRegs[2]==127);
  move(0,0,0,2000);advance(5000);assert(Wire.motorRegs[2]==0);
  Serial.output.clear();advance(30000);
  size_t last=Serial.output.rfind("upper_deg=");assert(last!=std::string::npos);
  double upper,lower;
  assert(std::sscanf(Serial.output.c_str()+last,"upper_deg=%lf lower_deg=%lf",&upper,&lower)==2);
  assert(std::fabs(upper)<1.0&&std::fabs(lower)<1.0);
  send("sense");assert(outputHas("neutral_delta_deg="));assert(outputHas("filter_minus_gravity_deg="));
  assert(outputHas("mean_hz="));
  Wire.gyroBiasY[2]=0;
  send("set 5 3 5 3 200");assert(outputHas("ACK settings"));
  send("set nan 3 5 3 200");assert(outputHas("ERR set"));
  send("set 5 3 5 3 200 extra");assert(outputHas("ERR set"));
  send("pause extra");assert(outputHas("ERR unknown"));
  send(std::string(200,'x').c_str());assert(outputHas("command too long"));
  Serial.output.clear();move(10,10,10,1000);advance(1500);
  assert(!outputHas("state=ALERT"));assert(Wire.motorRegs[2]==0);
  move(0,0,0,1000);advance(1000);
  Serial.output.clear();move(10,0,0,1000);advance(1000);
  assert(outputHas("state=ALERT"));assert(Wire.motorRegs[2]==127);
  // Sustained bad posture must keep continuous RTP drive, without pulse gaps.
  Serial.output.clear();
  for(int i=0;i<50;i++) {
    advance(100);
    assert(Wire.motorRegs[2]==127);assert(Wire.motorRegs[1]==5);
  }
  assert(outputHas("buzz=1"));
  assert(outputHas("upper_deg="));assert(outputHas("lower_deg="));
  assert(!outputHas("SENSE"));assert(!outputHas("trigger_deg="));
  move(4,0,0,1000);advance(1000);assert(Wire.motorRegs[2]==127); // hysteresis
  Serial.output.clear();
  move(0,0,0,1000);advance(1000);assert(Wire.motorRegs[2]==0);assert(Wire.motorRegs[1]==0x40);
  assert(outputHas("buzz=0"));
  move(10,0,0,1000);advance(1000);assert(Wire.motorRegs[2]==127);
  send("pause");assert(Wire.motorRegs[2]==0);assert(outputHas("state=PAUSED"));
  Serial.output.clear();advance(1200);assert(!outputHas("upper_deg="));
  send("resume");advance(1000);assert(Wire.motorRegs[2]==127);
  // Sensor fault must stop an already active alert and latch FAULT.
  Wire.sensorNack[1]=true;Serial.output.clear();advance(500);
  assert(outputHas("state=FAULT"));assert(Wire.motorRegs[2]==0);assert(Wire.motorRegs[1]==0x40);
  assert(!outputHas("upper_deg="));
  send("resume");assert(outputHas("FAULT latched"));
  Wire.sensorNack[1]=false;send("retry");assert(outputHas("state=SETTLING"));
  assert(Wire.clockHz==400000);
  advance(15500);send("status");assert(outputHas("state=MONITORING"));
  // An unresponsive motor must remain UNKNOWN until a checked shutdown succeeds.
  move(20,0,0,1000);advance(1000);assert(Wire.motorRegs[2]==127);
  Wire.motorNack=true;Serial.output.clear();advance(500);
  assert(outputHas("state=FAULT"));assert(outputHas("stop=UNKNOWN"));
  send("status");assert(outputHas("buzz=0 motor=UNKNOWN")); // manual confirmation details
  assert(Wire.motorRegs[2]==127); // demonstrates why software cannot guarantee physical stop
  Wire.motorNack=false;advance(500);assert(Wire.motorRegs[2]==0);
  send("retry");advance(15500);
  Wire.freeze[0]=true;Serial.output.clear();advance(500);
  assert(outputHas("data-ready timeout"));assert(Wire.motorRegs[2]==0);
  // Acquisition continues without a USB host after initialization, and never blocks on printing.
  Wire.freeze[0]=false;send("retry");Serial.connected=false;advance(16000);
  assert(Wire.motorRegs[2]==0);Serial.connected=true;send("status");assert(outputHas("state=MONITORING"));
  // Pure forward lean near horizontal used to fault on the unused lateral projection.
  Serial.output.clear();move(85,85,85,3000);advance(6000);send("status");
  assert(outputHas("geometry_valid=1"));assert(!outputHas("state=FAULT"));
  send("calibrate");advance(5500);send("status");assert(outputHas("state=MONITORING"));
  // A small raw gyro offset must not block an otherwise stable calibration.
  for(int i=0;i<3;i++) Wire.gyroY[i]=1.0;
  send("calibrate");advance(7000);send("status");assert(outputHas("state=MONITORING"));
  for(int i=0;i<3;i++) Wire.gyroY[i]=10.0;
  send("calibrate");advance(5000);assert(outputHas("sensor moving too quickly"));
  send("status");assert(outputHas("state=CALIBRATING"));
  for(int i=0;i<3;i++) Wire.gyroY[i]=0;
  advance(10000);send("status");assert(outputHas("state=MONITORING"));
  // A real scheduling discontinuity remains a fault; include the sensor and duration.
  fakeUs+=20000;advance(100);send("status");
  assert(outputHas("fault=IMU gap imu=0 gap_us="));
  assert(outputHas("limit_us=16000"));assert(Wire.motorRegs[2]==0);
  Wire.sensorNack[1]=true;send("scan");advance(300);
  assert(outputHas("BUS hz=100000 channel=0 addr=0x6A read=OK id=0x6C lsm6dsox=1"));
  assert(outputHas("BUS hz=400000 channel=0 addr=0x6A read=OK"));
  assert(outputHas("channel=1 addr=0x6A read=FAIL"));assert(outputHas("BUS scan complete"));
  assert(Wire.clockHz==400000);Wire.sensorNack[1]=false;
  Wire.muxNack=true;send("scan");advance(300);assert(outputHas("mux_0x70=FAIL"));Wire.muxNack=false;
  // Explicit opt-out works from FAULT with the motor driver completely absent.
  Wire.motorNack=true;send("motor off");assert(outputHas("MODE sensor-only"));
  uint32_t accesses=Wire.motorAccesses;
  advance(7000);send("status");assert(outputHas("state=MONITORING"));
  assert(outputHas("motor=DISABLED enabled=0"));assert(Wire.motorAccesses==accesses);
  move(100,85,85,2000);advance(3000);
  assert(outputHas("state=ALERT"));assert(outputHas("buzz=1"));
  assert(Wire.motorRegs[2]==0);assert(Wire.motorAccesses==accesses);
  move(85,85,85,2000);advance(3000);send("status");
  assert(outputHas("state=MONITORING"));assert(outputHas("buzz=0 motor=DISABLED"));
  send("retry");advance(7000);assert(Wire.motorAccesses==accesses);
  send("motor on");assert(outputHas("initial motor stop failed"));
  Wire.motorNack=false;send("retry");advance(7000);send("status");
  assert(outputHas("state=MONITORING"));assert(outputHas("motor=OFF_REG enabled=1"));
  Wire.rawAccelX[1]=32100;advance(100);send("status");
  assert(outputHas("IMU near full-scale imu=1 channel=1 source=accel axis=X raw=32100 limit=32000"));
  assert(Wire.motorRegs[2]==0);
  send("motor-on");assert(outputHas("with a space; mode unchanged"));assert(!outputHas("EVENT"));
  Wire.rawAccelX[1]=0;send("retry");advance(7000);
  Wire.motorRegs[0x17]=255;advance(300);send("status");
  assert(outputHas("motor state/status/voltage-clamp verification failed"));assert(Wire.motorRegs[2]==0);
  send("retry");advance(7000);assert(Wire.motorRegs[0x17]==138);
  Wire.rawGyroX[2]=-32200;advance(100);send("status");
  assert(outputHas("source=gyro axis=X raw=-32200 limit=32000"));
  std::puts("PASS: actual sketch boot/mount gate, calibration, commands, common lean, alert/recovery, pause/resume, sensor/motor faults, retry, no-USB monitoring");
}
