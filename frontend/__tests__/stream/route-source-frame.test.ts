import {webcrypto} from 'node:crypto';
import {readRecordedRouteFrame,type RouteSource} from '@/src/features/stream/routeSource';

async function fixture(){
  const unit=new Uint8Array([0,0,0,1,0x67,0x42,0xe0,0x1f,0,0,0,1,0x65,1]);
  const sha=Buffer.from(await webcrypto.subtle.digest('SHA-256',unit)).toString('hex'),bytes=new Uint8Array([...unit,...unit]);
  const source={clip:'a'.repeat(32),scope:'b'.repeat(32),manifestSha:'c'.repeat(64),rows:[0,1].map(index=>({index,offset:index*unit.length,bytes:unit.length,key:true,seekable:true,relative_ticks_90k:index*90000,worker_observed_at_ms:index*1000,sha256:sha})),
    folder:{getFileHandle:async()=>({getFile:async()=>({slice:(a:number,b:number)=>({arrayBuffer:async()=>bytes.slice(a,b).buffer})})})}} as unknown as RouteSource;
  return source;
}
beforeEach(()=>{
  Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});
  Object.defineProperty(globalThis,'EncodedVideoChunk',{configurable:true,value:class{timestamp:number;constructor(args:{timestamp:number}){this.timestamp=args.timestamp;}}});
  Object.defineProperty(globalThis,'VideoDecoder',{configurable:true,value:class{
    static isConfigSupported=async()=>({supported:true});state='unconfigured';decodeQueueSize=0;
    constructor(private callbacks:{output:(value:unknown)=>void}){}configure(){this.state='configured';}close(){this.state='closed';}async flush(){}
    decode(chunk:{timestamp:number}){this.callbacks.output({timestamp:chunk.timestamp,displayWidth:960,displayHeight:540,close:jest.fn()});}
  }});
});
test('reference preview verifies the exact stored access unit and closes aborted work',async()=>{
  const source=await fixture(),drawImage=jest.fn(),canvas={getContext:()=>({drawImage}),width:1,height:1} as unknown as HTMLCanvasElement;
  await readRecordedRouteFrame(source,1,canvas,new AbortController().signal);expect(drawImage).toHaveBeenCalledTimes(1);expect(canvas.width).toBe(960);
  drawImage.mockClear();source.rows[1].sha256='0'.repeat(64);
  await expect(readRecordedRouteFrame(source,1,canvas,new AbortController().signal)).rejects.toThrow(/сумма/);expect(drawImage).not.toHaveBeenCalled();
  const abort=new AbortController();abort.abort();
  await expect(readRecordedRouteFrame(source,0,canvas,abort.signal)).rejects.toThrow('cancelled');
});
