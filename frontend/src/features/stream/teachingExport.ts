/** Export a verified, completed local clip without materializing its video as a Blob. */
export type ExportProgress = { stage:'copy'|'verify'|'complete'; bytes:number; total:number; folder:string };
export type DirectoryPicker = () => Promise<FileSystemDirectoryHandle>;
type Frame = { index:number; offset:number; bytes:number; sha256:string };
const hash = async (data:ArrayBuffer) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),b=>b.toString(16).padStart(2,'0')).join('');
const cancelled = (signal?:AbortSignal) => { if(signal?.aborted)throw new DOMException('Экспорт отменён','AbortError'); };

export async function exportTeachingFolder(source:FileSystemDirectoryHandle, id:string, choose:DirectoryPicker,
  progress:(value:ExportProgress)=>void, signal?:AbortSignal, exportId=crypto.randomUUID().replaceAll('-','')) {
  if(!/^[0-9a-f]{32}$/.test(id)||!/^[0-9a-f]{32}$/.test(exportId))throw Error('Некорректный идентификатор материала.');
  cancelled(signal);
  // Keep the chooser in the button's transient activation, before filesystem/hash awaits.
  const root=await choose();cancelled(signal);
  const read=async(name:string,max:number)=>{const file=await(await source.getFileHandle(name)).getFile();if(file.size>max)throw Error('Файл превышает предел экспорта.');return file;};
  const manifestFile=await read('manifest.json',65536),manifestBytes=await manifestFile.arrayBuffer();
  const manifest=JSON.parse(new TextDecoder().decode(manifestBytes));
  if(!['sphere-browser-teaching-v1','sphere-browser-teaching-v2'].includes(manifest.schema)||manifest.id!==id
    ||manifest.complete!==true||manifest.release_confirmed!==true)throw Error('Для пакета нужна завершённая запись с подтверждённым освобождением ввода.');
  const markerFile=await read('COMPLETE',1024),markerBytes=await markerFile.arrayBuffer();
  if(JSON.parse(new TextDecoder().decode(markerBytes)).manifest_sha256!==await hash(manifestBytes))throw Error('Маркер завершения не прошёл проверку.');
  const small = new Map<string,ArrayBuffer>();
  for(const name of ['frames.jsonl','inputs.jsonl']) {
    const file=await read(name,name==='frames.jsonl'?16*1024**2:8*1024**2),data=await file.arrayBuffer();
    if(file.size!==manifest.files?.[name]?.bytes||await hash(data)!==manifest.files?.[name]?.sha256)throw Error('Контрольная сумма журнала не совпала.');
    small.set(name,data);
  }
  const frames:Frame[]=new TextDecoder().decode(small.get('frames.jsonl')!).trim().split('\n').filter(Boolean).map(line=>JSON.parse(line));
  const video=await read('video.h264',manifest.schema==='sphere-browser-teaching-v2'?2*1024**3:512*1024**2);
  if(!frames.length||frames.length!==manifest.frames||frames.length>(manifest.schema==='sphere-browser-teaching-v2'?36000:7200)||video.size!==manifest.files?.['video.h264']?.bytes
    ||frames.some((row,i)=>row.index!==i||!Number.isSafeInteger(row.offset)||row.offset<0||!Number.isSafeInteger(row.bytes)
      ||row.bytes<1||row.bytes>2*1024**2||!/^[0-9a-f]{64}$/.test(row.sha256)
      ||row.offset!==(i?frames[i-1].offset+frames[i-1].bytes:0))
    ||frames.at(-1)!.offset+frames.at(-1)!.bytes!==video.size)throw Error('Размер видео или индекс кадров не прошёл проверку.');
  cancelled(signal);
  const name=`sphere-route-${id}-${exportId}`;
  try {await root.getDirectoryHandle(name);throw Error('Папка экспорта уже существует. Её содержимое не изменено.');}
  catch(error){if(!(error instanceof Error)||error.name!=='NotFoundError')throw error;}
  const destination=await root.getDirectoryHandle(name,{create:true});
  const report=(stage:ExportProgress['stage'],bytes:number)=>progress({stage,bytes,total:video.size,folder:name});
  const writeSmall=async(filename:string,data:ArrayBuffer)=>{
    cancelled(signal);const file=await destination.getFileHandle(filename,{create:true}),writer=await file.createWritable();
    try{await writer.write(data);cancelled(signal);await writer.close();}
    catch(error){await writer.abort().catch(()=>{});throw error;}
    if(await hash(await(await file.getFile()).arrayBuffer())!==await hash(data))throw Error('Записанный файл не прошёл проверку.');
  };
  const target=await destination.getFileHandle('video.h264',{create:true}),writer=await target.createWritable();
  try {
    report('copy',0);
    for(const frame of frames){cancelled(signal);const bytes=await video.slice(frame.offset,frame.offset+frame.bytes).arrayBuffer();
      if(bytes.byteLength!==frame.bytes||await hash(bytes)!==frame.sha256)throw Error('Исходный видеокадр не прошёл проверку.');
      await writer.write(bytes);if(frame.index%60===0)report('copy',frame.offset+frame.bytes);
    }
    cancelled(signal);await writer.close();
  } catch(error){await writer.abort().catch(()=>{});throw error;}
  const copied=await target.getFile();if(copied.size!==video.size)throw Error('Сохранён размер видео, отличный от исходного.');
  report('verify',0);
  for(const frame of frames){cancelled(signal);const bytes=await copied.slice(frame.offset,frame.offset+frame.bytes).arrayBuffer();
    if(await hash(bytes)!==frame.sha256)throw Error('Сохранённый видеокадр не прошёл проверку.');
    if(frame.index%60===0)report('verify',frame.offset+frame.bytes);
  }
  for(const [filename,data] of small)await writeSmall(filename,data);
  await writeSmall('manifest.json',manifestBytes);
  // An interrupted export has no COMPLETE; never delete or overwrite another folder.
  await writeSmall('COMPLETE',markerBytes);report('complete',video.size);
  return {folder:name,videoBytes:video.size,frames:frames.length};
}
