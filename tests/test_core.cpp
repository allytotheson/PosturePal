#include "PostureCore.h"
#include "CheckedBus.h"
#include "vqf.hpp"
#include <cassert>
#include <cstdio>
#include <limits>
#include <vector>
#include <array>

static void near(double a,double b,double tolerance=1e-7) { assert(std::fabs(a-b)<tolerance); }
static pp::Alignment identity() { return {{{1,0,0},{0,1,0},{0,0,1}}}; }
static void multiply(const double a[4],const double b[4],double o[4]) {
  o[0]=a[0]*b[0]-a[1]*b[1]-a[2]*b[2]-a[3]*b[3];
  o[1]=a[0]*b[1]+a[1]*b[0]+a[2]*b[3]-a[3]*b[2];
  o[2]=a[0]*b[2]-a[1]*b[3]+a[2]*b[0]+a[3]*b[1];
  o[3]=a[0]*b[3]+a[1]*b[2]-a[2]*b[1]+a[3]*b[0];
}
static void geometry() {
  pp::Alignment a=identity(); assert(a.valid());
  double angle=20/pp::DEG, q[4]={std::cos(angle/2),0,std::sin(angle/2),0};
  pp::Vec up; double sag,lat;
  assert(pp::upFromQuaternion(q,a,up)&&pp::tilts(up,sag,lat)); near(sag,20); near(lat,0);
  double yaw[4]={std::cos(1.2),0,0,std::sin(1.2)},rotated[4]; multiply(yaw,q,rotated);
  assert(pp::upFromQuaternion(rotated,a,up)&&pp::tilts(up,sag,lat)); near(sag,20);
  for(double& v:rotated) v=-v;
  assert(pp::upFromQuaternion(rotated,a,up)&&pp::tilts(up,sag,lat)); near(sag,20);
  assert(!pp::tilts({0,1,0},sag,lat)); assert(!pp::tilts({1,0,0},sag,lat));
  q[0]=std::numeric_limits<double>::quiet_NaN(); assert(!pp::upFromQuaternion(q,a,up));
  assert(pp::makeAlignment("+Y","+Z",a)); assert(a.valid());
  up=a.apply({0,1,0}); near(up.z,1); near(up.x,0); near(up.y,0);
  up=a.apply({0,0,1}); near(up.x,-1);
  assert(!pp::makeAlignment("+Y","-Y",a)); assert(!pp::makeAlignment("Y","+Z",a));
  near(pp::wrap(359),-1); near(pp::wrap(-359),1);
  double tilt[6]={35,25,20,0,0,0},out[4]; pp::regions(tilt,out); near(out[0],10); near(out[1],5);
  for(int i=0;i<3;i++) tilt[i]-=20;
  pp::regions(tilt,out); near(out[0],10); near(out[1],5);
  // Sideways motion is measured but does not enter the sagittal alert input.
  tilt[3]=15; pp::regions(tilt,out); near(out[2],15); near(out[0],10);
}
static void alerts() {
  pp::Settings s; pp::AlertLogic a; double d[2]={8,0};
  a.update(d,100,s); a.update(d,2099,s); assert(!a.alert); a.update(d,2100,s); assert(a.alert);
  d[0]=6; a.update(d,2200,s); assert(a.alert); // inside trigger, outside recovery
  d[0]=4; d[1]=-4; a.update(d,2300,s); assert(!a.alert);
  d[0]=7.5; d[1]=0; a.update(d,3000,s); assert(!a.timing[0]);
  d[0]=8; a.update(d,3100,s); d[0]=0; d[1]=8; a.update(d,4500,s);
  a.update(d,6000,s); assert(!a.alert); a.update(d,6500,s); assert(a.alert);
  a.reset(); d[0]=-8; d[1]=0;
  a.update(d,UINT32_MAX-999,s); a.update(d,1000,s); assert(a.alert);
  a.reset(); assert(!a.alert&&!a.timing[0]&&!a.timing[1]);
  s.recovery[0]=s.trigger[0]; assert(!s.valid());
}
static void settings() {
  auto parse=[](const char* text,pp::Settings& s) {
    char copy[160]; std::strcpy(copy,text); char* tokens[10];int count=0;
    for(char* t=std::strtok(copy," ");t;t=std::strtok(nullptr," ")) tokens[count++]=t;
    return pp::parseSettings(tokens,count,s);
  };
  pp::Settings s; assert(parse("set 8 3 9 4 20000",s)); near(s.trigger[1],9); assert(s.durationMs==20000);
  for(const char* bad:{"set nan 3 9 4 2000","set 8 3 inf 4 2000","set 8 8 9 4 2000",
      "set 8 3 9 0 2000","set 8 3 9 4 -1","set 8 3 9 4 1.5","set 8 3 9 4 4294967297",
      "set 8 3 9 4 2000 extra","set 8 3 9 4","set 8x 3 9 4 2000"}) assert(!parse(bad,s));
}
static void calibration() {
  pp::Calibration c; double t[6]={179.9,0,0,0,0,0},r[4]={179.9,0,0,0};
  for(uint32_t i=0;i<=520;i++) {
    t[0]=(i%2)?-179.9:179.9; r[0]=t[0];
    bool done=c.add(i*10,t,r,true); if(i<500) assert(!done);
  }
  double b[4];c.baseline(b); assert(std::fabs(std::fabs(b[0])-180)<0.01);
  assert(!c.add(5300,t,r,false)); assert(c.count==0);
  c.add(5400,t,r,true); t[0]+=1.1; assert(!c.add(5410,t,r,true)); assert(c.count==0);
}
static void timing() {
  assert(!pp::sampleGap(100,0,false)); assert(!pp::sampleGap(15000,0,true));
  assert(pp::sampleGap(16000,0,true)); assert(pp::sampleGap(6000,UINT32_MAX-10000,true));
  uint32_t stamps[3]={UINT32_MAX-999,UINT32_MAX-1999,UINT32_MAX-2999},skew;
  assert(pp::freshFrame(1000,stamps,skew)); assert(skew==2000);
  assert(!pp::freshFrame(30000,stamps,skew));
  uint32_t skewed[3]={29000,28000,15000}; assert(!pp::freshFrame(30000,skewed,skew));
}
struct FakeWire {
  uint8_t addr=0,reg=0; std::vector<uint8_t> tx,rx; size_t index=0;
  uint8_t registers[256]={}; bool nack=false,shortRead=false,mismatch=false;
  std::vector<std::array<uint8_t,2>> writes;
  void beginTransmission(uint8_t a) {addr=a;tx.clear();}
  size_t write(uint8_t b) {tx.push_back(b);return 1;}
  uint8_t endTransmission(bool=true) {
    if(nack) return 2;
    if(addr!=0x70 && !tx.empty()) {
      reg=tx[0]; if(tx.size()==2) {registers[reg]=tx[1];writes.push_back({{reg,tx[1]}});}
    }
    return 0;
  }
  size_t requestFrom(uint8_t,size_t n,bool) {
    rx.clear();index=0;if(shortRead && n) --n;
    for(size_t i=0;i<n;i++) rx.push_back(registers[uint8_t(reg+i)]^(mismatch?1:0));
    return n;
  }
  int available() {return int(rx.size()-index);}
  int read() {return available()?rx[index++]:-1;}
};
static void communication() {
  FakeWire w; pp::CheckedBus<FakeWire> bus(w); pp::Motor<pp::CheckedBus<FakeWire>> motor(bus);
  w.registers[0]=0xe0;
  assert(bus.select(2)); assert(!bus.select(8)); assert(motor.stop()); assert(!motor.requested);
  assert(motor.confirmed==pp::MotorConfirmation::OFF); assert(motor.start(32)); assert(motor.check(32));
  w.mismatch=true; assert(!motor.stop()); assert(!motor.requested);
  assert(motor.confirmed==pp::MotorConfirmation::UNKNOWN);
  // Stop attempts GO and standby despite failed readback, and never claims physical confirmation.
  assert(w.registers[2]==0&&w.registers[1]==0x40&&w.registers[12]==0);
  w.mismatch=false; w.nack=true; assert(!motor.stop()); assert(!motor.start(32));
  w.nack=false; w.shortRead=true; uint8_t data[12]; assert(!bus.read(0x6a,0x22,data,12));
  assert(!motor.stop());w.shortRead=false;assert(motor.stop());
  assert(motor.start(32));w.registers[0]=0xe1;assert(!motor.check(32));
  assert(motor.confirmed==pp::MotorConfirmation::UNKNOWN);
}
static void actualVQF() {
  VQF filter(1.0/104); const vqf_real_t g[3]={0,0,0},acc[3]={0,0,9.80665};
  for(int i=0;i<2080;i++) filter.update(g,acc);
  assert(filter.getRestDetected()); vqf_real_t q[4];filter.getQuat6D(q);
  pp::Vec up;double sag,lat; assert(pp::upFromQuaternion(q,identity(),up));
  assert(pp::tilts(up,sag,lat));near(sag,0,1e-4);near(lat,0,1e-4);
  // Bias present at rest: test official estimator, not a mock of its API.
  filter.resetState(); const vqf_real_t biased[3]={0.005,-0.004,0.003};
  for(int i=0;i<3120;i++) filter.update(biased,acc);
  vqf_real_t bias[3];filter.getBiasEstimate(bias);
  for(int i=0;i<3;i++) near(bias[i],biased[i],0.0008);
}
int main() {
  geometry();alerts();settings();calibration();timing();communication();actualVQF();
  std::puts("PASS: geometry, heading invariance, timers/hysteresis/rollover, parsing, calibration, freshness, bus/motor faults, official VQF");
}
