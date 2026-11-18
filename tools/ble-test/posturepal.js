// Copy this module into the website. No package dependencies or server API.
export const UUID = Object.freeze({
  service: '6e400001-b5a3-f393-e0a9-e50e24dcca9e',
  rx: '6e400002-b5a3-f393-e0a9-e50e24dcca9e',
  tx: '6e400003-b5a3-f393-e0a9-e50e24dcca9e',
});
export class PosturePal extends EventTarget {
  device = null; rx = null; tx = null; buffer = ''; busy = false;
  emit(type, detail) { this.dispatchEvent(new CustomEvent(type, {detail})); }
  onDisconnected = () => {
    this.tx?.removeEventListener('characteristicvaluechanged', this.onValue);
    this.rx = this.tx = null; this.buffer = '';
    this.emit('connection', false);
  };
  onValue = event => {
    this.buffer += new TextDecoder().decode(event.target.value);
    let end;
    while ((end = this.buffer.indexOf('\n')) !== -1) {
      const line = this.buffer.slice(0, end).replace(/\r$/, '');
      this.buffer = this.buffer.slice(end + 1);
      this.emit('line', line);
      const reading = /^upper_deg=(-?\d+(?:\.\d+)?) lower_deg=(-?\d+(?:\.\d+)?) buzz=([01])$/.exec(line);
      if (reading) this.emit('reading', {upper: +reading[1], lower: +reading[2], buzz: reading[3] === '1'});
    }
    if (this.buffer.length > 4096) { this.buffer = ''; this.emit('error', 'Oversized response discarded; request status.'); }
  };
  async connect() {
    if (!navigator.bluetooth) throw new Error('Web Bluetooth unavailable. Use Chrome or Edge on a supported desktop, or Chrome on Android.');
    if (this.device?.gatt.connected) throw new Error('Already connected.');
    this.device?.removeEventListener('gattserverdisconnected', this.onDisconnected);
    this.device = await navigator.bluetooth.requestDevice({filters: [{services: [UUID.service]}]});
    this.device.addEventListener('gattserverdisconnected', this.onDisconnected);
    try {
      const server = await this.device.gatt.connect();
      const service = await server.getPrimaryService(UUID.service);
      this.rx = await service.getCharacteristic(UUID.rx);
      this.tx = await service.getCharacteristic(UUID.tx);
      this.buffer = '';
      this.tx.addEventListener('characteristicvaluechanged', this.onValue);
      await this.tx.startNotifications();
      this.emit('connection', true);
      await this.send('status');
    } catch (error) { this.disconnect(); this.onDisconnected(); throw error; }
  }
  disconnect() { this.device?.gatt.disconnect(); }
  async send(command) {
    if (!this.rx || !this.device?.gatt.connected) throw new Error('Connect first.');
    if (this.busy) throw new Error('Wait for the current command to finish.');
    if (!/^[\x20-\x7e]{1,159}$/.test(command)) throw new Error('Use 1–159 printable ASCII characters, without newlines.');
    this.busy = true;
    const rx = this.rx;
    try {
      const bytes = new TextEncoder().encode(command + '\n');
      for (let i = 0; i < bytes.length; i += 20) await rx.writeValueWithResponse(bytes.slice(i, i + 20));
      // Firmware consumes one command per loop. Do not flood its single mailbox.
      await new Promise(resolve => setTimeout(resolve, 100));
    } catch (error) {
      // Discard any partially transferred command on the peripheral.
      this.disconnect(); throw error;
    } finally { this.busy = false; }
  }
}
