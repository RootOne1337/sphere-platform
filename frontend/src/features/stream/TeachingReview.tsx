'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { exportTeachingFolder, type ExportProgress } from './teachingExport';
import { TeachingReconstruction } from './TeachingReconstruction';
import type {ReconstructionJob} from './reconstructionClient';
import {teachingCaptureMetrics} from './teachingCaptureMetrics';
import { readTeachingLabel, renameTeachingLabel, seekTeachingSecond, teachingDate } from './teachingMetadata';
import {exactRecordedFrame,readImportedRouteGeometry,type ImportedRouteGeometry} from './routeMapProjection';
import RouteGeometryMap from './RouteGeometryMap';
import {reconstructionRequest} from './reconstructionClient';

type Row = { index: number; offset: number; bytes: number; relative_ticks_90k: number; key: boolean; seekable?: boolean; sha256: string; worker_observed_at_ms: number };
type Clip = { id: string; title: string; createdAt: number; complete: boolean; frames: number; failure: string | null; hudHidden:boolean };
export type TeachingClipChoice = Pick<Clip,'id'|'title'|'complete'|'frames'>;
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
export function TeachingReview({ selected, refresh, onSelect, storageScope, onBusyChange,onRouteChange,onClipsChange,visible=true }: { selected: string | null; refresh: number; onSelect: (id: string | null) => void; storageScope: string | null; onBusyChange?: (busy:boolean)=>void;onRouteChange?:(job:ReconstructionJob|null,clip:string|null,scope:string|null)=>void;onClipsChange?:(clips:TeachingClipChoice[])=>void;visible?:boolean }) {
  useEffect(()=>{onRouteChange?.(null,selected,storageScope);},[selected,storageScope,onRouteChange]);
  const [linkedJob,setLinkedJob]=useState<ReconstructionJob|null>(null);
  const routeChanged=useCallback((job:ReconstructionJob|null)=>{setLinkedJob(job);onRouteChange?.(job,selected,storageScope);},[onRouteChange,selected,storageScope]);
  const [clips,setClips]=useState<Clip[]>([]),[error,setError]=useState<string|null>(null);
  const [libraryTruncated,setLibraryTruncated]=useState(false);
  useEffect(()=>{onClipsChange?.(clips);},[clips,onClipsChange]);
  const [rows,setRows]=useState<Row[]>([]),[inputs,setInputs]=useState<Record<string,unknown>[]>([]),[position,setPosition]=useState(0);
  const [sourceManifestSha,setSourceManifestSha]=useState<string|null>(null),[previewCanvas,setPreviewCanvas]=useState<HTMLCanvasElement|null>(null);
  const [importedGeometry,setImportedGeometry]=useState<ImportedRouteGeometry|null>(null),[importError,setImportError]=useState<string|null>(null),[importedCanvas,setImportedCanvas]=useState<HTMLCanvasElement|null>(null);
  const [alternatives,setAlternatives]=useState<{id:string;cameras:number;points:number}[]>([]),[alternativeId,setAlternativeId]=useState<string|null>(null),[alternativeStatus,setAlternativeStatus]=useState('');
  const [localRefresh,setLocalRefresh]=useState(0),[decoding,setDecoding]=useState(false);
  const [search,setSearch]=useState(''),[deleteConfirm,setDeleteConfirm]=useState(false),[deleting,setDeleting]=useState(false);
  const deleteInFlight=useRef(false);
  const [exporting,setExporting]=useState(false),[exportProgress,setExportProgress]=useState<ExportProgress|null>(null),[exportNotice,setExportNotice]=useState<string|null>(null);
  const [processing,setProcessing]=useState(false);
  useEffect(()=>{if(!visible)setPlaying(false);},[visible]);
  const [label,setLabel]=useState(''),[renaming,setRenaming]=useState(false);
  const [playing,setPlaying]=useState(false),[zoom,setZoom]=useState(1);
  const view=useRef<HTMLDivElement>(null);
  const exportAbort=useRef<AbortController|null>(null);
  const canvas=useRef<HTMLCanvasElement>(null), directory=useRef<FileSystemDirectoryHandle|null>(null);
  const generation=useRef(0),importGeneration=useRef(0);
  useEffect(()=>()=>{exportAbort.current?.abort();onBusyChange?.(false);},[onBusyChange]);
  useEffect(()=>{onBusyChange?.(exporting||processing||renaming||playing||deleting);},[exporting,processing,renaming,playing,deleting,onBusyChange]);
  useEffect(()=>{setPlaying(false);setZoom(1);setDeleteConfirm(false);},[selected]);
  useEffect(()=>{
    if(!playing||decoding)return;
    if(position>=rows.length-1){setPlaying(false);return;}
    const timer=setTimeout(()=>setPosition(at=>seekTeachingSecond(rows,at,.2)),200);
    return()=>clearTimeout(timer);
  },[playing,decoding,position,rows]);
  useEffect(()=>{
    let retired=false;
    void(async()=>{
      if(!navigator.storage?.getDirectory || !storageScope || !/^[0-9a-f]{32}$/.test(storageScope)) return;
      const root=await navigator.storage.getDirectory();
      let library:FileSystemDirectoryHandle;
      try {library=await root.getDirectoryHandle('sphere-teaching-'+storageScope);} catch {return;}
      const found:Clip[]=[];let examined=0;
      const iterable=library as FileSystemDirectoryHandle & { values(): AsyncIterableIterator<FileSystemHandle> };
      let truncated=false;
      for await(const entry of iterable.values()) {
        if(++examined>100) {truncated=true;break;}
        if(entry.kind!=='directory'||!/^[0-9a-f]{32}$/.test(entry.name)) continue;
        const folder=await library.getDirectoryHandle(entry.name);
        try {
          const file=await(await folder.getFileHandle('manifest.json')).getFile();if(file.size>65536)continue;
          const bytes=await file.arrayBuffer(),manifest=JSON.parse(new TextDecoder().decode(bytes));
          if(!['sphere-browser-teaching-v1','sphere-browser-teaching-v2'].includes(manifest.schema)||manifest.id!==entry.name)continue;
          found.push({id:entry.name,title:await readTeachingLabel(folder,entry.name,bytes)??String(manifest.config?.title??'Маршрут').slice(0,128),createdAt:Number(manifest.started_at_ms)||0,complete:manifest.complete===true,
            frames:Number(manifest.frames),failure:manifest.failure,hudHidden:manifest.config?.hud_hidden_declared===true});
        } catch { found.push({id:entry.name,title:'Прерванная запись',createdAt:0,complete:false,frames:0,failure:'manifest_missing',hudHidden:false}); }
      }
      if(!retired){setClips(found.sort((a,b)=>b.createdAt-a.createdAt||a.id.localeCompare(b.id)));setLibraryTruncated(truncated);}
    })().catch(()=>{if(!retired)setError('Не удалось прочитать локальную библиотеку браузера.');});
    return()=>{retired=true;};
  },[refresh,localRefresh,storageScope]);
  useEffect(()=>{setLabel(clips.find(c=>c.id===selected)?.title??'');},[clips,selected]);
  useEffect(()=>{
    const current=++generation.current;importGeneration.current++;setRows([]);setInputs([]);setPosition(0);setSourceManifestSha(null);setImportedGeometry(null);setImportError(null);setLinkedJob(null);setAlternatives([]);setAlternativeId(null);setAlternativeStatus('');directory.current=null;setError(null);
    if(!selected||!/^[0-9a-f]{32}$/.test(selected)||!storageScope||!/^[0-9a-f]{32}$/.test(storageScope))return;
    void(async()=>{
      const root=await navigator.storage.getDirectory(),library=await root.getDirectoryHandle('sphere-teaching-'+storageScope);
      const folder=await library.getDirectoryHandle(selected);
      const read=async(name:string,max:number)=>{const file=await(await folder.getFileHandle(name)).getFile();if(file.size>max)throw Error('Размер индекса превышает предел.');return file;};
      const manifestFile=await read('manifest.json',65536),manifestBytes=await manifestFile.arrayBuffer(),manifestSha=await digest(manifestBytes),manifest=JSON.parse(new TextDecoder().decode(manifestBytes));
      if(!['sphere-browser-teaching-v1','sphere-browser-teaching-v2'].includes(manifest.schema)||manifest.id!==selected)throw Error('Формат материала не поддерживается.');
      const indexFile=await read('frames.jsonl',16*1024*1024),inputFile=await read('inputs.jsonl',8*1024*1024);
      if(await digest(await indexFile.arrayBuffer())!==manifest.files?.['frames.jsonl']?.sha256
        ||await digest(await inputFile.arrayBuffer())!==manifest.files?.['inputs.jsonl']?.sha256)throw Error('Контрольная сумма журнала не совпала.');
      if(manifest.complete===true){const marker=JSON.parse(await(await read('COMPLETE',1024)).text());
        if(marker.manifest_sha256!==manifestSha)throw Error('Маркер завершения не прошёл проверку.');}
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
      if(current===generation.current){directory.current=folder;setRows(entries);setInputs(journal);setSourceManifestSha(manifestSha);}
    })().catch(e=>{if(current===generation.current)setError(e instanceof Error?e.message:'Материал не прочитан.');});
    return()=>{generation.current++;};
  },[selected,refresh,storageScope]);
  useEffect(()=>{
    if(!visible||!directory.current||!rows.length||!canvas.current){setDecoding(false);return;}
    // The label and the image must refer to the same frame even while a new
    // keyframe chain is decoding or a previous decode fails.
    for(const target of [canvas.current,previewCanvas,importedCanvas])if(target)target.getContext('2d')?.clearRect(0,0,target.width,target.height);
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
          for(const target of [canvas.current,previewCanvas,importedCanvas])if(target){target.width=frame.displayWidth;target.height=frame.displayHeight;target.getContext('2d')?.drawImage(frame,0,0);}
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
    })().catch(e=>{if(!retired){setPlaying(false);setError(e instanceof Error?e.message:'Просмотр не готов.');}}).finally(()=>{if(!retired)setDecoding(false);try{decoder?.close();}catch{}});
    return()=>{retired=true;try{decoder?.close();}catch{}};
  },[rows,position,visible,previewCanvas,importedCanvas]);
  const download=async(name:string)=>{
    try{const file=await(await directory.current!.getFileHandle(name)).getFile();const url=URL.createObjectURL(file),a=document.createElement('a');a.href=url;a.download=`${selected}-${name}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
    catch{setError('Файл недоступен. Для неполного материала маркер COMPLETE отсутствует.');}
  };
  const exportFolder=async()=>{
    if(exportAbort.current||deleteInFlight.current||!directory.current||!selected)return;
    setPlaying(false);
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
  const capture=useMemo(()=>teachingCaptureMetrics(rows),[rows]);
  const validTicks=useMemo(()=>new Set(rows.map(row=>row.relative_ticks_90k)),[rows]);
  useEffect(()=>{
    if(!visible||!linkedJob||!sourceManifestSha||!rows.length)return;
    const request=new AbortController();let retired=false;setAlternativeStatus('Проверяем сохранённые схемы…');setAlternatives([]);setAlternativeId(null);
    void(async()=>{const data=await(await reconstructionRequest(`/jobs/${linkedJob.id}/geometry-alternatives`,linkedJob,{signal:request.signal})).json();
      if(!Array.isArray(data.alternatives)||data.alternatives.length>16)throw Error('alternative_list_invalid');
      const items=data.alternatives.filter((v:unknown):v is {id:string;cameras:number;points:number}=>!!v&&typeof v==='object'&&typeof (v as {id?:unknown}).id==='string'&&/^[a-z0-9][a-z0-9-]{0,47}$/.test((v as {id:string}).id)&&Number.isInteger((v as {cameras?:unknown}).cameras)&&Number.isInteger((v as {points?:unknown}).points));
      if(!retired){setAlternatives(items);setAlternativeId(items[0]?.id??null);setAlternativeStatus(items.length?'Загружаем сохранённую схему…':'Дополнительных схем для этой реконструкции нет.');}
    })().catch(()=>{if(!retired)setAlternativeStatus('Не удалось проверить дополнительные схемы. Обычная реконструкция остаётся доступной.');});
    return()=>{retired=true;request.abort();};
  },[visible,linkedJob,sourceManifestSha,rows]);
  useEffect(()=>{
    if(!visible||!linkedJob||!alternativeId||!sourceManifestSha)return;
    const controller=new AbortController(),current=generation.current,request=++importGeneration.current;setImportedGeometry(null);setImportError(null);
    void(async()=>{const data=await(await reconstructionRequest(`/jobs/${linkedJob.id}/geometry-alternatives/${alternativeId}`,linkedJob,{signal:controller.signal})).json();
      const geometry=readImportedRouteGeometry(data,sourceManifestSha,validTicks);
      if(current===generation.current&&request===importGeneration.current&&!controller.signal.aborted){setImportedGeometry(geometry);setAlternativeStatus('Сохранённая экспериментальная схема связана с исходной записью.');}
    })().catch(()=>{if(current===generation.current&&request===importGeneration.current&&!controller.signal.aborted)setAlternativeStatus('Схема не прошла проверку привязки или недоступна.');});
    return()=>controller.abort();
  },[visible,linkedJob,alternativeId,sourceManifestSha,validTicks]);
  const seekCamera=(ticks:number)=>{const index=exactRecordedFrame(rows,ticks);if(index!==null){setPlaying(false);setPosition(index);}};
  const importGeometry=async(file:File)=>{
    const current=generation.current,request=++importGeneration.current;setAlternativeId(null);setImportError(null);setImportedGeometry(null);
    try{if(file.size<1||file.size>16*1024*1024)throw Error('Файл геометрии пуст или превышает 16 МБ.');
      const geometry=readImportedRouteGeometry(JSON.parse(await file.text()),sourceManifestSha,validTicks);
      if(current===generation.current&&request===importGeneration.current){setImportedGeometry(geometry);setAlternativeStatus('Схема из файла связана с выбранной записью.');}
    }catch(e){if(current===generation.current&&request===importGeneration.current)setImportError(e instanceof Error?e.message:'Не удалось прочитать геометрию.');}
  };
  const sourceViewer=(setCanvas:(canvas:HTMLCanvasElement|null)=>void,imported=false)=><div className="space-y-2 rounded-xl border border-border bg-background/60 p-3"><p className="text-xs font-medium">Исходный кадр · {((rows[position]?.relative_ticks_90k??0)/90000).toFixed(3)} с {decoding?'· декодирование':''}</p><canvas ref={setCanvas} aria-label={imported?'Исходный кадр импортированной схемы':'Исходный кадр выбранной точки'} className="aspect-video w-full rounded-lg bg-black"/><label className="block text-xs text-muted-foreground">Время исходной записи<input aria-label={imported?'Время записи импортированной схемы':'Время записи рядом со схемой'} type="range" min={0} max={Math.max(0,rows.length-1)} value={position} disabled={exporting} className="mt-2 w-full accent-emerald-400" onChange={e=>{setPlaying(false);setPosition(Number(e.target.value));}}/></label><p className="text-xs text-muted-foreground">Это кадр из сохранённого H.264; между восстановленными камерами новое положение не достраивается.</p></div>;
  const needle=search.trim().toLocaleLowerCase();
  const shown=needle?clips.filter(c=>c.title.toLocaleLowerCase().includes(needle)||c.id.includes(needle)):clips;
  return <section aria-label="Просмотр записанных маршрутов" className="space-y-4 rounded-2xl border border-border bg-card p-4 sm:p-5">
    <div><h3 className="text-lg font-semibold">Записанные проходы</h3><p className="mt-1 text-sm text-muted-foreground">Локальная библиотека этого браузера. Кадры проверяются по SHA-256; время получения кадра не равно времени его захвата Android.</p></div>
    {!clips.length?<p className="text-sm text-muted-foreground">Сохранённых материалов пока нет.</p>:<div className="space-y-2"><div className="flex flex-wrap items-end justify-between gap-2"><label className="block min-w-0 flex-1 space-y-1 text-xs text-muted-foreground"><span>Поиск по названию или идентификатору</span><input className="w-full max-w-md rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground" value={search} onChange={e=>setSearch(e.target.value)} /></label><span className="text-xs text-muted-foreground">Показано {shown.length} из {clips.length}</span></div>{shown.length?<div className="grid max-h-72 gap-2 overflow-auto sm:grid-cols-2 xl:grid-cols-3">{shown.map(c=><Button key={c.id} aria-pressed={selected===c.id} className="h-auto min-w-0 flex-col items-start gap-1 whitespace-normal py-3 text-left" disabled={exporting||processing||renaming||deleting} variant={selected===c.id?'default':'outline'} onClick={()=>onSelect(c.id)}><span className="max-w-full break-words">{c.title}</span><span className="text-xs opacity-75">{teachingDate(c.createdAt)} · {c.id.slice(0,8)} · {c.complete?'Готов':'Неполный'} · {c.frames} кадров</span></Button>)}</div>:<p className="text-sm text-muted-foreground">По этому запросу записи не найдены.</p>}</div>}
    {libraryTruncated&&<p role="status" className="text-xs text-amber-500">Проверены первые 100 элементов библиотеки. Часть записей может не отображаться; исходные материалы не удалены.</p>}
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {capture&&rows.length>0&&<div aria-label="Измеренное качество сохранённой записи" className="grid gap-4 rounded-xl border border-border bg-muted/20 p-4 sm:grid-cols-[1fr_240px]"><div className="flex flex-wrap gap-x-6 gap-y-2 text-xs tabular-nums"><strong className={capture.cadence30Confirmed?'text-emerald-500':'text-amber-500'}>{capture.fps?.toFixed(2)??'—'} средних FPS</strong><span>{capture.cadence60Confirmed?'Ритм 60 FPS подтверждён по RTP':'60 FPS не подтверждены'}</span><span>{capture.bitrateBps==null?'—':(capture.bitrateBps/1e6).toFixed(2)} Мбит/с</span><span>Интервалы p95 {capture.p95GapMs?.toFixed(1)??'—'} мс · max {capture.maxGapMs?.toFixed(1)??'—'} мс</span><span>Интервалы &gt;25 мс: {capture.gaps25} · &gt;50 мс: {capture.gaps50} · &gt;200 мс: {capture.gaps200} · &gt;1 с: {capture.gaps1000}</span><p className="w-full text-muted-foreground">{capture.cadence30Confirmed?'Средняя частота записи не ниже 29,5 FPS, интервалов длиннее 50 мс нет.':'Ровный ритм 30 FPS не подтверждён. Для восстановления используются только реально записанные кадры.'} Качество рендера игры и полная задержка Android по этим данным неизвестны.</p></div><div><p className="mb-1 text-[10px] text-muted-foreground">Интервалы кадров по ходу записи, мс · график ограничен 100 мс</p><svg viewBox="0 0 240 60" className="h-16 w-full" role="img" aria-label="График интервалов видеокадров"><line x1={0} y1={50} x2={240} y2={50} stroke="currentColor" opacity={.2}/><polyline fill="none" stroke="currentColor" className="text-cyan-500" strokeWidth={1.5} points={capture.chart.map((n,i)=>`${i*240/Math.max(1,capture.chart.length-1)},${55-Math.min(100,n)*.5}`).join(' ')}/></svg></div></div>}
    {selected&&<div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]"><div className="min-w-0 space-y-3"><div ref={view} className="max-h-[75dvh] overflow-auto rounded-xl bg-black"><canvas ref={canvas} className="block h-auto max-w-none" style={{width:`${zoom*100}%`}} aria-label="Записанный видеокадр" /></div>
      <div aria-label="Просмотр маршрута по исходным кадрам" className="flex flex-wrap gap-2"><Button variant="outline" disabled={!rows.length||decoding||exporting||processing||position===0} onClick={()=>{setPlaying(false);setPosition(at=>seekTeachingSecond(rows,at,-1));}}>← Назад 1 с</Button><Button variant="outline" disabled={!rows.length||exporting||processing} onClick={()=>{if(position>=rows.length-1)setPosition(0);setPlaying(value=>!value);}}>{playing?'Приостановить просмотр':'Пройти по записи'}</Button><Button variant="outline" disabled={!rows.length||decoding||exporting||processing||position>=rows.length-1} onClick={()=>{setPlaying(false);setPosition(at=>seekTeachingSecond(rows,at,1));}}>Вперёд 1 с →</Button><select aria-label="Увеличение исходного кадра" value={zoom} className="rounded-lg border border-input bg-background px-2 text-sm" onChange={e=>setZoom(Number(e.target.value))}><option value={1}>Вписать</option><option value={1.5}>150%</option><option value={2}>200%</option><option value={3}>300%</option></select><Button variant="outline" onClick={()=>{const promise=view.current?.requestFullscreen?.();promise?.catch(()=>setError('Полноэкранный просмотр недоступен.'));}}>На весь экран</Button></div>
      <p className="text-xs text-muted-foreground">Исходные ракурсы записанного пути. Можно двигаться по времени и увеличивать детали; невидимые стороны и 360° этим не дорисовываются.</p>
      <label className="block text-sm">Кадр {position+1} / {rows.length} · {((rows[position]?.relative_ticks_90k??0)/90000).toFixed(3)} с {decoding?'· декодирование':''}<input aria-label="Время записанного прохода" type="range" min={0} max={Math.max(0,rows.length-1)} value={position} disabled={exporting} className="mt-2 w-full" onChange={e=>setPosition(Number(e.target.value))} /></label></div>
      <div className="space-y-3"><label className="block space-y-1 text-sm"><span>Название сохранённого маршрута</span><input className="w-full rounded-lg border border-input bg-background px-3 py-2" value={label} maxLength={128} disabled={renaming||exporting||processing||deleting} onChange={e=>setLabel(e.target.value)} /></label><Button variant="outline" disabled={renaming||exporting||processing||deleting||!directory.current||!label.trim()} onClick={()=>{void(async()=>{const folder=directory.current;if(!folder||!selected||deleteInFlight.current)return;setRenaming(true);try{await renameTeachingLabel(folder,selected,label);setLocalRefresh(n=>n+1);}catch(e){setError(e instanceof Error?e.message:'Название не сохранено.');}finally{setRenaming(false);}})();}}>Сохранить название</Button><h4 className="text-sm font-medium">Подтверждения рядом с кадром</h4><div className="max-h-56 space-y-1 overflow-auto font-mono text-xs">{nearby.length?nearby.map((i,n)=><p key={n}>#{String(i.sequence)} · палец {String(i.pointer_id)} · {String(i.outcome)} · {String(i.device_uptime_ms??'')} мс</p>):<p className="text-muted-foreground">В этом интервале нет подтверждений.</p>}</div>
        <Button className="w-full" disabled={exporting||processing||deleting||!directory.current||!clips.find(c=>c.id===selected)?.complete} onClick={()=>{void exportFolder();}}>Сохранить пакет в папку</Button>
        {exporting&&<Button variant="outline" onClick={()=>exportAbort.current?.abort()}>Отменить экспорт</Button>}
        {exporting&&exportProgress&&<p role="status" className="text-xs text-muted-foreground">{exportProgress.stage==='verify'?'Проверка сохранённого видео':'Копирование видео'} · {(exportProgress.bytes/1048576).toFixed(1)} / {(exportProgress.total/1048576).toFixed(1)} МБ</p>}
        {exportNotice&&<p role="status" className="break-all text-xs text-muted-foreground">{exportNotice}</p>}
        <details><summary className="cursor-pointer text-sm">Отдельные файлы и диагностика</summary><div className="mt-2 flex flex-wrap gap-2">{names.map(name=><Button disabled={exporting||deleting} size="sm" variant="outline" key={name} onClick={()=>{void download(name);}}>{name}</Button>)}</div></details>
        {!deleteConfirm?<Button disabled={exporting||processing||deleting} variant="ghost" className="text-destructive" onClick={()=>setDeleteConfirm(true)}>Удалить выбранный локальный материал</Button>:<div role="group" aria-label="Подтверждение удаления записи" className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3"><p className="text-xs leading-5 text-muted-foreground">Локальная запись и связанные с ней ссылки будут удалены из этого браузера. Если нужен архив, сначала сохраните пакет в папку.</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="destructive" disabled={deleting} onClick={()=>{void(async()=>{if(deleteInFlight.current)return;deleteInFlight.current=true;setDeleting(true);try{if(!storageScope||!/^[0-9a-f]{32}$/.test(storageScope)||!/^[0-9a-f]{32}$/.test(selected))throw Error();const root=await navigator.storage.getDirectory();const library=await root.getDirectoryHandle('sphere-teaching-'+storageScope);await library.removeEntry(selected,{recursive:true});onSelect(null);setLocalRefresh(v=>v+1);}catch{setError('Удаление не подтверждено. Проверьте библиотеку перед повтором.');}finally{deleteInFlight.current=false;setDeleting(false);setDeleteConfirm(false);}})();}}>{deleting?'Удаление…':'Удалить навсегда'}</Button><Button size="sm" variant="outline" disabled={deleting} onClick={()=>setDeleteConfirm(false)}>Отмена</Button></div></div>}
      </div></div>}
    {selected&&sourceManifestSha&&rows.length>0&&<section className="space-y-3 rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4"><div><h4 className="font-medium">Схема ориентиров и исходная запись</h4><p className="mt-1 text-xs leading-5 text-muted-foreground">Связанная сохранённая схема открывается вместе с выбранной записью. Нажмите на камеру, чтобы увидеть исходный кадр.</p></div><p role="status" className="text-xs text-muted-foreground">{alternativeStatus||'Если схема ещё не построена, подготовьте ориентиры ниже.'}</p>{alternatives.length>1&&<label className="block text-xs">Сохранённая схема<select aria-label="Сохранённая схема ориентиров" value={alternativeId??''} onChange={e=>setAlternativeId(e.target.value||null)} className="ml-2 rounded-lg border bg-background p-2">{alternatives.map((item,i)=><option key={item.id} value={item.id}>Схема {i+1} · {item.cameras} камер · {item.points} точек</option>)}</select></label>}{importError&&<p role="alert" className="text-xs text-destructive">{importError}</p>}{importedGeometry&&<RouteGeometryMap cameras={importedGeometry.cameras} points={importedGeometry.points} motionWarning={!!alternativeId} selectedTicks={rows[position]?.relative_ticks_90k??null} onSeekCamera={seekCamera} validTicks={validTicks} sourcePreview={sourceViewer(setImportedCanvas,true)}/>}<details><summary className="cursor-pointer text-xs text-muted-foreground">Открыть геометрию из файла</summary><label className="mt-2 block text-xs font-medium">Выбрать файл геометрии<input aria-label="Выбрать geometry.json для выбранной записи" type="file" accept=".json,application/json" className="mt-2 block w-full text-xs file:mr-3 file:rounded-md file:border file:bg-background file:px-3 file:py-2 file:text-foreground" onChange={e=>{const file=e.currentTarget.files?.[0];e.currentTarget.value='';if(file)void importGeometry(file);}}/></label><p className="mt-2 text-xs text-muted-foreground">Ручной импорт доступен до закрытия страницы. Исходная запись и файл не изменяются.</p></details></section>}
    {selected&&storageScope&&rows.length>0&&clips.some(c=>c.id===selected)&&<TeachingReconstruction key={selected} clip={selected} scope={storageScope} folder={()=>directory.current} complete={!exporting&&!deleting&&!!clips.find(c=>c.id===selected)?.complete} hudHidden={clips.find(c=>c.id===selected)?.hudHidden} onBusyChange={setProcessing} onRouteChange={routeChanged} visible={visible} sourceManifestSha={sourceManifestSha} selectedTicks={rows[position]?.relative_ticks_90k??null} onSeekCamera={seekCamera} validTicks={validTicks} sourcePreview={sourceViewer(setPreviewCanvas)} alternativeCameraCount={importedGeometry?.cameras.length??null}/>}
  </section>;
}
