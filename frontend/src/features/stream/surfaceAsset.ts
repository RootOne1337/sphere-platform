import {reconstructionRequest,type ReconstructionJob,type SurfaceState} from './reconstructionClient';

/** The local API validates the full mesh. This boundary also forbids loader network requests. */
export function surfaceMetadata(buffer:ArrayBuffer) {
  if(buffer.byteLength<28||buffer.byteLength>64*1048576)throw Error('Размер 3D-модели превышает лимит.');
  const data=new DataView(buffer);
  if(data.getUint32(0,true)!==0x46546c67||data.getUint32(4,true)!==2||data.getUint32(8,true)!==buffer.byteLength||data.getUint32(16,true)!==0x4e4f534a)throw Error('Повреждён формат 3D-модели.');
  const length=data.getUint32(12,true);
  if(length<2||length>2*1048576||length%4||28+length>buffer.byteLength)throw Error('Повреждено описание 3D-модели.');
  if(data.getUint32(24+length,true)!==0x004e4942||28+length+data.getUint32(20+length,true)!==buffer.byteLength)throw Error('Повреждён буфер 3D-модели.');
  const metadata=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,20,length)));
  const inspect=(value:unknown)=>{
    if(!value||typeof value!=='object')return;
    if(Array.isArray(value)){value.forEach(inspect);return;}
    for(const [key,item] of Object.entries(value)){
      if(key==='uri'||key==='extensions'&&JSON.stringify(item)!=='{"KHR_materials_unlit":{}}')throw Error('Внешние ресурсы 3D-модели запрещены.');
      inspect(item);
    }
  };
  inspect(metadata);
  if(JSON.stringify(metadata.extensionsUsed)!=='["KHR_materials_unlit"]'||metadata.extensionsRequired?.length)throw Error('Расширение модели не поддерживается.');
  return metadata;
}

export async function loadSurface(job:ReconstructionJob,state:SurfaceState,signal?:AbortSignal) {
  const receipt=state.result;
  if(!state.available||!receipt||!Number.isSafeInteger(receipt.bytes)||receipt.bytes>64*1048576||!/^[0-9a-f]{64}$/.test(receipt.sha256))throw Error('3D-модель ещё не подтверждена.');
  const response=await reconstructionRequest(`/jobs/${job.id}/surface`,job,{signal});
  if(Number(response.headers.get('Content-Length'))!==receipt.bytes)throw Error('Размер результата изменился.');
  const buffer=await response.arrayBuffer();
  if(buffer.byteLength!==receipt.bytes)throw Error('3D-модель получена не полностью.');
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer)),b=>b.toString(16).padStart(2,'0')).join('');
  if(digest!==receipt.sha256)throw Error('Контрольная сумма 3D-модели изменилась.');
  surfaceMetadata(buffer);
  return buffer;
}
