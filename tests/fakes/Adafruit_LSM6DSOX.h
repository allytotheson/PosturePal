#pragma once
#include "Wire.h"
enum { LSM6DS_ACCEL_RANGE_2_G=0,LSM6DS_GYRO_RANGE_250_DPS=0,LSM6DS_RATE_104_HZ=4 };
struct Adafruit_LSM6DSOX {
  bool begin_I2C(uint8_t,TwoWire*) {return true;}
  void setAccelRange(int) {} void setGyroRange(int) {}
  void setAccelDataRate(int) {Wire.sensorRegs[Wire.channel][0x10]=0x40;}
  void setGyroDataRate(int) {Wire.sensorRegs[Wire.channel][0x11]=0x40;}
};
