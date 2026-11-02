'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { exportTeachingFolder, type ExportProgress } from './teachingExport';
import { TeachingReconstruction } from './TeachingReconstruction';
import type {ReconstructionJob} from './reconstructionClient';
import {teachingCaptureMetrics} from './teachingCaptureMetrics';
import { renameTeachingLabel, seekTeachingSecond } from './teachingMetadata';
import {readTeachingLibrary,type TeachingLibraryRecord} from './teachingLibrary';
import {readTeachingCatalogStatuses,type TeachingCatalogStatus} from './teachingCatalogStatus';
import {TeachingRecordingCatalog} from './TeachingRecordingCatalog';
import {teachingCatalogPresentation,type TeachingCatalogEntry} from './teachingCatalog';
import type {TeachingQueueSnapshot} from './teachingQueue';
import {exactRecordedFrame,readImportedRouteGeometry,type ImportedRouteGeometry} from './routeMapProjection';
import RouteGeometryMap from './RouteGeometryMap';
import ImageRouteReview from './ImageRouteReview';
import {reconstructionRequest} from './reconstructionClient';
import type {RouteSource} from './routeSource';
import type {SceneGeometrySelection} from './sceneGeometrySelection';
import {cameraMotionRequiresReview} from './routePreparation';

type Row = { index: number; offset: number; bytes: number; relative_ticks_90k: number; key: boolean; seekable?: boolean; sha256: string; worker_observed_at_ms: number };
type Clip = TeachingLibraryRecord;
type Alternative = {id:string;cameras:number;points:number;label?:string};
export function chooseReviewGeometry(items:Alternative[], preferred:unknown, primary:boolean|null, manual:string|null,visualPrimary=false):string|null {
  if(manual!==null)return manual==='primary'?(primary===true||visualPrimary?'primary':null):items.some(item=>item.id===manual)?manual:null;
  if(primary===true)return 'primary';
  if(primary!==false)return null;
  return typeof preferred==='string'&&items.some(item=>item.id===preferred)?preferred:visualPrimary?'primary':null;
}
export type TeachingClipChoice = Pick<Clip,'id'|'title'|'complete'|'frames'>;
const emptyClips:Clip[]=[];
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
export function TeachingReview({ selected, refresh, onSelect, storageScope, onBusyChange,onRouteChange,onClipsChange,onSourceChange,visible=true,autoPrepare=false,onAutoPrepareConsumed,manageAutomaticPreparation=true,processingQueue=null,onOpenNavigation }: { selected: string | null; refresh: number; onSelect: (id: string | null) => void; storageScope: string | null; onBusyChange?: (busy:boolean)=>void;onRouteChange?:(job:ReconstructionJob|null,clip:string|null,scope:string|null)=>void;onClipsChange?:(clips:TeachingClipChoice[])=>void;onSourceChange?:(source:RouteSource|null)=>void;visible?:boolean;autoPrepare?:boolean;onAutoPrepareConsumed?:()=>void;manageAutomaticPreparation?:boolean;processingQueue?:TeachingQueueSnapshot|null;onOpenNavigation?:()=>void }) {
  useEffect(()=>{onRouteChange?.(null,selected,storageScope);},[selected,storageScope,onRouteChange]);
  const [linkedJob,setLinkedJob]=useState<ReconstructionJob|null>(null);
  const routeChanged=useCallback((job:ReconstructionJob|null)=>{setLinkedJob(job);onRouteChange?.(job,selected,storageScope);},[onRouteChange,selected,storageScope]);
  const [libraryState,setLibraryState]=useState<{scope:string|null;records:Clip[]}>({scope:null,records:[]}),[error,setError]=useState<string|null>(null);
  const clips=libraryState.scope===storageScope?libraryState.records:emptyClips;
  const [libraryTruncated,setLibraryTruncated]=useState(false);
  const [libraryLoading,setLibraryLoading]=useState(true),[statusRefreshing,setStatusRefreshing]=useState(false);
  const [catalogState,setCatalogState]=useState<{scope:string|null;items:Record<string,TeachingCatalogStatus>}>({scope:null,items:{}});
  const [catalogNow,setCatalogNow]=useState(Date.now);
  useEffect(()=>{onClipsChange?.(clips);},[clips,onClipsChange]);
  const [rows,setRows]=useState<Row[]>([]),[inputs,setInputs]=useState<Record<string,unknown>[]>([]),[position,setPosition]=useState(0);
  const [sourceManifestSha,setSourceManifestSha]=useState<string|null>(null),[previewCanvas,setPreviewCanvas]=useState<HTMLCanvasElement|null>(null);
  const [loadedSourceKey,setLoadedSourceKey]=useState<string|null>(null);
  const [importedGeometry,setImportedGeometry]=useState<ImportedRouteGeometry|null>(null),[importError,setImportError]=useState<string|null>(null),[importedCanvas,setImportedCanvas]=useState<HTMLCanvasElement|null>(null);
  const [alternatives,setAlternatives]=useState<Alternative[]>([]),[alternativeId,setAlternativeId]=useState<string|null>(null),[alternativeStatus,setAlternativeStatus]=useState('');
  const [alternativesRefresh,setAlternativesRefresh]=useState(0);
  const [geometryRefresh,setGeometryRefresh]=useState(0);
  const manualAlternative=useRef<string|null>(null);
  const alternativeJob=useRef<string|null>(null);
  const [primaryAvailable,setPrimaryAvailable]=useState(false);
  const [primaryReady,setPrimaryReady]=useState(false),[primaryMotionWarning,setPrimaryMotionWarning]=useState(false),[loadedGeometryIdentity,setLoadedGeometryIdentity]=useState<string|null>(null);
  const [viewerMode,setViewerMode]=useState<'map'|'scene'|'video'>('map');
  const [sceneContainer,setSceneContainer]=useState<HTMLDivElement|null>(null),[catalogOpen,setCatalogOpen]=useState(!selected);
  const [archiveOpen,setArchiveOpen]=useState(false);
  const [localRefresh,setLocalRefresh]=useState(0),[decoding,setDecoding]=useState(false);
  const [deleteConfirm,setDeleteConfirm]=useState(false),[deleting,setDeleting]=useState(false);
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
  useEffect(()=>{onBusyChange?.(exporting||processing||renaming||deleting);},[exporting,processing,renaming,deleting,onBusyChange]);
  useEffect(()=>{setPlaying(false);setZoom(1);setDeleteConfirm(false);setViewerMode('map');if(selected)setCatalogOpen(false);},[selected]);
  useEffect(()=>{
    if(!playing||decoding)return;
    if(position>=rows.length-1){setPlaying(false);return;}
    const timer=setTimeout(()=>setPosition(at=>seekTeachingSecond(rows,at,.2)),200);
    return()=>clearTimeout(timer);
  },[playing,decoding,position,rows]);
  useEffect(()=>{
    const request=new AbortController();setLibraryLoading(true);setLibraryState({scope:storageScope,records:[]});setLibraryTruncated(false);
    if(!storageScope||!/^[0-9a-f]{32}$/.test(storageScope)){setLibraryLoading(false);return;}
    void readTeachingLibrary(storageScope,{signal:request.signal}).then(library=>{
      if(!request.signal.aborted){setLibraryState({scope:storageScope,records:library.records});setLibraryTruncated(library.truncated);}
    }).catch(()=>{if(!request.signal.aborted)setError('Не удалось прочитать локальную библиотеку браузера.');})
      .finally(()=>{if(!request.signal.aborted)setLibraryLoading(false);});
    return()=>request.abort();
  },[refresh,localRefresh,storageScope]);
  const queueItems=processingQueue?.scope===storageScope?processingQueue.items:[];
  const queueRevision=queueItems.map(item=>`${item.clip}:${item.jobId??''}:${item.phase}`).join('|');
  useEffect(()=>{
    setCatalogState(current=>current.scope===storageScope?current:{scope:storageScope,items:{}});
    if(!visible||!storageScope||!clips.length){setStatusRefreshing(false);return;}
    const request=new AbortController();let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      setStatusRefreshing(true);
      try{
        const prioritized=[...clips].sort((a,b)=>Number(b.id===selected)-Number(a.id===selected));
        const items=await readTeachingCatalogStatuses(prioritized,request.signal);
        if(!request.signal.aborted){setCatalogState({scope:storageScope,items});setCatalogNow(Date.now());}
      }catch{/* An aborted read cannot replace the next account or selection. */}
      finally{if(!request.signal.aborted){setStatusRefreshing(false);timer=setTimeout(()=>{void poll();},15000);}}
    };
    void poll();return()=>{request.abort();clearTimeout(timer);};
  },[clips,visible,storageScope,selected,queueRevision]);
  useEffect(()=>{const timer=setInterval(()=>setCatalogNow(Date.now()),5000);return()=>clearInterval(timer);},[]);
  const catalogEntries:TeachingCatalogEntry[]=clips.map(record=>{
    const status=catalogState.scope===storageScope?catalogState.items[record.id]:undefined;
    const queued=queueItems.find(item=>item.clip===record.id);
    const useQueue=queued&&(!status?.statusCheckedAt||queued.updatedAt>status.statusCheckedAt
      ||['waiting','persisting','uploading','processing'].includes(queued.phase)&&queued.jobId!==status.preparation?.jobId);
    return {id:record.id,title:record.title,createdAt:record.createdAt,frames:record.frames,durationSeconds:record.durationSeconds,
      deviceId:record.deviceId,controlMode:record.controlMode,hudProfile:record.hudProfile,hudHidden:record.hudHidden,
      sourceState:record.sourceState,sourceFailure:record.sourceFailure,...status,
      ...(useQueue?{preparation:{phase:queued.phase,reason:queued.reason,jobId:queued.jobId,updatedAt:queued.updatedAt},navigation:{phase:'not_prepared' as const},
        statusCheckedAt:queued.updatedAt}:{}),
    };
  });
  const selectedQueue=queueItems.find(item=>item.clip===selected);
  const selectedProcessing=!!selectedQueue&&['waiting','persisting','uploading','processing'].includes(selectedQueue.phase)
    ||catalogEntries.some(record=>record.id===selected&&!!record.preparation&&['waiting','persisting','uploading','processing'].includes(record.preparation.phase));
  useEffect(()=>{setLabel(clips.find(c=>c.id===selected)?.title??'');},[clips,selected]);
  useEffect(()=>{
    const current=++generation.current;importGeneration.current++;manualAlternative.current=null;alternativeJob.current=null;setLoadedSourceKey(null);setRows([]);setInputs([]);setPosition(0);setSourceManifestSha(null);setImportedGeometry(null);setImportError(null);setLinkedJob(null);setAlternatives([]);setAlternativeId(null);setAlternativeStatus('');directory.current=null;setError(null);
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
      if(current===generation.current){directory.current=folder;setRows(entries);setInputs(journal);setSourceManifestSha(manifestSha);setLoadedSourceKey(`${storageScope}:${selected}`);}
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
  const sourceFrames=useMemo(()=>new Map(rows.map(row=>[row.index,row.relative_ticks_90k])),[rows]);
  useEffect(()=>{onSourceChange?.(selected&&storageScope&&loadedSourceKey===`${storageScope}:${selected}`&&sourceManifestSha&&rows.length&&directory.current?
    {clip:selected,scope:storageScope,manifestSha:sourceManifestSha,rows,folder:directory.current}:null);
  },[selected,storageScope,sourceManifestSha,rows,onSourceChange,loadedSourceKey]);
  useEffect(()=>{
    if(!visible||!linkedJob||!sourceManifestSha||!rows.length)return;
    if(alternativeJob.current!==linkedJob.id){alternativeJob.current=linkedJob.id;manualAlternative.current=null;setAlternatives([]);setAlternativeId(null);setImportedGeometry(null);setPrimaryAvailable(false);setPrimaryReady(false);setLoadedGeometryIdentity(null);}
    const request=new AbortController();let retired=false;setAlternativeStatus('Проверяем сохранённые схемы…');
    void(async()=>{const data=await(await reconstructionRequest(`/jobs/${linkedJob.id}/geometry-alternatives`,linkedJob,{signal:request.signal})).json();
      if(!Array.isArray(data.alternatives)||data.alternatives.length>16)throw Error('alternative_list_invalid');
      const items=data.alternatives.filter((v:unknown):v is Alternative=>!!v&&typeof v==='object'&&typeof (v as {id?:unknown}).id==='string'&&/^[a-z0-9][a-z0-9-]{0,47}$/.test((v as {id:string}).id)&&(v as {id:string}).id!=='primary'&&Number.isSafeInteger((v as {cameras?:unknown}).cameras)&&Number.isSafeInteger((v as {points?:unknown}).points)&&(v as Alternative).cameras>=0&&(v as Alternative).points>=0&&((v as Alternative).label===undefined||typeof (v as Alternative).label==='string'&&(v as Alternative).label!.length<=128));
      // An admitted current map must not be hidden by an older experiment.
      const status=await reconstructionRequest(`/jobs/${linkedJob.id}`,linkedJob,{signal:request.signal}).then(r=>r.json()).catch(()=>null);
      const primary=status===null?null:status?.navigation?.phase==='ready'&&status?.geometry_available===true;
      const available=status?.geometry_available===true;
      if(!retired){const choice=chooseReviewGeometry(items,data.preferredAlternativeId,primary,manualAlternative.current,available);setPrimaryAvailable(available);setPrimaryReady(primary===true);setPrimaryMotionWarning(cameraMotionRequiresReview(status?.camera_motion));setAlternatives(items);if(manualAlternative.current==='__file__'){setAlternativeStatus('Схема из файла связана с выбранной записью.');return;}setAlternativeId(choice);if(choice)setGeometryRefresh(v=>v+1);if(!choice){importGeneration.current++;setImportedGeometry(null);}setAlternativeStatus(choice?'Загружаем выбранную схему…':manualAlternative.current===''?'Выберите схему.':manualAlternative.current!==null?'Выбранная схема больше недоступна. Выберите другую.':primary===null?'Не удалось подтвердить состояние основной карты. Выберите схему вручную.':items.length?'Выберите экспериментальную схему: рекомендация отсутствует.':'Дополнительных схем для этой реконструкции нет.');}
    })().catch(()=>{if(!retired)setAlternativeStatus('Не удалось проверить дополнительные схемы. Обычная реконструкция остаётся доступной.');});
    return()=>{retired=true;request.abort();};
  },[visible,linkedJob,sourceManifestSha,rows,alternativesRefresh]);
  useEffect(()=>{
    if(!visible||!linkedJob||!alternativeId||!sourceManifestSha)return;
    const controller=new AbortController(),current=generation.current,request=++importGeneration.current;setImportedGeometry(null);setLoadedGeometryIdentity(null);setImportError(null);
    const identity=JSON.stringify([storageScope,selected,linkedJob.id,sourceManifestSha,alternativeId]);
    void(async()=>{const data=await(await reconstructionRequest(`/jobs/${linkedJob.id}/${alternativeId==='primary'?'geometry':`geometry-alternatives/${alternativeId}`}`,linkedJob,{signal:controller.signal})).json();
      const geometry=readImportedRouteGeometry(data,sourceManifestSha,validTicks);
      if(current===generation.current&&request===importGeneration.current&&!controller.signal.aborted){setImportedGeometry(geometry);setLoadedGeometryIdentity(identity);setAlternativeStatus(alternativeId==='primary'?'Текущая подготовленная карта связана с исходной записью.':'Сохранённая экспериментальная схема связана с исходной записью.');}
    })().catch(()=>{if(current===generation.current&&request===importGeneration.current&&!controller.signal.aborted)setAlternativeStatus('Схема не прошла проверку привязки или недоступна.');});
    return()=>controller.abort();
  },[visible,linkedJob,alternativeId,sourceManifestSha,validTicks,geometryRefresh]);
  const seekCamera=(ticks:number)=>{const index=exactRecordedFrame(rows,ticks);if(index!==null){setPlaying(false);setPosition(index);}};
  const importGeometry=async(file:File)=>{
    const current=generation.current,request=++importGeneration.current;manualAlternative.current='__file__';setAlternativeId(null);setImportError(null);setImportedGeometry(null);setLoadedGeometryIdentity(null);
    try{if(file.size<1||file.size>16*1024*1024)throw Error('Файл геометрии пуст или превышает 16 МБ.');
      const geometry=readImportedRouteGeometry(JSON.parse(await file.text()),sourceManifestSha,validTicks);
      if(current===generation.current&&request===importGeneration.current){setImportedGeometry(geometry);setLoadedGeometryIdentity(JSON.stringify([storageScope,selected,linkedJob?.id,sourceManifestSha,'file']));setAlternativeStatus('Схема из файла связана с выбранной записью.');}
    }catch(e){if(current===generation.current&&request===importGeneration.current)setImportError(e instanceof Error?e.message:'Не удалось прочитать геометрию.');}
  };
  const sourceViewer=(setCanvas:(canvas:HTMLCanvasElement|null)=>void,imported=false)=><div className="space-y-2 rounded-xl border border-border bg-background/60 p-3"><p className="text-xs font-medium">Исходный кадр · {((rows[position]?.relative_ticks_90k??0)/90000).toFixed(3)} с {decoding?'· декодирование':''}</p><canvas ref={setCanvas} aria-label={imported?'Исходный кадр импортированной схемы':'Исходный кадр выбранной точки'} className="aspect-video w-full rounded-lg bg-black"/><label className="block text-xs text-muted-foreground">Время исходной записи<input aria-label={imported?'Время записи импортированной схемы':'Время записи рядом со схемой'} type="range" min={0} max={Math.max(0,rows.length-1)} value={position} disabled={exporting} className="mt-2 w-full accent-emerald-400" onChange={e=>{setPlaying(false);setPosition(Number(e.target.value));}}/></label><p className="text-xs text-muted-foreground">Это кадр из сохранённого H.264; между восстановленными камерами новое положение не достраивается.</p></div>;
  const selectedRecord=catalogEntries.find(record=>record.id===selected);
  const selectedStatus=selectedRecord?teachingCatalogPresentation(selectedRecord,{nowMs:catalogNow}):null;
  const sourceKey=storageScope&&selected?`${storageScope}:${selected}`:null;
  const choiceId=alternativeId??(manualAlternative.current==='__file__'?'file':null);
  const expectedGeometryIdentity=choiceId?JSON.stringify([storageScope,selected,linkedJob?.id,sourceManifestSha,choiceId]):null;
  const currentGeometry=expectedGeometryIdentity&&loadedGeometryIdentity===expectedGeometryIdentity&&loadedSourceKey===sourceKey?importedGeometry:null;
  const geometryLabel=choiceId==='primary'?(primaryReady?'Основная подготовленная карта':'Основная реконструкция · проверка'):
    choiceId==='file'?'Геометрия из файла':alternatives.find(item=>item.id===choiceId)?.label??'Дополнительная реконструкция';
  const selectedGeometry:SceneGeometrySelection|null=sourceKey&&linkedJob&&sourceManifestSha&&choiceId?{
    sourceKey,jobId:linkedJob.id,sourceManifestSha,id:choiceId,label:geometryLabel,diagnostic:choiceId!=='primary'||!primaryReady,geometry:currentGeometry,
    recordingRange:rows.length?{firstTicks:rows[0].relative_ticks_90k,lastTicks:rows.at(-1)!.relative_ticks_90k,frames:rows.length}:undefined,
  }:null;
  const operationBusy=exporting||processing||renaming||deleting;
  const chooseClip=(id:string)=>{setCatalogOpen(false);onSelect(id);};
  const chooseGeometry=(value:string)=>{
    if(value==='file')return;
    manualAlternative.current=value;importGeneration.current++;setImportedGeometry(null);setLoadedGeometryIdentity(null);setImportError(null);
    setAlternativeId(value||null);setAlternativeStatus(value?'Загружаем выбранный результат…':'Выберите результат восстановления.');
  };
  return <section aria-label="Просмотр записанных маршрутов" className="min-w-0 space-y-4 rounded-2xl border border-border bg-card p-4 sm:p-5">
    {selectedRecord&&<header className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4" aria-label="Выбранный маршрут">
      <div className="min-w-0 flex-1"><p className="text-[10px] font-semibold uppercase tracking-widest text-cyan-700 dark:text-cyan-300">Рабочее пространство маршрута</p><h3 className="mt-1 break-words text-lg font-semibold">{selectedRecord.title}</h3>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]" aria-label="Состояние выбранной записи">{[selectedStatus?.source.label,selectedStatus?.reconstruction.label,selectedStatus?.navigation.label].map((text,index)=><span key={index} className="rounded-md border border-border bg-background/65 px-2 py-1">{text}</span>)}</div>
      </div>
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={operationBusy} onClick={()=>setCatalogOpen(open=>!open)}>{catalogOpen?'Скрыть библиотеку':'Сменить запись'}</Button>
        {onOpenNavigation&&<Button size="sm" disabled={operationBusy||!linkedJob||selectedRecord.sourceState!=='saved'} onClick={()=>{setPlaying(false);onOpenNavigation();}}>Живая проверка</Button>}
        <Button size="sm" variant="ghost" disabled={operationBusy} onClick={()=>onSelect(null)}>Закрыть запись</Button></div>
    </header>}
    {(!selected||catalogOpen)&&<TeachingRecordingCatalog entries={catalogEntries} selectedId={selected} onSelect={chooseClip}
      onReload={()=>setLocalRefresh(value=>value+1)} loading={libraryLoading} refreshing={statusRefreshing}
      disabled={operationBusy} truncated={libraryTruncated} nowMs={catalogNow}/>}
    {selected&&!selectedRecord&&<p role="status" className="rounded-xl border border-border p-4 text-sm text-muted-foreground">{libraryLoading?'Читаем выбранную запись…':'Выбранная запись не найдена в библиотеке этого аккаунта.'}<Button variant="link" size="sm" onClick={()=>onSelect(null)}>Открыть библиотеку</Button></p>}
    {error&&<p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    <div className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
    <aside className="order-last min-w-0 xl:col-start-2 xl:row-start-1">
    {selected&&storageScope&&loadedSourceKey===sourceKey&&rows.length>0&&clips.some(c=>c.id===selected)&&<TeachingReconstruction key={`${storageScope}:${selected}`} clip={selected} scope={storageScope} folder={()=>directory.current}
      complete={!exporting&&!deleting&&!!clips.find(c=>c.id===selected)?.complete} hudHidden={clips.find(c=>c.id===selected)?.hudHidden} onBusyChange={setProcessing} onRouteChange={routeChanged}
      visible={visible} sourceManifestSha={sourceManifestSha} selectedTicks={rows[position]?.relative_ticks_90k??null} onSeekCamera={seekCamera} validTicks={validTicks}
      sourcePreview={sourceViewer(setPreviewCanvas)} alternativeCameraCount={currentGeometry?.cameras.length??null} manageAutomaticPreparation={manageAutomaticPreparation}
      processingJobId={selectedQueue?.jobId} autoPrepare={autoPrepare||clips.find(c=>c.id===selected)?.prepareAfterRecording===true} onAutoPrepareConsumed={onAutoPrepareConsumed}
      presentation="compact" selectedGeometry={selectedGeometry} sceneContainer={sceneContainer}/>}
    </aside>
    <div className="min-w-0 xl:col-start-1 xl:row-start-1">
    {selected&&sourceManifestSha&&rows.length>0&&<section className="min-w-0 overflow-hidden rounded-xl border border-border bg-background/35" aria-label="Единый просмотр выбранного результата">
      <header className="space-y-3 border-b border-border p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h4 className="font-semibold">Маршрут, ориентиры и исходные кадры</h4>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">Один выбранный результат для схемы и 3D; время синхронизировано с исходным видео.</p></div><Button size="sm" variant="outline" disabled={!linkedJob} onClick={()=>setAlternativesRefresh(value=>value+1)}>Обновить результаты</Button></div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end"><label className="min-w-0 flex-1 space-y-1 text-xs"><span>Результат восстановления</span>
          <select aria-label="Сохранённая схема ориентиров" value={choiceId??''} onChange={event=>chooseGeometry(event.target.value)} className="block h-10 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-sm">
            <option value="">Выберите результат</option>{primaryAvailable&&<option value="primary">{primaryReady?'Основная подготовленная карта':'Основная реконструкция · проверка'}</option>}
            {alternatives.map(item=><option key={item.id} value={item.id}>{item.label||'Дополнительный результат'} · {item.cameras} камер · {item.points} точек</option>)}
            {choiceId==='file'&&<option value="file">Геометрия из файла</option>}
          </select></label>
          <div role="group" aria-label="Вид выбранного результата" className="flex flex-wrap gap-1 rounded-lg border border-border bg-muted/25 p-1">{[
            ['map','Карта 2D'],['scene','Камеры и точки 3D'],['video','Исходное видео'],
          ].map(([mode,title])=><Button type="button" key={mode} size="sm" variant={viewerMode===mode?'secondary':'ghost'} aria-pressed={viewerMode===mode} disabled={mode==='scene'&&!linkedJob} onClick={()=>setViewerMode(mode as typeof viewerMode)}>{title}</Button>)}</div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-background/65 px-3 py-2 text-xs" aria-label="Источник геометрии всех просмотров">
          <span className="min-w-0 break-words font-medium">{choiceId?geometryLabel:'Результат не выбран'}</span><span className="tabular-nums text-muted-foreground">{currentGeometry?`${currentGeometry.cameras.length} камер · ${currentGeometry.points.length.toLocaleString('ru')} точек`:'Геометрия пока недоступна'}</span>
        </div>
        {choiceId&&choiceId!=='primary'&&<p className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-800 dark:text-amber-300">Это результат для проверки геометрии. Допуск живого движения и состояние основной карты показаны в блоке подготовки.</p>}
        <p role="status" className="min-h-5 text-xs text-muted-foreground">{alternativeStatus||'Сохранённые результаты появятся после обработки записи.'}</p>
        {importError&&<p role="alert" className="text-xs text-destructive">{importError}</p>}
      </header>
      <div className="min-w-0 p-3 sm:p-4">
        {viewerMode==='map'&&(currentGeometry?<RouteGeometryMap cameras={currentGeometry.cameras} points={currentGeometry.points} embedded motionWarning={choiceId==='primary'&&primaryMotionWarning}
          diagnosticId={selectedGeometry?.diagnostic?choiceId??undefined:undefined} selectedTicks={rows[position]?.relative_ticks_90k??null} onSeekCamera={seekCamera} validTicks={validTicks} sourcePreview={sourceViewer(setImportedCanvas,true)}/>:
          <div className="grid min-h-56 place-items-center rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">{choiceId?'Выбранный результат загружается или не прошёл проверку связи с видео.':'Выберите результат восстановления. Исходное видео доступно в соседнем режиме.'}</div>)}
        {viewerMode==='scene'&&<div ref={setSceneContainer} aria-label="3D выбранного результата" className="min-h-64 min-w-0"/>}
        <div hidden={viewerMode!=='video'} className="min-w-0 space-y-3"><div ref={view} className="max-h-[65dvh] overflow-auto rounded-xl bg-black"><canvas ref={canvas} className="block h-auto max-w-none" style={{width:`${zoom*100}%`}} aria-label="Записанный видеокадр"/></div>
          <div className="flex flex-wrap items-center gap-2"><label className="text-xs">Масштаб<select aria-label="Увеличение исходного кадра" value={zoom} className="ml-2 rounded-lg border border-input bg-background p-2 text-sm" onChange={event=>setZoom(Number(event.target.value))}><option value={1}>Вписать</option><option value={1.5}>150%</option><option value={2}>200%</option><option value={3}>300%</option></select></label><Button size="sm" variant="outline" onClick={()=>{view.current?.requestFullscreen?.()?.catch(()=>setError('Полноэкранный просмотр недоступен.'));}}>На весь экран</Button></div>
          <p className="text-xs leading-5 text-muted-foreground">Исходные кадры без дорисовывания невидимых сторон. Качество рендера игры сохранено таким, каким оно было записано.</p>
        </div>
      </div>
      <footer className="space-y-3 border-t border-border bg-background/65 p-4" aria-label="Общее время записи">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs tabular-nums"><strong>Кадр {position+1} / {rows.length} · {((rows[position]?.relative_ticks_90k??0)/90000).toFixed(3)} с</strong><span className="text-muted-foreground">{decoding?'Декодирование исходного кадра…':`Длительность ${(rows.at(-1)!.relative_ticks_90k/90000).toFixed(3)} с`}</span></div>
        <input aria-label="Время записанного прохода" type="range" min={0} max={Math.max(0,rows.length-1)} value={position} disabled={exporting} className="w-full accent-cyan-400" onChange={event=>{setPlaying(false);setPosition(Number(event.target.value));}}/>
        <div aria-label="Просмотр маршрута по исходным кадрам" className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={!rows.length||decoding||operationBusy||position===0} onClick={()=>{setPlaying(false);setPosition(at=>seekTeachingSecond(rows,at,-1));}}>← Назад 1 с</Button>
          <Button size="sm" variant="outline" disabled={!rows.length||operationBusy} onClick={()=>{if(position>=rows.length-1)setPosition(0);setPlaying(value=>!value);}}>{playing?'Приостановить просмотр':'Пройти по записи'}</Button>
          <Button size="sm" variant="outline" disabled={!rows.length||decoding||operationBusy||position>=rows.length-1} onClick={()=>{setPlaying(false);setPosition(at=>seekTeachingSecond(rows,at,1));}}>Вперёд 1 с →</Button></div>
      </footer>
    </section>}
    </div></div>
    {capture&&rows.length>0&&<details className="rounded-xl border border-border bg-muted/15 p-4"><summary className="cursor-pointer text-sm font-medium">Качество записи · {capture.fps?.toFixed(2)??'—'} средних FPS · {capture.bitrateBps==null?'—':(capture.bitrateBps/1e6).toFixed(2)} Мбит/с</summary>
      <div aria-label="Измеренное качество сохранённой записи" className="mt-3 space-y-2 text-xs leading-5 text-muted-foreground"><p>{capture.cadence30Confirmed?'Ритм 30 FPS подтверждён по временным меткам записи.':'Ровный ритм 30 FPS не подтверждён.'} {capture.cadence60Confirmed?'Ритм 60 FPS подтверждён.':'60 FPS не подтверждены.'}</p>
        <p>Интервалы p95 {capture.p95GapMs?.toFixed(1)??'—'} мс · max {capture.maxGapMs?.toFixed(1)??'—'} мс · &gt;50 мс: {capture.gaps50} · &gt;200 мс: {capture.gaps200} · &gt;1 с: {capture.gaps1000}</p>
        <svg viewBox="0 0 240 60" className="h-16 w-full max-w-md" role="img" aria-label="График интервалов видеокадров"><polyline fill="none" stroke="currentColor" className="text-cyan-500" strokeWidth={1.5} points={capture.chart.map((n,i)=>`${i*240/Math.max(1,capture.chart.length-1)},${55-Math.min(100,n)*.5}`).join(' ')}/></svg>
        <p>Это метрики сохранённого потока. Достоверность 3D, качество внутриигрового рендера и полная задержка Android оцениваются отдельно.</p>
      </div></details>}
    {selected&&<details className="rounded-xl border border-border bg-background/35 p-4" onToggle={event=>setArchiveOpen(event.currentTarget.open)}><summary className="cursor-pointer text-sm font-medium">Название, экспорт и диагностика</summary><div className="mt-4 grid min-w-0 gap-4 lg:grid-cols-2">
      <div className="space-y-3"><label className="block space-y-1 text-sm"><span>Название сохранённого маршрута</span><input className="w-full rounded-lg border border-input bg-background px-3 py-2" value={label} maxLength={128} disabled={renaming||exporting||processing||deleting} onChange={e=>setLabel(e.target.value)} /></label><Button variant="outline" disabled={renaming||exporting||processing||deleting||!directory.current||!label.trim()} onClick={()=>{void(async()=>{const folder=directory.current;if(!folder||!selected||deleteInFlight.current)return;setRenaming(true);try{await renameTeachingLabel(folder,selected,label);setLocalRefresh(n=>n+1);}catch(e){setError(e instanceof Error?e.message:'Название не сохранено.');}finally{setRenaming(false);}})();}}>Сохранить название</Button><h4 className="text-sm font-medium">Подтверждения рядом с кадром</h4><div className="max-h-56 space-y-1 overflow-auto font-mono text-xs">{nearby.length?nearby.map((i,n)=><p key={n}>#{String(i.sequence)} · палец {String(i.pointer_id)} · {String(i.outcome)} · {String(i.device_uptime_ms??'')} мс</p>):<p className="text-muted-foreground">В этом интервале нет подтверждений.</p>}</div>
        <Button className="w-full" disabled={exporting||processing||deleting||!directory.current||!clips.find(c=>c.id===selected)?.complete} onClick={()=>{void exportFolder();}}>Сохранить пакет в папку</Button>
        {exporting&&<Button variant="outline" onClick={()=>exportAbort.current?.abort()}>Отменить экспорт</Button>}
        {exporting&&exportProgress&&<p role="status" className="text-xs text-muted-foreground">{exportProgress.stage==='verify'?'Проверка сохранённого видео':'Копирование видео'} · {(exportProgress.bytes/1048576).toFixed(1)} / {(exportProgress.total/1048576).toFixed(1)} МБ</p>}
        {exportNotice&&<p role="status" className="break-all text-xs text-muted-foreground">{exportNotice}</p>}
        <details><summary className="cursor-pointer text-sm">Отдельные файлы и диагностика</summary><div className="mt-2 flex flex-wrap gap-2">{names.map(name=><Button disabled={exporting||deleting} size="sm" variant="outline" key={name} onClick={()=>{void download(name);}}>{name}</Button>)}</div></details>
        {!deleteConfirm?<Button disabled={exporting||processing||deleting||selectedProcessing} variant="ghost" className="text-destructive" onClick={()=>setDeleteConfirm(true)}>Удалить выбранный локальный материал</Button>:<div role="group" aria-label="Подтверждение удаления записи" className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3"><p className="text-xs leading-5 text-muted-foreground">Локальная запись и связанные с ней ссылки будут удалены из этого браузера. Если нужен архив, сначала сохраните пакет в папку.</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="destructive" disabled={deleting||selectedProcessing} onClick={()=>{void(async()=>{if(deleteInFlight.current||selectedProcessing)return;deleteInFlight.current=true;setDeleting(true);try{if(!storageScope||!/^[0-9a-f]{32}$/.test(storageScope)||!/^[0-9a-f]{32}$/.test(selected))throw Error();const root=await navigator.storage.getDirectory();const library=await root.getDirectoryHandle('sphere-teaching-'+storageScope);await library.removeEntry(selected,{recursive:true});onSelect(null);setLocalRefresh(v=>v+1);}catch{setError('Удаление не подтверждено. Проверьте библиотеку перед повтором.');}finally{deleteInFlight.current=false;setDeleting(false);setDeleteConfirm(false);}})();}}>{deleting?'Удаление…':'Удалить навсегда'}</Button><Button size="sm" variant="outline" disabled={deleting} onClick={()=>setDeleteConfirm(false)}>Отмена</Button></div></div>}
      </div>
      <div className="space-y-3"><h4 className="text-sm font-medium">Дополнительные данные</h4><details><summary className="cursor-pointer text-xs">Открыть геометрию из файла</summary><label className="mt-3 block text-xs font-medium">Выбрать файл геометрии<input aria-label="Выбрать geometry.json для выбранной записи" type="file" accept=".json,application/json" className="mt-2 block w-full text-xs" onChange={event=>{const file=event.currentTarget.files?.[0];event.currentTarget.value='';if(file)void importGeometry(file);}}/></label><p className="mt-2 text-xs text-muted-foreground">Импорт проверяется по исходнику и доступен до закрытия страницы; не даёт допуск движения.</p></details>
        {archiveOpen&&selected&&storageScope&&sourceManifestSha&&loadedSourceKey===sourceKey&&<ImageRouteReview key={`${storageScope}:${selected}:${sourceManifestSha}`} job={linkedJob} manifestSha={sourceManifestSha} frames={sourceFrames} refresh={alternativesRefresh} visible={visible} onSeek={seekCamera}/>}
      </div>
    </div></details>}
  </section>;
}
