#pragma once
#include "Wire.h"
struct Adafruit_DRV2605 {bool begin(TwoWire* wire) {wire->begin();return true;}};
