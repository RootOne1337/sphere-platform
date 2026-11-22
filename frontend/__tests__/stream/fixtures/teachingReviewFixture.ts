import {webcrypto} from 'node:crypto';
import {TextDecoder,TextEncoder} from 'node:util';

export const encodeReview=(value:unknown)=>new TextEncoder().encode(typeof value==='string'?value:JSON.stringify(value));
export const hashReview=async(bytes:Uint8Array)=>Buffer.from(await webcrypto.subtle.digest('SHA-256',Uint8Array.from(bytes).buffer)).toString('hex');
const missing=()=>new DOMException('missing','NotFoundError');
function file(bytes:Uint8Array):File{return {size:bytes.length,arrayBuffer:async()=>Uint8Array.from(bytes).buffer,text:async()=>new TextDecoder().decode(bytes),slice:(first:number,last:number)=>file(bytes.slice(first,last))} as unknown as File;}
export function installReviewBrowser(){
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(globalThis,'TextDecoder',{configurable:true,value:TextDecoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockImplementation(()=>({drawImage:jest.fn(),clearRect:jest.fn(),setTransform:jest.fn(),beginPath:jest.fn(),arc:jest.fn(),fill:jest.fn()}) as never);
  Object.defineProperty(globalThis,'EncodedVideoChunk',{configurable:true,value:class{timestamp:number;constructor(value:{timestamp:number}){this.timestamp=value.timestamp;}}});
  Object.defineProperty(globalThis,'VideoDecoder',{configurable:true,value:class{
    static isConfigSupported=async()=>({supported:true});decodeQueueSize=0;
    constructor(private callbacks:{output:(frame:unknown)=>void}){}configure(){}close(){}async flush(){}
    decode(chunk:{timestamp:number}){this.callbacks.output({timestamp:chunk.timestamp,displayWidth:960,displayHeight:540,close:jest.fn()});}
  }});
}
/** Tiny sealed UI fixtures; these are not reconstructed gameplay or pose accuracy evidence. */
export async function makeUnifiedReviewFixture(scope:string,id:string,title='Тестовый маршрут',frameCount=200){
  const unit=new Uint8Array([0,0,0,1,0x67,0x42,0xe0,0x1f,0,0,0,1,0x65,1]),unitSha=await hashReview(unit);
  const rows=Array.from({length:frameCount},(_,index)=>({index,offset:index*unit.length,bytes:unit.length,relative_ticks_90k:index*9000,key:true,seekable:true,sha256:unitSha,worker_observed_at_ms:1000+index*100}));
  const video=new Uint8Array(frameCount*unit.length);for(let i=0;i<frameCount;i++)video.set(unit,i*unit.length);
  const index=encodeReview(rows.map(row=>JSON.stringify(row)).join('\n')),journal=encodeReview('');
  const manifest=encodeReview({schema:'sphere-browser-teaching-v2',id,started_at_ms:1793610000000,config:{title,prepare_after_recording:true},complete:true,release_confirmed:true,frames:frameCount,events:0,files:{'video.h264':{bytes:video.length},'frames.jsonl':{bytes:index.length,sha256:await hashReview(index)},'inputs.jsonl':{bytes:0,sha256:await hashReview(journal)}}});
  const manifestSha=await hashReview(manifest),files=new Map<string,Uint8Array>([['manifest.json',manifest],['frames.jsonl',index],['inputs.jsonl',journal],['video.h264',video],['COMPLETE',encodeReview({manifest_sha256:manifestSha})]]);
  const folder={entries:async function*(){for(const name of files.keys())yield [name,{kind:'file',name}];},getFileHandle:async(name:string)=>{if(!files.has(name))throw missing();return {getFile:async()=>file(files.get(name)!)};}} as unknown as FileSystemDirectoryHandle;
  const library={entries:async function*(){yield [id,{kind:'directory',name:id}];},getDirectoryHandle:async(name:string)=>{if(name!==id)throw missing();return folder;}};
  const root={getDirectoryHandle:async(name:string)=>{if(name!==`sphere-teaching-${scope}`)throw missing();return library;}} as unknown as FileSystemDirectoryHandle;
  const geometry=(cameras:number,offset=0)=>({schema:'sphere-recovered-scene-v1',source_manifest_sha256:manifestSha,camera_path_units:cameras-1,
    cameras:Array.from({length:cameras},(_,i)=>({center:[offset+i,0,0],ticks_90k:rows[i].relative_ticks_90k,camera_to_world:[[1,0,0,offset+i],[0,1,0,0],[0,0,1,0]],image:`${i.toString().padStart(8,'0')}.png`,intrinsics:{width:960,height:540,fx:600,fy:600,cx:480,cy:270}})),points:[[offset+1,2,3,210,220,230]]});
  return {root,folder,files,manifest,manifestSha,rows,geometry};
}
