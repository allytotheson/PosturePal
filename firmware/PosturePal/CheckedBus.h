#pragma once
#include <cstddef>
#include <cstdint>

namespace pp {
// Wire-compatible template permits fault-injection tests with the same transactions.
template<class WireType> class CheckedBus {
  WireType& wire;
public:
  explicit CheckedBus(WireType& w):wire(w) {}
  bool select(uint8_t channel) {
    if(channel>7) return false;
    wire.beginTransmission(0x70); wire.write(uint8_t(1U<<channel));
    return wire.endTransmission()==0;
  }
  bool read(uint8_t addr,uint8_t reg,uint8_t* dst,size_t len) {
    wire.beginTransmission(addr); wire.write(reg);
    if(wire.endTransmission(false)!=0) return false;
    if(wire.requestFrom(addr,len,true)!=len) {
      while(wire.available()) wire.read(); return false;
    }
    for(size_t i=0;i<len;i++) { if(!wire.available()) return false; dst[i]=uint8_t(wire.read()); }
    return true;
  }
  bool write(uint8_t addr,uint8_t reg,uint8_t value) {
    wire.beginTransmission(addr); wire.write(reg); wire.write(value);
    return wire.endTransmission()==0;
  }
  bool verify(uint8_t addr,uint8_t reg,uint8_t value,uint8_t mask=0xff) {
    uint8_t got; return read(addr,reg,&got,1) && (got&mask)==(value&mask);
  }
  bool writeVerify(uint8_t addr,uint8_t reg,uint8_t value,uint8_t mask=0xff) {
    return write(addr,reg,value)&&verify(addr,reg,value,mask);
  }
};
enum class MotorConfirmation { UNKNOWN, OFF, ON };
template<class BusType> class Motor {
  BusType& bus;
public:
  bool requested=false;
  MotorConfirmation confirmed=MotorConfirmation::UNKNOWN;
  explicit Motor(BusType& b):bus(b) {}
  bool stop() {
    requested=false; confirmed=MotorConfirmation::UNKNOWN;
    if(!bus.select(3)) return false;
    // Try EVERY stop action even if a previous action failed. GO alone does not stop RTP.
    bool zero=bus.write(0x5a,0x02,0);
    bool go=bus.write(0x5a,0x0c,0);
    bool standby=bus.write(0x5a,0x01,0x40);
    bool zread=bus.verify(0x5a,0x02,0);
    bool mread=bus.verify(0x5a,0x01,0x40,0x47);
    if(zero&&go&&standby&&zread&&mread) { confirmed=MotorConfirmation::OFF; return true; }
    return false;
  }
  bool start(uint8_t amplitude) {
    requested=true; confirmed=MotorConfirmation::UNKNOWN;
    if(amplitude==0||amplitude>127||!bus.select(3)) return false;
    if(!bus.writeVerify(0x5a,0x02,0)||!bus.writeVerify(0x5a,0x01,5,0x47)||
       !bus.writeVerify(0x5a,0x02,amplitude)) return false;
    confirmed=MotorConfirmation::ON; return true;
  }
  bool check(uint8_t amplitude) {
    if(!bus.select(3)||!bus.verify(0x5a,0x02,requested?amplitude:0)||
       !bus.verify(0x5a,0x01,requested?5:0x40,0x47)) {
      confirmed=MotorConfirmation::UNKNOWN; return false;
    }
    uint8_t status;
    // DRV2605L status: device ID 7 (bits 7:5); over-temperature/over-current bits 1:0.
    if(!bus.read(0x5a,0,&status,1)||(status&0xe0)!=0xe0||(status&3)) {
      confirmed=MotorConfirmation::UNKNOWN; return false;
    }
    confirmed=requested?MotorConfirmation::ON:MotorConfirmation::OFF; return true;
  }
};
} // namespace pp
