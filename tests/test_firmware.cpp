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
  assert(Wire.motorRegs[2]==0); send("resume");assert(outputHas("ERR mounting"));
  send("mount-ok");assert(outputHas("ERR configure axes"));
  // Virtual fixture: +Z headward and -X outward -> identity mapping.
  send("axes +Z -X");send("mount-ok");assert(outputHas("SETTLING"));
  advance(15500);send("status");assert(outputHas("state=MONITORING"));assert(outputHas("baseline_valid=1"));
  send("set 5 3 5 3 200");assert(outputHas("ACK settings"));
  send("set nan 3 5 3 200");assert(outputHas("ERR set"));
  send("set 5 3 5 3 200 extra");assert(outputHas("ERR set"));
  send("pause extra");assert(outputHas("ERR unknown"));
  send(std::string(200,'x').c_str());assert(outputHas("command too long"));
  Serial.output.clear();move(10,10,10,1000);advance(1500);
  assert(!outputHas("state=ALERT"));assert(Wire.motorRegs[2]==0);
  move(0,0,0,1000);advance(1000);
  Serial.output.clear();move(10,0,0,1000);advance(1000);
  assert(outputHas("state=ALERT"));assert(Wire.motorRegs[2]==32);
  move(4,0,0,1000);advance(1000);assert(Wire.motorRegs[2]==32); // hysteresis
  move(0,0,0,1000);advance(1000);assert(Wire.motorRegs[2]==0);assert(Wire.motorRegs[1]==0x40);
  move(10,0,0,1000);advance(1000);assert(Wire.motorRegs[2]==32);
  send("pause");assert(Wire.motorRegs[2]==0);assert(outputHas("state=PAUSED"));
  send("resume");advance(1000);assert(Wire.motorRegs[2]==32);
  // Sensor fault must stop an already active alert and latch FAULT.
  Wire.sensorNack[1]=true;Serial.output.clear();advance(500);
  assert(outputHas("state=FAULT"));assert(Wire.motorRegs[2]==0);assert(Wire.motorRegs[1]==0x40);
  send("resume");assert(outputHas("FAULT latched"));
  Wire.sensorNack[1]=false;send("retry");assert(outputHas("state=SETTLING"));
  advance(15500);send("status");assert(outputHas("state=MONITORING"));
  // An unresponsive motor must remain UNKNOWN until a checked shutdown succeeds.
  move(20,0,0,1000);advance(1000);assert(Wire.motorRegs[2]==32);
  Wire.motorNack=true;Serial.output.clear();advance(500);
  assert(outputHas("state=FAULT"));assert(outputHas("motor=UNKNOWN"));
  assert(Wire.motorRegs[2]==32); // demonstrates why software cannot guarantee physical stop
  Wire.motorNack=false;advance(500);assert(Wire.motorRegs[2]==0);
  send("retry");advance(15500);
  Wire.freeze[0]=true;Serial.output.clear();advance(500);
  assert(outputHas("data-ready timeout"));assert(Wire.motorRegs[2]==0);
  // Acquisition continues without a USB host after initialization, and never blocks on printing.
  Wire.freeze[0]=false;send("retry");Serial.connected=false;advance(16000);
  assert(Wire.motorRegs[2]==0);Serial.connected=true;send("status");assert(outputHas("state=MONITORING"));
  std::puts("PASS: actual sketch boot/mount gate, calibration, commands, common lean, alert/recovery, pause/resume, sensor/motor faults, retry, no-USB monitoring");
}
