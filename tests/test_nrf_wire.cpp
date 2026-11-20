// Execute the actual replacement methods against a TWIM register model.
// A simulated CPU preemption at LAST-byte time keeps clocks running unless a
// hardware shortcut was installed BEFORE START. This does not model wiring/RF.
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <initializer_list>

constexpr uint32_t TWIM_SHORTS_LASTRX_STOP_Msk=1u<<12;
constexpr uint32_t TWIM_SHORTS_LASTRX_SUSPEND_Msk=1u<<11;
constexpr uint32_t TWIM_SHORTS_LASTTX_STOP_Msk=1u<<9;
constexpr uint32_t TWIM_SHORTS_LASTTX_SUSPEND_Msk=1u<<8;
constexpr uint32_t TWIM_ERRORSRC_ANACK_Msk=2, TWIM_ERRORSRC_DNACK_Msk=4;
struct FakeTwim;
enum Kind { VALUE, ERROR_SOURCE, START_RX, START_TX, STOP, SUSPEND, RESUME };
struct Register {
  FakeTwim* owner=nullptr;Kind kind=VALUE;uintptr_t value=0;
  Register()=default;
  Register(FakeTwim* p,Kind k):owner(p),kind(k) {}
  Register& operator=(uintptr_t v);
  Register& operator=(const Register& other) {return *this=uintptr_t(other);}
  operator uintptr_t() const {return value;}
};
struct FakeTwim {
  struct Dma {uintptr_t PTR=0,MAXCNT=0,AMOUNT=0;} RXD,TXD;
  Register ADDRESS,SHORTS,EVENTS_STOPPED,EVENTS_SUSPENDED,EVENTS_ERROR,EVENTS_TXSTARTED;
  Register ERRORSRC{this,ERROR_SOURCE},TASKS_RESUME{this,RESUME};
  Register TASKS_STARTRX{this,START_RX},TASKS_STARTTX{this,START_TX};
  Register TASKS_STOP{this,STOP},TASKS_SUSPEND{this,SUSPEND};
  bool nackAddress=false,nackData=false,shortRead=false,active=false;
  unsigned extraClocked=0,delayBytes=7,starts=0,stops=0,suspends=0;
  void start(bool read) {
    ++starts;active=true;
    if(nackAddress||nackData) {
      EVENTS_ERROR.value=1;ERRORSRC.value=nackAddress?TWIM_ERRORSRC_ANACK_Msk:TWIM_ERRORSRC_DNACK_Msk;
      RXD.AMOUNT=TXD.AMOUNT=0;return;
    }
    if(read) {
      RXD.AMOUNT=RXD.MAXCNT-(shortRead?1:0);
      auto* data=reinterpret_cast<uint8_t*>(RXD.PTR);
      for(size_t i=0;i<RXD.AMOUNT;i++)data[i]=uint8_t(7+i);
    } else {TXD.AMOUNT=TXD.MAXCNT;EVENTS_TXSTARTED.value=1;}
    uint32_t stopMask=read?TWIM_SHORTS_LASTRX_STOP_Msk:TWIM_SHORTS_LASTTX_STOP_Msk;
    uint32_t suspendMask=read?TWIM_SHORTS_LASTRX_SUSPEND_Msk:TWIM_SHORTS_LASTTX_SUSPEND_Msk;
    if(SHORTS.value&stopMask) {EVENTS_STOPPED.value=1;active=false;++stops;}
    else if(SHORTS.value&suspendMask) {EVENTS_SUSPENDED.value=1;active=false;++suspends;}
    else if(read||TXD.MAXCNT) extraClocked+=delayBytes;
  }
};
Register& Register::operator=(uintptr_t v) {
  if(kind==ERROR_SOURCE) {value&=~v;return *this;}
  value=v;
  if(!owner||!v)return *this;
  if(kind==START_RX)owner->start(true);
  if(kind==START_TX)owner->start(false);
  if(kind==STOP) {owner->EVENTS_STOPPED.value=1;owner->active=false;++owner->stops;}
  if(kind==SUSPEND) {owner->EVENTS_SUSPENDED.value=1;owner->active=false;++owner->suspends;}
  return *this;
}
struct Buffer {
  uint8_t _aucBuffer[256]={};size_t _iHead=0;
  void clear() {_iHead=0;}
  size_t available() const {return _iHead;}
};
struct TwoWire {
  FakeTwim* _p_twim;Buffer rxBuffer,txBuffer;
  bool transmissionBegun=false;uint8_t txAddress=0x6a;
  explicit TwoWire(FakeTwim& p):_p_twim(&p) {}
  uint8_t requestFrom(uint8_t,size_t,bool);
  uint8_t endTransmission(bool);
};
#include "../tools/nrf_wire_master.inc"

int main() {
  // Negative control: software-only STOP lets hardware over-read while the CPU
  // is delayed, even though DMA still reports the requested byte count.
  FakeTwim legacy;uint8_t byte=0;
  legacy.RXD.PTR=reinterpret_cast<uintptr_t>(&byte);legacy.RXD.MAXCNT=1;
  legacy.TASKS_STARTRX=1;legacy.TASKS_STOP=1;
  assert(legacy.extraClocked==7&&legacy.RXD.AMOUNT==1);

  FakeTwim hw;TwoWire wire(hw);
  for(size_t count : {size_t(1),size_t(12),size_t(255)}) {
    assert(wire.requestFrom(0x6a,count,true)==count);
    assert(wire.rxBuffer.available()==count);
    assert(wire.rxBuffer._aucBuffer[0]==7);
    assert(hw.extraClocked==0&&!hw.active&&hw.SHORTS.value==0);
  }
  auto starts=hw.starts;
  assert(wire.requestFrom(0x6a,0,true)==0);
  assert(wire.requestFrom(0x6a,256,true)==0);
  assert(hw.starts==starts&&wire.rxBuffer.available()==0);
  hw.shortRead=true;assert(wire.requestFrom(0x6a,12,true)==11);
  hw.shortRead=false;
  // Register-pointer write is suspended at its last byte; repeated-start read
  // then stops at its last byte with no CPU-dependent clocks on either leg.
  wire.txBuffer._iHead=1;
  assert(wire.endTransmission(false)==0);assert(hw.suspends==1);
  assert(wire.requestFrom(0x6a,12,true)==12);assert(hw.extraClocked==0);
  assert(wire.requestFrom(0x6a,1,false)==1);assert(hw.suspends==2);
  wire.txBuffer._iHead=2;assert(wire.endTransmission(true)==0);
  assert(hw.extraClocked==0);
  // Empty address probes retain the core API and error recovery cannot expose
  // stale bytes/events as a successful following transfer.
  wire.txBuffer._iHead=0;assert(wire.endTransmission(true)==0);
  hw.nackAddress=true;
  assert(wire.requestFrom(0x6a,1,true)==0);assert(wire.rxBuffer.available()==0);
  assert(!hw.active&&hw.ERRORSRC.value==0);
  assert(wire.endTransmission(true)==2);
  hw.nackAddress=false;hw.nackData=true;wire.txBuffer._iHead=1;
  assert(wire.endTransmission(false)==3);assert(!hw.active);
  hw.nackData=false;assert(wire.endTransmission(false)==0);
  assert(wire.requestFrom(0x6a,1,true)==1);assert(hw.extraClocked==0);
  std::puts("PASS: actual nRF Wire replacement methods, delayed CPU, STOP/SUSPEND, repeated start, bounds, NACK/recovery");
}
