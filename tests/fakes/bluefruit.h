#pragma once
#include <string>
#include <cstdint>
#include <cstddef>
#define taskENTER_CRITICAL() do {} while(0)
#define taskEXIT_CRITICAL() do {} while(0)
constexpr int CHR_PROPS_NOTIFY=1, CHR_PROPS_WRITE=2, SECMODE_OPEN=1, SECMODE_NO_ACCESS=0;
constexpr int BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE=1, BLE_GATT_HVX_NOTIFICATION=1;
constexpr uint32_t NRF_SUCCESS=0;
struct ble_gatts_char_handles_t {uint16_t value_handle=1;};
struct ble_gatts_hvx_params_t {uint16_t handle=0;uint8_t type=0;uint16_t offset=0;uint16_t* p_len=nullptr;uint8_t* p_data=nullptr;};
struct BLEService {explicit BLEService(const char*) {} void begin() {} };
struct BLECharacteristic {
  bool subscribed=true;
  explicit BLECharacteristic(const char*) {}
  void setProperties(int) {} void setPermission(int,int) {} void setMaxLen(int) {} void begin() {}
  void setWriteCallback(void(*)(uint16_t,BLECharacteristic*,uint8_t*,uint16_t),bool) {}
  bool notifyEnabled() {return subscribed;}
  ble_gatts_char_handles_t handles() {return {};}
};
struct FakeBluefruit {
  bool online=true;
  struct Peripheral {void setDisconnectCallback(void(*)(uint16_t,uint8_t)) {}} Periph;
  struct Advertiser {
    void addFlags(int) {} void addService(BLEService&) {} void addName() {}
    void restartOnDisconnect(bool) {} void setInterval(int,int) {} void setFastTimeout(int) {} void start(int) {}
  } Advertising, ScanResponse;
  void begin(int,int) {} void setName(const char*) {} bool connected() {return online;} uint16_t connHandle() {return 0;}
};
extern FakeBluefruit Bluefruit;
extern bool congested;
extern std::string bleOutput;
inline uint32_t sd_ble_gatts_hvx(uint16_t,ble_gatts_hvx_params_t* p) {
  if(congested) return 1;
  bleOutput.append(reinterpret_cast<char*>(p->p_data),*p->p_len);return NRF_SUCCESS;
}
