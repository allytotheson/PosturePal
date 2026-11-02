#pragma once
#include "Arduino.h"
#include <cmath>
#include <vector>
struct TwoWire {
  uint8_t channel=0,addr=0,reg=0;
  uint8_t sensorRegs[3][256]={},motorRegs[256]={};
  bool sensorNack[3]={},freeze[3]={},motorNack=false,muxNack=false,shortRead=false;
  double angle[3]={},gyroY[3]={};
  uint32_t lastSample[3]={};
  std::vector<uint8_t> tx,rx;size_t pos=0;
  TwoWire() { motorRegs[0]=0xe0; for(int i=0;i<3;i++)sensorRegs[i][15]=0x6c; }
  void begin() {} void setClock(uint32_t) {}
  void beginTransmission(uint8_t a) {addr=a;tx.clear();}
  size_t write(uint8_t v) {tx.push_back(v);return 1;}
  uint8_t endTransmission(bool=true) {
    if(addr==0x70) {
      if(muxNack)return 2;
      for(int i=0;i<8;i++)if(tx[0]==(1<<i))channel=uint8_t(i);
      return 0;
    }
    if((channel<3&&sensorNack[channel])||(channel==3&&motorNack))return 2;
    reg=tx[0];
    if(tx.size()==2) {
      if(channel==3)motorRegs[reg]=tx[1];else if(channel<3)sensorRegs[channel][reg]=tx[1];
    }
    return 0;
  }
  static void put(std::vector<uint8_t>& data,size_t index,double value) {
    uint16_t word=uint16_t(int16_t(std::round(value)));
    data[index]=uint8_t(word);data[index+1]=uint8_t(word>>8);
  }
  size_t requestFrom(uint8_t,size_t n,bool) {
    rx.assign(n,0);pos=0;
    if(channel<3) {
      if(reg==0x1e&&n==1)rx[0]=!freeze[channel]&&fakeUs/9615!=lastSample[channel]?3:0;
      else if(reg==0x22&&n==12) {
        lastSample[channel]=fakeUs/9615;
        double radians=angle[channel]*3.141592653589793/180;
        put(rx,2,gyroY[channel]/0.00875);
        put(rx,6,-std::sin(radians)/0.000061);
        put(rx,10,std::cos(radians)/0.000061);
      } else for(size_t i=0;i<n;i++)rx[i]=sensorRegs[channel][uint8_t(reg+i)];
    } else if(channel==3)for(size_t i=0;i<n;i++)rx[i]=motorRegs[uint8_t(reg+i)];
    if(shortRead&&n)rx.pop_back();
    return rx.size();
  }
  int available() {return int(rx.size()-pos);}
  int read() {return available()?rx[pos++]:-1;}
};
extern TwoWire Wire;
