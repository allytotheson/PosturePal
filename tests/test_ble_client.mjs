import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../tools/ble-test/posturepal.js', import.meta.url), 'utf8');
const {PosturePal} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const c = new PosturePal();
const lines = [], readings = [];
c.addEventListener('line', e => lines.push(e.detail));
c.addEventListener('reading', e => readings.push(e.detail));
function chunk(text) {
  const bytes = new TextEncoder().encode(text);
  c.onValue({target:{value:new DataView(bytes.buffer)}});
}
chunk('upper_deg=1.');chunk('25 lower_deg=-2.50 buzz=1\nEVENT state=PAUSED\n');
assert.equal(lines.length,2);
assert.deepEqual(readings[0],{upper:1.25,lower:-2.5,buzz:true});
chunk('partial');c.onDisconnected();assert.equal(c.buffer,'');
const writes=[];
c.device={gatt:{connected:true,disconnect(){this.connected=false;}}};
c.rx={async writeValueWithResponse(bytes){writes.push(bytes);}};
await c.send('set 7.5 4 7.5 4 2000');
assert.ok(writes.every(bytes=>bytes.length<=20));
assert.equal(new TextDecoder().decode(Buffer.concat(writes)),'set 7.5 4 7.5 4 2000\n');
await assert.rejects(c.send('pause\nresume'));
await assert.rejects(c.send('x'.repeat(160)));
const first=c.send('pause');await assert.rejects(c.send('resume'));await first;
c.rx={async writeValueWithResponse(){throw new Error('lost connection');}};
await assert.rejects(c.send('status'));assert.equal(c.device.gatt.connected,false);assert.equal(c.busy,false);
console.log('PASS: client framing, parsing, disconnect, command chunks, validation, concurrency and write failure');
