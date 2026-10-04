// Runs the actual active TS decoder against a deliberately stalled WebCodecs double.
// This demonstrates application queue policy, not GPU/browser capacity.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = process.cwd();
const ts = require(path.join(root, 'frontend/node_modules/typescript'));
const source = fs.readFileSync(path.join(root, 'frontend/lib/h264-decoder.ts'), 'utf8');
const js = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText;
const codecs = [];
class StalledDecoder {
  constructor(callbacks) { this.callbacks=callbacks; this.state='unconfigured'; this.decodeQueueSize=0; this.lastTimestamp=null; codecs.push(this); }
  configure() { this.state='configured'; }
  decode(chunk) { if(this.state==='closed') throw Error('decoder closed'); this.decodeQueueSize++; this.lastTimestamp=chunk.timestamp; }
  close() { this.state='closed'; }
}
const context = {exports:{}, VideoDecoder:StalledDecoder, EncodedVideoChunk:class {constructor(x){Object.assign(this,x);}},
  Uint8Array, DataView, ArrayBuffer, performance:{now:()=>999999}, console:{error(){}}};
vm.runInNewContext(js,context);
function packet(nal, timestamp=12345) {
  const data=new Uint8Array(18+nal.length);data[0]=1;
  const view=new DataView(data.buffer);view.setBigInt64(2,BigInt(timestamp));view.setUint32(10,4+nal.length);
  data.set([0,0,0,1],14);data.set(nal,18);return data.buffer;
}
const waiting=new context.exports.H264Decoder(()=>{});waiting.init();
const largeNal=new Uint8Array(1024);largeNal[0]=0x65;
for(let i=0;i<2048;i++)waiting.handleBinary(packet(largeNal));
const active=new context.exports.H264Decoder(()=>{});active.init();
active.handleBinary(packet([0x67,0x42,0,0x1f]));active.handleBinary(packet([0x68,0xce]));
for(let i=0;i<1000;i++)active.handleBinary(packet([0x65,0x88]));
const codec=codecs[1];
const result={source:'frontend/lib/h264-decoder.ts',scope:'Actual TS decoder with a stalled VideoDecoder double; not a browser benchmark',
  pending_without_sps_pps:waiting.pendingFrames.length,
  pending_payload_bytes:waiting.pendingFrames.reduce((n,b)=>n+b.byteLength,0),
  submitted_to_stalled_decoder:codec.decodeQueueSize,source_timestamp_us:12345000,submitted_timestamp_us:codec.lastTimestamp};
codec.state='closed';codec.callbacks.error(Error('simulated codec failure'));
try {active.handleBinary(packet([0x65,0x88]));result.decode_error_propagated=false;} catch {result.decode_error_propagated=true;}
waiting.destroy();active.destroy();
console.log(JSON.stringify(result,null,2));
