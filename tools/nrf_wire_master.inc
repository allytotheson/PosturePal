/*
 * Adapted from Adafruit nRF52 core 1.7.0, libraries/Wire/Wire_nRF52.cpp.
 * Copyright (c) 2015 Arduino LLC. All rights reserved.
 * Copyright (c) 2016 Sandeep Mistry. All rights reserved.
 * Modifications: PosturePal contributors, 2026.
 * SPDX-License-Identifier: LGPL-2.1-or-later
 *
 * Install LAST-byte shortcuts before START, then wait for completion, rather
 * than relying on the CPU to issue STOP/SUSPEND within one I2C byte time.
 * Interrupts, including the SoftDevice, remain enabled throughout.
 */

uint8_t TwoWire::requestFrom(uint8_t address, size_t quantity, bool stopBit)
{
  rxBuffer.clear();
  if (!quantity || quantity > 255 || quantity > sizeof(rxBuffer._aucBuffer)) return 0;
  _p_twim->ADDRESS = address;
  _p_twim->EVENTS_STOPPED = 0;
  _p_twim->EVENTS_SUSPENDED = 0;
  _p_twim->EVENTS_ERROR = 0;
  _p_twim->ERRORSRC = _p_twim->ERRORSRC;
  _p_twim->RXD.PTR = reinterpret_cast<uintptr_t>(rxBuffer._aucBuffer);
  _p_twim->RXD.MAXCNT = quantity;
  _p_twim->SHORTS = stopBit ? TWIM_SHORTS_LASTRX_STOP_Msk : TWIM_SHORTS_LASTRX_SUSPEND_Msk;
  _p_twim->TASKS_RESUME = 1;
  _p_twim->TASKS_STARTRX = 1;
  while (!_p_twim->EVENTS_STOPPED && !_p_twim->EVENTS_SUSPENDED && !_p_twim->EVENTS_ERROR) {}
  bool error = _p_twim->EVENTS_ERROR;
  if (error && !_p_twim->EVENTS_STOPPED) {
    _p_twim->SHORTS = 0;
    _p_twim->EVENTS_SUSPENDED = 0;
    _p_twim->TASKS_RESUME = 1;
    _p_twim->TASKS_STOP = 1;
    while (!_p_twim->EVENTS_STOPPED) {}
  }
  size_t count = error ? 0 : size_t(_p_twim->RXD.AMOUNT);
  _p_twim->SHORTS = 0;
  _p_twim->EVENTS_STOPPED = 0;
  _p_twim->EVENTS_SUSPENDED = 0;
  _p_twim->EVENTS_ERROR = 0;
  _p_twim->ERRORSRC = _p_twim->ERRORSRC;
  if (count > quantity) count = 0;
  rxBuffer._iHead = count;
  return uint8_t(count);
}

uint8_t TwoWire::endTransmission(bool stopBit)
{
  transmissionBegun = false;
  size_t count = txBuffer.available();
  _p_twim->ADDRESS = txAddress;
  _p_twim->EVENTS_STOPPED = 0;
  _p_twim->EVENTS_SUSPENDED = 0;
  _p_twim->EVENTS_ERROR = 0;
  _p_twim->EVENTS_TXSTARTED = 0;
  _p_twim->ERRORSRC = _p_twim->ERRORSRC;
  _p_twim->TXD.PTR = reinterpret_cast<uintptr_t>(txBuffer._aucBuffer);
  _p_twim->TXD.MAXCNT = count;
  _p_twim->SHORTS = count ? (stopBit ? TWIM_SHORTS_LASTTX_STOP_Msk : TWIM_SHORTS_LASTTX_SUSPEND_Msk) : 0;
  _p_twim->TASKS_RESUME = 1;
  _p_twim->TASKS_STARTTX = 1;
  if (!count) {
    // Preserve the core's address-only probe path (no LASTTX data byte).
    while (!_p_twim->EVENTS_TXSTARTED && !_p_twim->EVENTS_ERROR) {}
    if (stopBit || _p_twim->EVENTS_ERROR) _p_twim->TASKS_STOP = 1;
    else _p_twim->TASKS_SUSPEND = 1;
  }
  while (!_p_twim->EVENTS_STOPPED && !_p_twim->EVENTS_SUSPENDED && !_p_twim->EVENTS_ERROR) {}
  bool error = _p_twim->EVENTS_ERROR;
  uint32_t source = _p_twim->ERRORSRC;
  if (error && !_p_twim->EVENTS_STOPPED) {
    _p_twim->SHORTS = 0;
    _p_twim->EVENTS_SUSPENDED = 0;
    _p_twim->TASKS_RESUME = 1;
    _p_twim->TASKS_STOP = 1;
    while (!_p_twim->EVENTS_STOPPED) {}
  }
  bool complete = size_t(_p_twim->TXD.AMOUNT) == count;
  _p_twim->SHORTS = 0;
  _p_twim->EVENTS_STOPPED = 0;
  _p_twim->EVENTS_SUSPENDED = 0;
  _p_twim->EVENTS_ERROR = 0;
  _p_twim->ERRORSRC = source;
  if (error) {
    if (source & TWIM_ERRORSRC_ANACK_Msk) return 2;
    if (source & TWIM_ERRORSRC_DNACK_Msk) return 3;
    return 4;
  }
  return complete ? 0 : 4;
}
