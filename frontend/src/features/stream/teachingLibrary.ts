import {readTeachingLabel} from './teachingMetadata';

const idPattern=/^[0-9a-f]{32}$/;
const shaPattern=/^[0-9a-f]{64}$/;
export type TeachingLibraryRecord={
  id:string;title:string;createdAt:number;complete:boolean;frames:number;durationSeconds?:number;
  deviceId?:string;controlMode?:string;hudProfile?:string;hudHidden:boolean;hudHiddenView?:'first_person'|'third_person';prepareAfterRecording:boolean;
  manifestSha:string|null;sourceState:'saved'|'incomplete'|'unverified'|'unavailable';sourceFailure?:string;
  folder:FileSystemDirectoryHandle;
};
export type TeachingLibraryResult={records:TeachingLibraryRecord[];truncated:boolean};
const MAX_ENTRIES=4096,MAX_RECORDS=512,MAX_INDEX_SCAN_BYTES=64*1024**2;
const digest=async(data:ArrayBuffer)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),b=>b.toString(16).padStart(2,'0')).join('');
const abort=(signal?:AbortSignal)=>{if(signal?.aborted)throw new DOMException('Чтение библиотеки отменено','AbortError');};
const missing=(error:unknown)=>(error instanceof Error||error instanceof DOMException)&&error.name==='NotFoundError';
const boundedText=(value:unknown,max:number)=>typeof value==='string'?value.slice(0,max):undefined;
type Frame={index:number;offset:number;bytes:number;relative_ticks_90k:number;sha256:string;key:boolean};

/** Private account/origin library. No jobs, uploads, retries or device input. */
export async function readTeachingLibrary(scope:string,{signal,root:providedRoot}:{signal?:AbortSignal;root?:FileSystemDirectoryHandle}={}):Promise<TeachingLibraryResult>{
  if(!idPattern.test(scope))throw Error('teaching_library_scope');
  abort(signal);
  const root=providedRoot??await navigator.storage.getDirectory();
  let library:FileSystemDirectoryHandle;
  try{library=await root.getDirectoryHandle('sphere-teaching-'+scope);}catch(error){if(missing(error))return {records:[],truncated:false};throw error;}
  const iterable=library as FileSystemDirectoryHandle&{entries?:()=>AsyncIterable<[string,FileSystemHandle]>};
  if(typeof iterable.entries!=='function')throw Error('teaching_library_listing_unavailable');
  const records:TeachingLibraryRecord[]=[];let examined=0,indexBytes=0,truncated=false;
  for await(const [name,entry] of iterable.entries()){
    abort(signal);
    if(++examined>MAX_ENTRIES){truncated=true;break;}
    if(entry.kind!=='directory'||!idPattern.test(name))continue;
    if(records.length>=MAX_RECORDS){truncated=true;break;}
    const folder=await library.getDirectoryHandle(name);
    const record:TeachingLibraryRecord={id:name,title:'Запись без описания',createdAt:0,complete:false,frames:0,
      hudHidden:false,prepareAfterRecording:false,manifestSha:null,sourceState:'unavailable',folder};
    records.push(record);
    const read=async(filename:string,max:number)=>{abort(signal);const file=await(await folder.getFileHandle(filename)).getFile();
      if(file.size>max)throw Error('teaching_library_file_quota');return file;};
    try{
      const manifestFile=await read('manifest.json',65536),bytes=await manifestFile.arrayBuffer();abort(signal);
      const manifest=JSON.parse(new TextDecoder().decode(bytes));record.manifestSha=await digest(bytes);
      if(!manifest||!['sphere-browser-teaching-v1','sphere-browser-teaching-v2'].includes(manifest.schema)||manifest.id!==name)throw Error('teaching_library_manifest_binding');
      record.title=boundedText(manifest.config?.title,128)?.trim()||'Маршрут';
      try{record.title=await readTeachingLabel(folder,name,bytes)??record.title;}catch{/* Optional label damage cannot rewrite or invalidate the captured video. */}
      record.createdAt=typeof manifest.started_at_ms==='number'&&Number.isFinite(manifest.started_at_ms)&&manifest.started_at_ms>=0?manifest.started_at_ms:0;
      record.frames=Number.isSafeInteger(manifest.frames)&&manifest.frames>=0?manifest.frames:0;
      record.deviceId=boundedText(manifest.config?.device_id,128);
      record.controlMode=boundedText(manifest.config?.profile?.mode,64);
      record.hudProfile=boundedText(manifest.config?.profile?.hudProfile,64);
      record.hudHidden=manifest.config?.hud_hidden_declared===true;
      if(record.hudHidden&&['first_person','third_person'].includes(manifest.config?.hud_hidden_view))record.hudHiddenView=manifest.config.hud_hidden_view;
      record.prepareAfterRecording=manifest.config?.prepare_after_recording===true;
      if(manifest.complete!==true){record.sourceState='incomplete';record.sourceFailure=boundedText(manifest.failure,128)||'recording_incomplete';continue;}
      if(manifest.release_confirmed!==true)throw Error('teaching_library_release_unconfirmed');
      const marker=JSON.parse(await(await read('COMPLETE',1024)).text());
      if(marker?.manifest_sha256!==record.manifestSha)throw Error('teaching_library_complete_binding');
      const index=await read('frames.jsonl',16*1024**2),journal=await read('inputs.jsonl',8*1024**2);
      if(indexBytes+index.size+journal.size>MAX_INDEX_SCAN_BYTES){record.sourceState='unverified';record.sourceFailure='teaching_library_scan_budget';truncated=true;continue;}
      indexBytes+=index.size+journal.size;
      const indexRaw=await index.arrayBuffer(),journalRaw=await journal.arrayBuffer();abort(signal);
      for(const [filename,file,data] of [['frames.jsonl',index,indexRaw],['inputs.jsonl',journal,journalRaw]] as const){
        const expected=manifest.files?.[filename];
        if(expected?.bytes!==file.size||!shaPattern.test(expected?.sha256??'')||await digest(data)!==expected.sha256)throw Error('teaching_library_index_integrity');
      }
      const rows:Frame[]=new TextDecoder().decode(indexRaw).trim().split('\n').filter(Boolean).map(line=>JSON.parse(line));
      if(!rows.length||rows.length!==manifest.frames||rows.length>(manifest.schema==='sphere-browser-teaching-v2'?36000:7200)||rows.some((row,i)=>
        !row||row.index!==i||!Number.isSafeInteger(row.offset)||row.offset<0||!Number.isSafeInteger(row.bytes)||row.bytes<1||row.bytes>2*1024**2
        ||!Number.isSafeInteger(row.relative_ticks_90k)||row.relative_ticks_90k<0||typeof row.key!=='boolean'||!shaPattern.test(row.sha256)
        ||row.offset!==(i?rows[i-1].offset+rows[i-1].bytes:0)||i>0&&row.relative_ticks_90k<=rows[i-1].relative_ticks_90k))throw Error('teaching_library_frame_index');
      const events=new TextDecoder().decode(journalRaw).trim().split('\n').filter(Boolean).map(line=>JSON.parse(line));
      if(events.length>40000||events.length!==manifest.events||events.some(row=>!row||typeof row!=='object'||Array.isArray(row)))throw Error('teaching_library_input_index');
      const video=await read('video.h264',manifest.schema==='sphere-browser-teaching-v2'?2*1024**3:512*1024**2);
      if(video.size!==manifest.files?.['video.h264']?.bytes||rows.at(-1)!.offset+rows.at(-1)!.bytes!==video.size)throw Error('teaching_library_video_size');
      abort(signal);record.durationSeconds=rows.at(-1)!.relative_ticks_90k/90000;record.complete=true;record.sourceState='saved';
    }catch(error){
      abort(signal);record.complete=false;record.sourceState='unavailable';
      record.sourceFailure=missing(error)?'teaching_library_source_missing':error instanceof Error&&/^teaching_library_/.test(error.message)?error.message:'teaching_library_source_invalid';
    }
  }
  abort(signal);
  records.sort((a,b)=>b.createdAt-a.createdAt||a.id.localeCompare(b.id));
  return {records,truncated};
}
