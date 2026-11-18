#include <cstring>
#include <cassert>
#include "bluefruit.h"
FakeBluefruit Bluefruit;
bool congested=false;
std::string bleOutput;
#include "PostureBle.h"
void receive(const std::string& s) {
  ppble::received(0,nullptr,reinterpret_cast<uint8_t*>(const_cast<char*>(s.data())),uint16_t(s.size()));
}
int main() {
  ppble::begin();char command[160];
  receive("set 7.5 4 ");assert(!ppble::take(command));
  receive("7.5 4 2000\r\n");assert(ppble::take(command));assert(!strcmp(command,"set 7.5 4 7.5 4 2000"));
  receive(std::string(160,'x')+"\n");assert(ppble::take(command));assert(!strcmp(command,"!invalid-ble-command"));
  receive(std::string("pause\0resume\n",13));assert(ppble::take(command));assert(!strcmp(command,"!invalid-ble-command"));
  receive("pause\nresume\n");assert(ppble::take(command));assert(!strcmp(command,"pause"));assert(!ppble::take(command));
  receive("res");ppble::disconnected(0,0);ppble::drain();receive("ume\n");assert(ppble::take(command));assert(!strcmp(command,"ume"));
  std::string line(639,'a');line+='\n';
  ppble::line(line.data(),line.size());congested=true;ppble::drain();assert(bleOutput.empty());assert(ppble::used==640);
  congested=false;while(ppble::used)ppble::drain();assert(bleOutput==line);
  // Ring wrapping and whole-line overflow preserve framing.
  bleOutput.clear();for(int i=0;i<10;i++){ppble::line(line.data(),line.size());while(ppble::used)ppble::drain();}assert(bleOutput.size()==6400);
  for(int i=0;i<7;i++)ppble::line(line.data(),line.size());assert(ppble::dropped==1);assert(ppble::used==3840);
  ppble::disconnected(0,0);ppble::drain();assert(ppble::used==0);
  Bluefruit.online=false;ppble::line(line.data(),line.size());assert(ppble::used==0);
}
