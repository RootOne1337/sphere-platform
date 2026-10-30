/** @jest-environment node */
import {surfaceMetadata,loadSurface} from '@/src/features/stream/surfaceAsset';
import {activeSurface,terminalReconstruction,type SurfaceState} from '@/src/features/stream/reconstructionClient';
import {webcrypto} from 'node:crypto';

function payload(extra:object={}) {
  const json=new TextEncoder().encode(JSON.stringify({extensionsUsed:['KHR_materials_unlit'],...extra}));
  const length=Math.ceil(json.length/4)*4,buffer=new ArrayBuffer(28+length+4),view=new DataView(buffer);
  view.setUint32(0,0x46546c67,true);view.setUint32(4,2,true);view.setUint32(8,buffer.byteLength,true);
  view.setUint32(12,length,true);view.setUint32(16,0x4e4f534a,true);
  new Uint8Array(buffer,20,length).fill(32);new Uint8Array(buffer,20,json.length).set(json);
  view.setUint32(20+length,4,true);view.setUint32(24+length,0x004e4942,true);
  return buffer;
}
afterEach(()=>jest.restoreAllMocks());

test('a completed visual scene continues polling while the surface is being built',()=>{
  expect(activeSurface({phase:'complete',surface:{phase:'baking'}})).toBe(true);
  expect(terminalReconstruction({phase:'complete',surface:{phase:'baking'}})).toBe(false);
  expect(terminalReconstruction({phase:'complete',surface:{phase:'ready'}})).toBe(true);
  expect(terminalReconstruction({phase:'failed',surface:{phase:'failed'}})).toBe(true);
});

test('GLB loader refuses every external URI and unsupported decoder',()=>{
  expect(surfaceMetadata(payload()).extensionsUsed).toEqual(['KHR_materials_unlit']);
  expect(()=>surfaceMetadata(payload({images:[{uri:'https://invalid.example/texture'}]}))).toThrow('Внешние ресурсы');
  expect(()=>surfaceMetadata(payload({nodes:[{extensions:{KHR_draco_mesh_compression:{}}}]}))).toThrow('Внешние ресурсы');
  expect(()=>surfaceMetadata(payload().slice(0,-1))).toThrow();
});

test('a changed hash is rejected before the renderer parses any asset',async()=>{
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:webcrypto});
  const body=payload();const fetcher=jest.spyOn(globalThis,'fetch').mockResolvedValue(new Response(body,{headers:{'Content-Length':String(body.byteLength)}}));
  const state={phase:'ready',available:true,result:{bytes:body.byteLength,sha256:'0'.repeat(64)}} as SurfaceState;
  await expect(loadSurface({id:'a'.repeat(32),key:'b'.repeat(64)},state)).rejects.toThrow('Контрольная сумма');
  expect(fetcher).toHaveBeenCalledTimes(1);
});

test('a saved fragment uses its own authenticated endpoint',async()=>{
  const body=payload();const digest=Buffer.from(await webcrypto.subtle.digest('SHA-256',body)).toString('hex');
  const fetcher=jest.spyOn(globalThis,'fetch').mockResolvedValue(new Response(body,{headers:{'Content-Length':String(body.byteLength)}}));
  const state={id:'c'.repeat(32),phase:'review_required',available:true,result:{bytes:body.byteLength,sha256:digest}} as SurfaceState;
  expect(await loadSurface({id:'a'.repeat(32),key:'b'.repeat(64)},state)).toEqual(body);
  expect(fetcher.mock.calls[0][0]).toBe(`http://127.0.0.1:3342/jobs/${'a'.repeat(32)}/fragments/${'c'.repeat(32)}`);
  expect((fetcher.mock.calls[0][1]?.headers as Headers).get('X-Job-Key')).toBe('b'.repeat(64));
  await expect(loadSurface({id:'a'.repeat(32),key:'b'.repeat(64)},{...state,id:'../escape'})).rejects.toThrow('идентификатор');
  expect(fetcher).toHaveBeenCalledTimes(1);
});
