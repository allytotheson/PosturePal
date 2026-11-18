#pragma once
// Nordic UART UUIDs, ASCII newline protocol. No BLE dependency on the M4.
#if defined(ARDUINO_NRF52840_FEATHER)
#include <bluefruit.h>
namespace ppble {
BLEService service("6e400001-b5a3-f393-e0a9-e50e24dcca9e");
BLECharacteristic rx("6e400002-b5a3-f393-e0a9-e50e24dcca9e");
BLECharacteristic tx("6e400003-b5a3-f393-e0a9-e50e24dcca9e");
char incoming[160]={}, ready[160]={};
size_t incomingSize=0;
bool invalid=false, pending=false;
volatile bool resetPending=false;
char output[4096];
size_t head=0, tail=0, used=0;
uint32_t dropped=0;
void disconnected(uint16_t, uint8_t) {
  taskENTER_CRITICAL();
  incomingSize=0; invalid=false; pending=false; resetPending=true;
  taskEXIT_CRITICAL();
}
void received(uint16_t, BLECharacteristic*, uint8_t* data, uint16_t len) {
  taskENTER_CRITICAL();
  for(uint16_t i=0;i<len;i++) {
    uint8_t c=data[i];
    if(c=='\r') continue;
    if(c=='\n') {
      if(!pending) {
        if(invalid) strcpy(ready,"!invalid-ble-command");
        else {memcpy(ready,incoming,incomingSize);ready[incomingSize]=0;}
        pending=true;
      }
      incomingSize=0;invalid=false;
    } else if(c<32||c>126||incomingSize>=sizeof(incoming)-1) invalid=true;
    else incoming[incomingSize++]=char(c);
  }
  taskEXIT_CRITICAL();
}
bool connected() {return Bluefruit.connected() && tx.notifyEnabled();}
void begin() {
  Bluefruit.begin(1,0);
  Bluefruit.setName("PosturePal");
  service.begin();
  tx.setProperties(CHR_PROPS_NOTIFY);
  tx.setPermission(SECMODE_OPEN,SECMODE_NO_ACCESS);tx.setMaxLen(20);tx.begin();
  rx.setProperties(CHR_PROPS_WRITE);
  rx.setPermission(SECMODE_NO_ACCESS,SECMODE_OPEN);rx.setMaxLen(20);
  rx.setWriteCallback(received,false);rx.begin();
  Bluefruit.Periph.setDisconnectCallback(disconnected);
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addService(service);Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32,244);Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);
}
bool take(char* destination) {
  taskENTER_CRITICAL();
  bool result=pending;
  if(result) {strcpy(destination,ready);pending=false;}
  taskEXIT_CRITICAL();
  return result;
}
void line(const char* data,size_t n) {
  if(!connected()||resetPending) return;
  if(n>sizeof(output)-used) {++dropped;return;} // Drop complete lines only.
  for(size_t i=0;i<n;i++) {output[head]=data[i];head=(head+1)%sizeof(output);}
  used+=n;
}
void drain() {
  if(resetPending||!connected()) {used=0;tail=head;resetPending=false;return;}
  if(!used) return;
  uint16_t n=uint16_t(used>20?20:used);
  if(n>sizeof(output)-tail) n=uint16_t(sizeof(output)-tail);
  ble_gatts_hvx_params_t params={};
  params.handle=tx.handles().value_handle;params.type=BLE_GATT_HVX_NOTIFICATION;
  params.p_len=&n;params.p_data=reinterpret_cast<uint8_t*>(output+tail);
  // Call SoftDevice directly: the Bluefruit notify wrapper waits for a TX
  // semaphore when congested. Sampling must never wait for a BLE central.
  if(sd_ble_gatts_hvx(Bluefruit.connHandle(),&params)==NRF_SUCCESS) {
    tail=(tail+n)%sizeof(output);used-=n;
  }
}
}
#else
namespace ppble {
inline void begin() {}
inline bool connected() {return false;}
inline bool take(char*) {return false;}
inline void line(const char*,size_t) {}
inline void drain() {}
}
#endif
