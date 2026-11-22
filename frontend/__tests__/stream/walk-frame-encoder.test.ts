import {WalkFrameEncoder} from '@/src/features/stream/walkFrameEncoder';
class FakeWorker{
  static latest:FakeWorker;onmessage:((e:{data:unknown})=>void)|null=null;onerror:(()=>void)|null=null;
  postMessage=jest.fn();terminate=jest.fn();constructor(){FakeWorker.latest=this;}
}
const original={Worker:globalThis.Worker,OffscreenCanvas:globalThis.OffscreenCanvas,createImageBitmap:globalThis.createImageBitmap,VideoFrame:globalThis.VideoFrame};
let bitmap:{close:jest.Mock};
beforeEach(()=>{
  bitmap={close:jest.fn()};Object.defineProperty(globalThis,'Worker',{configurable:true,writable:true,value:FakeWorker});
  Object.defineProperty(globalThis,'OffscreenCanvas',{configurable:true,writable:true,value:function(){}});
  Object.defineProperty(globalThis,'createImageBitmap',{configurable:true,writable:true,value:jest.fn(async()=>bitmap)});
});
afterEach(()=>{for(const [key,value] of Object.entries(original))Object.defineProperty(globalThis,key,{configurable:true,writable:true,value});jest.restoreAllMocks();});
test('one bitmap is transferred to the worker and a second capture cannot queue',async()=>{
  const e=new WalkFrameEncoder(),video={} as HTMLVideoElement,canvas={} as HTMLCanvasElement;
  const first=e.encode(video,canvas);await Promise.resolve();
  expect(FakeWorker.latest.postMessage).toHaveBeenCalledWith({type:'encode',bitmap},[bitmap]);
  await expect(e.encode(video,canvas)).rejects.toThrow('walk_encoder_unavailable');
  const blob=new Blob(['jpeg'],{type:'image/jpeg'});FakeWorker.latest.onmessage!({data:{type:'encoded',blob,sha:'a'.repeat(64)}});
  await expect(first).resolves.toEqual({blob,sha:'a'.repeat(64)});e.close();expect(FakeWorker.latest.terminate).toHaveBeenCalled();
});

test('VideoFrame snapshots synchronously and moves resize/readback into the worker',async()=>{
  const close=jest.fn(),construct=jest.fn();class Frame{close=close;constructor(v:unknown){construct(v);}}
  Object.defineProperty(globalThis,'VideoFrame',{configurable:true,writable:true,value:Frame});
  const e=new WalkFrameEncoder(),video={} as HTMLVideoElement;
  const pending=e.encode(video,{} as HTMLCanvasElement);
  expect(construct).toHaveBeenCalledWith(video);expect(createImageBitmap).not.toHaveBeenCalled();
  const frame=FakeWorker.latest.postMessage.mock.calls[0][0].bitmap;
  expect(FakeWorker.latest.postMessage).toHaveBeenCalledWith({type:'encode',bitmap:frame},[frame]);
  FakeWorker.latest.onmessage!({data:{type:'encoded',blob:new Blob(['jpeg'],{type:'image/jpeg'}),sha:'a'.repeat(64),encodeMs:4,hashMs:1}});
  await pending;expect(e.snapshot()).toMatchObject({captureMode:'video_frame',encodeMs:4,hashMs:1});
  expect(close).not.toHaveBeenCalled();e.close();
});
test('closing a pending encode terminates its worker and cannot publish stale output',async()=>{
  const e=new WalkFrameEncoder(),first=e.encode({} as HTMLVideoElement,{} as HTMLCanvasElement);await Promise.resolve();
  const rejected=expect(first).rejects.toThrow('walk_encoder_retry');e.close();await rejected;
  FakeWorker.latest.onmessage!({data:{type:'encoded',blob:new Blob(['late'],{type:'image/jpeg'}),sha:'a'.repeat(64)}});
  await expect(e.encode({} as HTMLVideoElement,{} as HTMLCanvasElement)).rejects.toThrow('walk_encoder_unavailable');
});
test('failure drops the query and permits legacy encoding of the NEXT frame only',async()=>{
  const e=new WalkFrameEncoder(),first=e.encode({} as HTMLVideoElement,{} as HTMLCanvasElement);await Promise.resolve();
  const rejected=expect(first).rejects.toThrow('walk_encoder_retry');FakeWorker.latest.onerror!();await rejected;
  const draw=jest.fn(),blob=new Blob(['jpeg'],{type:'image/jpeg'});Object.defineProperty(blob,'arrayBuffer',{value:async()=>new ArrayBuffer(4)});
  const canvas={getContext:()=>({drawImage:draw}),toBlob:(done:(v:Blob)=>void)=>done(blob)} as unknown as HTMLCanvasElement;
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).fill(170).buffer}});
  await expect(e.encode({} as HTMLVideoElement,canvas)).resolves.toEqual({blob,sha:'aa'.repeat(32)});
  expect(draw).toHaveBeenCalledTimes(1);expect(createImageBitmap).toHaveBeenCalledTimes(1);e.close();
});

test('a fallback callback from a stopped encoder cannot publish into a replacement encoder',async()=>{
  Object.defineProperty(globalThis,'Worker',{configurable:true,writable:true,value:undefined});
  const callbacks:((value:Blob)=>void)[]=[];
  const canvas={getContext:()=>({drawImage:jest.fn()}),toBlob:(done:(v:Blob)=>void)=>{callbacks.push(done);}} as unknown as HTMLCanvasElement;
  const old=new WalkFrameEncoder(),pending=old.encode({} as HTMLVideoElement,canvas);
  const rejected=expect(pending).rejects.toThrow('walk_encoder_unavailable');old.close();
  const replacement=new WalkFrameEncoder(),next=replacement.encode({} as HTMLVideoElement,canvas);
  const blob=new Blob(['jpeg'],{type:'image/jpeg'});
  Object.defineProperty(blob,'arrayBuffer',{value:async()=>new ArrayBuffer(4)});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).fill(170).buffer}});
  callbacks[1](blob);await expect(next).resolves.toMatchObject({sha:'aa'.repeat(32)});
  replacement.close();
  callbacks[0](blob);await rejected;
});
