'use client';
import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { exportTeachingFolder, type ExportProgress } from './teachingExport';

type Row = { index: number; offset: number; bytes: number; relative_ticks_90k: number; key: boolean; seekable?: boolean; sha256: string; worker_observed_at_ms: number };
type Clip = { id: string; title: string; complete: boolean; frames: number; failure: string | null };
const names = ['video.h264','frames.jsonl','inputs.jsonl','manifest.json','COMPLETE'];
const digest = async (buffer: ArrayBuffer) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer)), v => v.toString(16).padStart(2,'0')).join('');
export function h264Codec(data: Uint8Array): string | null {
  for(let i=0;i+7<data.length;i++) {
    if(data[i] || data[i+1]) continue;
    const at=data[i+2]===1?i+3:data[i+2]===0&&data[i+3]===1?i+4:-1;
    if(at>=0&&(data[at]&31)===7&&at+3<data.length) return 'avc1.'+Array.from(data.slice(at+1,at+4),v=>v.toString(16).padStart(2,'0')).join('');
  }
  return null;
}
export function TeachingReview({ selected, refresh, onSelect, storageScope, onBusyChange }: { selected: string | null; refresh: number; onSelect: (id: string | null) => void; storageScope: string | null; onBusyChange?: (busy:boolean)=>void }) {
  const [clips,setClips]=useState<Clip[]>([]),[error,setError]=useState<string|null>(null);
  const [rows,setRows]=useState<Row[]>([]),[inputs,setInputs]=useState<Record<string,unknown>[]>([]),[position,setPosition]=useState(0);
  const [localRefresh,setLocalRefresh]=useState(0),[decoding,setDecoding]=useState(false);
  const [exporting,setExporting]=useState(false),[exportProgress,setExportProgress]=useState<ExportProgress|null>(null),[exportNotice,setExportNotice]=useState<string|null>(null);
  const exportAbort=useRef<AbortController|null>(null);
  const canvas=useRef<HTMLCanvasElement>(null), directory=useRef<FileSystemDirectoryHandle|null>(null);
  const generation=useRef(0);
  useEffect(()=>()=>{exportAbort.current?.abort();onBusyChange?.(false);},[onBusyChange]);
  useEffect(()=>{
    let retired=false;
    void(async()=>{
      if(!navigator.storage?.getDirectory || !storageScope || !/^[0-9a-f]{32}$/.test(storageScope)) return;
      const root=await navigator.storage.getDirectory();
      let library:FileSystemDirectoryHandle;
      try {library=await root.getDirectoryHandle('sphere-teaching-'+storageScope);} catch {return;}
      const found:Clip[]=[];let examined=0;
      const iterable=library as FileSystemDirectoryHandle & { values(): AsyncIterableIterator<FileSystemHandle> };
      for await(const entry of iterable.values()) {
        if(++examined>100) break;
        if(entry.kind!=='directory'||!/^[0-9a-f]{32}$/.test(entry.name)) continue;
        const folder=await library.getDirectoryHandle(entry.name);
        try {
          const file=await(await folder.getFileHandle('manifest.json')).getFile();if(file.size>65536)continue;
          const manifest=JSON.parse(await file.text());
          if(!['sphere-browser-teaching-v1','sphere-browser-teaching-v2'].includes(manifest.schema)||manifest.id!==entry.name)continue;
          found.push({id:entry.name,title:String(manifest.config?.title??'Маршрут').slice(0,128),complete:manifest.complete===true,
            frames:Number(manifest.frames),failure:manifest.failure});
        } catch { found.push({id:entry.name,title:'Прерванная запись',complete:false,frames:0,failure:'manifest_missing'}); }
      }
      if(!retired)setClips(found.slice(-20).reverse());
    })().catch(()=>{if(!retired)setError('Не удалось прочитать локальную библиотеку браузера.');});
    return()=>{retired=true;};
  },[refresh,localRefresh,storageScope]);
  useEffect(()=>{
    const current=++generation.current; setRows([]);setInputs([]);setPosition(0);directory.current=null;setError(null);
    if(!selected||!/^[0-9a-f]{32}$/.test(selected)||!storageScope||!/^[0-9a-f]{32}$/.test(storageScope))return;
    void(async()=>{
      const root=await navigator.storage.getDirectory(),library=await root.getDirectoryHandle('sphere-teaching-'+storageScope);
      const folder=await library.getDirectoryHandle(selected);
      const read=async(name:string,max:number)=>{const file=await(await folder.getFileHandle(name)).getFile();if(file.size>max)throw Error('Размер индекса превышает предел.');return file;};
      const manifestFile=await read('manifest.json',65536),manifest=JSON.parse(await manifestFile.text());
      if(!['sphere-browser-teaching-v1','sphere-browser-teaching-v2'].includes(manifest.schema)||manifest.id!==selected)throw Error('Формат материала не поддерживается.');
      const indexFile=await read('frames.jsonl',16*1024*1024),inputFile=await read('inputs.jsonl',8*1024*1024);
      if(await digest(await indexFile.arrayBuffer())!==manifest.files?.['frames.jsonl']?.sha256
        ||await digest(await inputFile.arrayBuffer())!==manifest.files?.['inputs.jsonl']?.sha256)throw Error('Контрольная сумма журнала не совпала.');
      if(manifest.complete===true){const marker=JSON.parse(await(await read('COMPLETE',1024)).text());
        if(marker.manifest_sha256!==await digest(await manifestFile.arrayBuffer()))throw Error('Маркер завершения не прошёл проверку.');}
      const entries:Row[]=(await indexFile.text()).trim().split('\n').filter(Boolean).map(line=>JSON.parse(line));
      if(entries.length>(manifest.schema==='sphere-browser-teaching-v2'?36000:7200)||entries.some((r,i)=>r.index!==i||!Number.isInteger(r.offset)||r.offset<0
        ||!Number.isInteger(r.bytes)||r.bytes<1||r.bytes>2*1024*1024||!Number.isFinite(r.relative_ticks_90k)
        ||r.relative_ticks_90k<0||typeof r.key!=='boolean'||!/^[0-9a-f]{64}$/.test(r.sha256)
        || i>0&&(r.offset!==entries[i-1].offset+entries[i-1].bytes||r.relative_ticks_90k<=entries[i-1].relative_ticks_90k)))throw Error('Индекс видео некорректен.');
      const video=await read('video.h264',manifest.schema==='sphere-browser-teaching-v2'?2*1024*1024*1024:512*1024*1024);
      if(video.size!==manifest.files?.['video.h264']?.bytes||entries.length
        && entries.at(-1)!.offset+entries.at(-1)!.bytes!==video.size)throw Error('Размер видео не соответствует индексу.');
      const journal=(await inputFile.text()).trim().split('\n').filter(Boolean).map(line=>JSON.parse(line));
      if(journal.length>40000)throw Error('Журнал действий превышает предел.');
      if(current===generation.current){directory.current=folder;setRows(entries);setInputs(journal);}
    })().catch(e=>{if(current===generation.current)setError(e instanceof Error?e.message:'Материал не прочитан.');});
    return()=>{generation.current++;};
  },[selected,refresh,storageScope]);
  useEffect(()=>{
    if(!directory.current||!rows.length||!canvas.current)return;
    let retired=false;let decoder:VideoDecoder|undefined;setDecoding(true);setError(null);
    void(async()=>{
      if(typeof VideoDecoder==='undefined')throw Error('В браузере нет WebCodecs для просмотра исходного H264. Экспортируйте видео.');
      const file=await(await directory.current!.getFileHandle('video.h264')).getFile();
      let first=position;while(first>0&&!(rows[first].seekable??rows[first].key))first--;
      if(!rows[first].key)throw Error('Нет ключевого кадра для просмотра.');
      const bytes=await file.slice(rows[first].offset,rows[first].offset+rows[first].bytes).arrayBuffer();
      const codec=h264Codec(new Uint8Array(bytes));if(!codec)throw Error('Не найден SPS H264.');
      const support=await VideoDecoder.isConfigSupported({codec});if(!support.supported)throw Error('Профиль H264 не поддерживается декодером.');
      let decodeError=false;
      decoder=new VideoDecoder({output:frame=>{
        try{if(!retired&&frame.timestamp===Math.round(rows[position].relative_ticks_90k*1000000/90000)){
          const target=canvas.current;if(target){target.width=frame.displayWidth;target.height=frame.displayHeight;target.getContext('2d')?.drawImage(frame,0,0);}
        }}finally{frame.close();}
      },error:()=>{decodeError=true;}});
      decoder.configure({codec});
      for(let i=first;i<=position&&!retired;i++){
        const row=rows[i],data=i===first?bytes:await file.slice(row.offset,row.offset+row.bytes).arrayBuffer();
        if(data.byteLength!==row.bytes||await digest(data)!==row.sha256)throw Error('Контрольная сумма видеокадра не совпала.');
        decoder.decode(new EncodedVideoChunk({type:row.key?'key':'delta',timestamp:Math.round(row.relative_ticks_90k*1000000/90000),data}));
        if(decoder.decodeQueueSize>8)await new Promise<void>((resolve,reject)=>{
          const timeout=setTimeout(()=>reject(Error('Декодер не подтвердил продвижение.')),2000);
          decoder!.addEventListener('dequeue',()=>{clearTimeout(timeout);resolve();},{once:true});
        });
      }
      if(!retired)await decoder.flush();if(decodeError)throw Error('Декодер отклонил материал.');
    })().catch(e=>{if(!retired)setError(e instanceof Error?e.message:'Просмотр не готов.');}).finally(()=>{if(!retired)setDecoding(false);try{decoder?.close();}catch{}});
    return()=>{retired=true;try{decoder?.close();}catch{}};
  },[rows,position]);
  const download=async(name:string)=>{
    try{const file=await(await directory.current!.getFileHandle(name)).getFile();const url=URL.createObjectURL(file),a=document.createElement('a');a.href=url;a.download=`${selected}-${name}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
    catch{setError('Файл недоступен. Для неполного материала маркер COMPLETE отсутствует.');}
  };
  const exportFolder=async()=>{
    if(exportAbort.current||!directory.current||!selected)return;
    const picker=(window as Window & {showDirectoryPicker?:(options:{id:string;mode:'readwrite'})=>Promise<FileSystemDirectoryHandle>}).showDirectoryPicker;
    if(!picker){setExportNotice('Браузер не поддерживает выбор папки. Скачайте отдельные файлы ниже; для экспорта папкой используйте Chrome или Edge.');return;}
    const request=new AbortController();exportAbort.current=request;setExporting(true);onBusyChange?.(true);setExportProgress(null);setExportNotice(null);
    try{
      const result=await exportTeachingFolder(directory.current,selected,()=>picker.call(window,{id:'sphere-route-export',mode:'readwrite'}),setExportProgress,request.signal);
      setExportNotice(`Пакет сохранён и проверен: ${result.folder}. Исходник остался в браузере.`);
    }catch(error){setExportNotice(error instanceof Error&&error.name==='AbortError'?'Экспорт отменён. Исходник остался в браузере.':`Экспорт не подтверждён: ${error instanceof Error?error.message:'ошибка доступа к папке'}. Исходник остался в браузере; папка без COMPLETE неполная.`);}
    finally{exportAbort.current=null;setExporting(false);onBusyChange?.(false);}
  };
  const nearby=rows[position]?inputs.filter(i=>i.stage!=='submitted'&&typeof i.at_ms==='number'
    &&Math.abs(i.at_ms-rows[position].worker_observed_at_ms)<500).slice(0,12):[];
  return <section aria-label="Просмотр записанных маршрутов" className="space-y-4 rounded-2xl border border-border bg-card p-4 sm:p-5">
    <div><h3 className="text-lg font-semibold">Записанные проходы</h3><p className="mt-1 text-sm text-muted-foreground">Локальная библиотека этого браузера. Кадры проверяются по SHA-256; время получения кадра не равно времени его захвата Android.</p></div>
    {!clips.length?<p className="text-sm text-muted-foreground">Завершённых материалов пока нет.</p>:<div className="flex flex-wrap gap-2">{clips.map(c=><Button key={c.id} disabled={exporting} variant={selected===c.id?'default':'outline'} onClick={()=>onSelect(c.id)}>{c.title} · {c.complete?'Готов':'Неполный'} · {c.frames} кадров</Button>)}</div>}
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {selected&&<div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]"><div className="space-y-3"><canvas ref={canvas} className="aspect-video w-full rounded-xl bg-black object-contain" aria-label="Записанный видеокадр" />
      <label className="block text-sm">Кадр {position+1} / {rows.length} · {((rows[position]?.relative_ticks_90k??0)/90000).toFixed(3)} с {decoding?'· декодирование':''}<input aria-label="Время записанного прохода" type="range" min={0} max={Math.max(0,rows.length-1)} value={position} disabled={exporting} className="mt-2 w-full" onChange={e=>setPosition(Number(e.target.value))} /></label></div>
      <div className="space-y-3"><h4 className="text-sm font-medium">Подтверждения рядом с кадром</h4><div className="max-h-56 space-y-1 overflow-auto font-mono text-xs">{nearby.length?nearby.map((i,n)=><p key={n}>#{String(i.sequence)} · палец {String(i.pointer_id)} · {String(i.outcome)} · {String(i.device_uptime_ms??'')} мс</p>):<p className="text-muted-foreground">В этом интервале нет подтверждений.</p>}</div>
        <Button className="w-full" disabled={exporting||!directory.current||!clips.find(c=>c.id===selected)?.complete} onClick={()=>{void exportFolder();}}>Сохранить пакет в папку</Button>
        {exporting&&<Button variant="outline" onClick={()=>exportAbort.current?.abort()}>Отменить экспорт</Button>}
        {exporting&&exportProgress&&<p role="status" className="text-xs text-muted-foreground">{exportProgress.stage==='verify'?'Проверка сохранённого видео':'Копирование видео'} · {(exportProgress.bytes/1048576).toFixed(1)} / {(exportProgress.total/1048576).toFixed(1)} МБ</p>}
        {exportNotice&&<p role="status" className="break-all text-xs text-muted-foreground">{exportNotice}</p>}
        <details><summary className="cursor-pointer text-sm">Отдельные файлы и диагностика</summary><div className="mt-2 flex flex-wrap gap-2">{names.map(name=><Button disabled={exporting} size="sm" variant="outline" key={name} onClick={()=>{void download(name);}}>{name}</Button>)}</div></details>
        <Button disabled={exporting} variant="ghost" className="text-destructive" onClick={()=>{void(async()=>{if(!storageScope||!/^[0-9a-f]{32}$/.test(storageScope))throw Error();const root=await navigator.storage.getDirectory();const library=await root.getDirectoryHandle('sphere-teaching-'+storageScope);await library.removeEntry(selected,{recursive:true});onSelect(null);setLocalRefresh(v=>v+1);})().catch(()=>setError('Удаление не подтверждено.'));}}>Удалить выбранный локальный материал</Button>
      </div></div>}
  </section>;
}
