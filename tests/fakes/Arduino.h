#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
extern uint32_t fakeUs;
inline uint32_t micros() { return fakeUs; }
inline uint32_t millis() { return fakeUs/1000; }
struct FakeSerial {
  bool connected=true; std::string input,output;
  void begin(unsigned long) {}
  explicit operator bool() const { return connected; }
  int available() const { return int(input.size()); }
  int read() { if(input.empty()) return -1; int c=input[0];input.erase(0,1);return c; }
  int availableForWrite() const { return connected?64:0; }
  size_t write(const uint8_t* p,size_t n) { output.append(reinterpret_cast<const char*>(p),n);return n; }
};
extern FakeSerial Serial;
