import {automaticReconstructionStopped,ensureAutomaticReconstructionLink,listReconstructionLinks,readReconstructionLink,stopAutomaticReconstruction} from './reconstructionLink';
import {reconstructionRequest,ReconstructionResponseError,terminalReconstruction,uploadReconstruction,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
import type {TeachingLibraryRecord} from './teachingLibrary';

export type TeachingQueuePhase='waiting'|'persisting'|'uploading'|'processing'|'ready'|'failed'|'cancelled'|'stopped'|'unavailable';
export type TeachingQueueItem={clip:string;jobId?:string;phase:TeachingQueuePhase;reason?:string;updatedAt:number};
export type TeachingQueueSnapshot={scope:string;activeClip:string|null;items:TeachingQueueItem[]};
type CaptureMaskPreference=Pick<TeachingLibraryRecord,'hudHidden'|'hudHiddenView'>;
export type QueueRecording={id:string;createdAt:number;complete:boolean;manifestSha:string|null;sourceState:string;folder:FileSystemDirectoryHandle;prepareAfterRecording:boolean}&CaptureMaskPreference;
type Dependencies={
  readLink:typeof readReconstructionLink;listLinks:typeof listReconstructionLinks;ensureLink:typeof ensureAutomaticReconstructionLink;
  stopped:typeof automaticReconstructionStopped;stop:typeof stopAutomaticReconstruction;
  request:typeof reconstructionRequest;upload:typeof uploadReconstruction;now:()=>number;
  locks:Pick<LockManager,'request'>|undefined;
};
const defaults=():Dependencies=>({readLink:readReconstructionLink,listLinks:listReconstructionLinks,ensureLink:ensureAutomaticReconstructionLink,stopped:automaticReconstructionStopped,stop:stopAutomaticReconstruction,
  request:reconstructionRequest,upload:uploadReconstruction,now:Date.now,locks:typeof navigator==='undefined'?undefined:navigator.locks});
const idPattern=/^[0-9a-f]{32}$/;
const abortError=()=>new DOMException('Aborted','AbortError');
const reasonCode=(value:unknown,fallback:string)=>typeof value==='string'&&/^[a-z0-9_]{1,160}$/.test(value)?value:fallback;
export function recordingPreparationMask({hudHidden,hudHiddenView}:CaptureMaskPreference):'none'|'avatar'|'game' {
  if(!hudHidden)return 'game';
  return hudHiddenView==='first_person'?'none':'avatar';
}
export function newAutomaticReconstruction(mask:'none'|'avatar'|'game'):ReconstructionJob {
  return {id:crypto.randomUUID().replaceAll('-',''),key:Array.from(crypto.getRandomValues(new Uint8Array(32)),v=>v.toString(16).padStart(2,'0')).join(''),creation:{mask,steps:30000,prepare_route:true,route_only:true}};
}
const fatal=(error:unknown)=>error instanceof ReconstructionResponseError
  &&([400,403,422].includes(error.status)||error.status===409&&!['job_not_found','resource_guard','one_active_job_only','upload_offset_mismatch_read_offsets_before_retry'].includes(error.message))
  ||error instanceof DOMException&&error.name==='NotFoundError'
  ||error instanceof Error&&['source_file_quota','invalid_worker_offset','reconstruction_lock_unavailable','preparation_source_mismatch'].includes(error.message);
function settled(state:ReconstructionState):TeachingQueuePhase {
  if(state.phase==='cancelled'||state.navigation?.phase==='cancelled')return 'cancelled';
  if(['failed','quality_rejected','partial_scene','review_required'].includes(state.phase)||['failed','rejected'].includes(state.navigation?.phase??''))return 'failed';
  return 'ready';
}

/** Only the account-level lock owner calls cycle. No timer, input, or selected clip owns this queue. */
export class TeachingQueueController {
  private deps:Dependencies;
  private items=new Map<string,TeachingQueueItem>();
  private candidates=new Map<string,ReconstructionJob>();
  private metadataFailures=new Map<string,number>();
  private terminal=new Map<string,string>();
  constructor(private readonly scope:string,private readonly signal:AbortSignal,private readonly changed:(snapshot:TeachingQueueSnapshot)=>void,dependencies:Partial<Dependencies>={}){
    if(!idPattern.test(scope))throw Error('recording_scope_invalid');
    this.deps={...defaults(),...dependencies};
  }
  private guard(){if(this.signal.aborted)throw abortError();}
  private binding(record:QueueRecording,job:ReconstructionJob){return `${job.id}:${record.manifestSha}`;}
  private publish(clip:string,phase:TeachingQueuePhase,job?:ReconstructionJob,reason?:string){
    this.items.set(clip,{clip,phase,...(job?{jobId:job.id}:{}),...(reason?{reason}:{}),updatedAt:this.deps.now()});
    this.changed({scope:this.scope,activeClip:['persisting','uploading','processing'].includes(phase)?clip:null,items:[...this.items.values()]});
  }
  private async mayContinue(record:QueueRecording,job:ReconstructionJob){
    this.guard();
    if(await this.deps.stopped(record.folder,job)){this.publish(record.id,'stopped',job,'automatic_preparation_stopped');this.terminal.set(record.id,this.binding(record,job));return false;}
    this.guard();return true;
  }
  private async readState(job:ReconstructionJob){
    this.guard();const response=await this.deps.request(`/jobs/${job.id}`,job,{signal:this.signal});this.guard();
    return await response.json() as ReconstructionState;
  }
  private bindState(record:QueueRecording,state:ReconstructionState){
    // An unfinished upload may not yet contain its manifest. Every later phase
    // must be bound to this exact sealed source, including terminal readback.
    if((state.phase!=='uploading'||state.source_manifest_sha256!=null)&&state.source_manifest_sha256!==record.manifestSha)throw Error('preparation_source_mismatch');
    return state;
  }
  private async advance(record:QueueRecording,job:ReconstructionJob):Promise<ReconstructionState|null>{
    if(!await this.mayContinue(record,job))return null;
    let state:ReconstructionState;
    try{state=this.bindState(record,await this.readState(job));}
    catch(error){
      // A lost create response is NOT absence. Only the same capability's confirmed 404 permits POST.
      if(!(error instanceof ReconstructionResponseError)||error.status!==404)throw error;
      if(!await this.mayContinue(record,job))return null;
      state=this.bindState(record,await(await this.deps.request('/jobs',null,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:job.id,key:job.key,...job.creation}),signal:this.signal})).json() as ReconstructionState);
    }
    if(state.phase!=='uploading'||!await this.mayContinue(record,job))return state;
    if(!this.deps.locks)throw Error('reconstruction_lock_unavailable');
    // Do not combine ifAvailable with signal: browsers reject that Web Locks option pair.
    await this.deps.locks.request(`sphere-reconstruction-upload-${job.id}`,{ifAvailable:true},async lock=>{
      if(!lock||!await this.mayContinue(record,job))return;
      state=this.bindState(record,await this.readState(job));
      if(state.phase!=='uploading')return;
      const upload=new AbortController();
      const abort=()=>upload.abort();this.signal.addEventListener('abort',abort,{once:true});
      let checking=false,checkError:unknown=null;
      const watcher=setInterval(()=>{
        if(checking||upload.signal.aborted)return;checking=true;
        void this.deps.stopped(record.folder,job).then(stopped=>{if(stopped)upload.abort();}).catch(error=>{checkError=error;upload.abort();}).finally(()=>{checking=false;});
      },500);
      try{
        this.publish(record.id,'uploading',job);
        this.guard();
        await this.deps.upload(record.folder,job,()=>{},upload.signal);
        if(checkError)throw checkError;
        if(!await this.mayContinue(record,job))return;
        state=this.bindState(record,await this.readState(job));
        if(state.phase==='uploading'&&await this.mayContinue(record,job)){
          state=this.bindState(record,await(await this.deps.request(`/jobs/${job.id}/start`,job,{method:'POST',body:'{}',signal:this.signal})).json() as ReconstructionState);
        }
      }catch(error){if(!this.signal.aborted&&await this.deps.stopped(record.folder,job)){this.publish(record.id,'stopped',job,'automatic_preparation_stopped');this.terminal.set(record.id,this.binding(record,job));return;}throw error;}
      finally{clearInterval(watcher);this.signal.removeEventListener('abort',abort);upload.abort();}
    });
    return state;
  }
  /** FIFO; a busy or unavailable service keeps the first pending intent, never allocates another. */
  async cycle(records:readonly QueueRecording[]):Promise<{pending:boolean;retryMs:number}>{
    this.guard();
    const verified=records.filter(record=>idPattern.test(record.id)&&record.complete&&record.sourceState==='saved'&&/^[0-9a-f]{64}$/.test(record.manifestSha??''))
      .sort((a,b)=>a.createdAt-b.createdAt||a.id.localeCompare(b.id));
    const present=new Set(verified.map(record=>record.id));for(const id of this.items.keys())if(!present.has(id)){this.items.delete(id);this.terminal.delete(id);this.candidates.delete(id);this.metadataFailures.delete(id);}
    for(const record of verified)if(record.prepareAfterRecording&&!this.items.has(record.id))this.items.set(record.id,{clip:record.id,phase:'waiting',updatedAt:this.deps.now()});
    for(const record of verified){
      let job:ReconstructionJob|null=null;
      try{
        this.guard();job=await this.deps.readLink(record.folder,record.id);this.guard();
        if(!job){const known=await this.deps.listLinks(record.folder,record.id);this.guard();
          if(known.length===1)job=known[0];
          else if(known.length>1){this.publish(record.id,'unavailable',undefined,'reconstruction_attempt_selection_required');continue;}
        }
        if(!record.prepareAfterRecording&&!job?.creation)continue;
        if(job&&this.terminal.get(record.id)===this.binding(record,job))continue;
        if((this.metadataFailures.get(record.id)??0)>=3){this.publish(record.id,'unavailable',job??undefined,'preparation_metadata_retry_limit');continue;}
        if(!job){
          const mask=recordingPreparationMask(record);
          let candidate=this.candidates.get(record.id);if(!candidate){candidate=newAutomaticReconstruction(mask);this.candidates.set(record.id,candidate);}
          this.publish(record.id,'persisting',candidate);
          try{job=await this.deps.ensureLink(record.folder,record.id,mask,candidate);}
          catch(error){const failures=(this.metadataFailures.get(record.id)??0)+1;this.metadataFailures.set(record.id,failures);this.publish(record.id,'unavailable',candidate,reasonCode(error instanceof Error?error.message:null,'preparation_metadata_failed'));return {pending:true,retryMs:failures<3?1000*failures:15000};}
          this.guard();
        }
        // Existing legacy/dense attempts have no durable sparse creation options: never retrofit consent.
        if(!job?.creation){this.publish(record.id,'unavailable',job??undefined,'legacy_preparation_requires_explicit_action');continue;}
        const state=await this.advance(record,job);this.guard();
        if(!state)continue;
        if(this.terminal.get(record.id)===this.binding(record,job))continue;
        if(terminalReconstruction(state)){
          const phase=settled(state),reason=state.navigation?.error??state.error;this.publish(record.id,phase,job,reason?reasonCode(reason,'preparation_failed'):undefined);this.terminal.set(record.id,this.binding(record,job));continue;
        }
        this.publish(record.id,state.phase==='uploading'?'uploading':'processing',job);
        return {pending:true,retryMs:2500};
      }catch(error){
        this.guard();
        if(fatal(error)&&job?.creation){
          try{await this.deps.stop(record.folder,job);this.publish(record.id,'stopped',job,reasonCode(error instanceof Error?error.message:null,'preparation_failed'));}
          catch{this.publish(record.id,'unavailable',job,'preparation_stop_not_confirmed');}
          this.terminal.set(record.id,this.binding(record,job));continue;
        }
        const reason=reasonCode(error instanceof Error?error.message:null,'local_worker_unavailable');
        this.publish(record.id,reason==='one_active_job_only'||reason==='resource_guard'?'waiting':'unavailable',job??undefined,reason);
        return {pending:true,retryMs:reason==='one_active_job_only'||reason==='resource_guard'?5000:10000};
      }
    }
    this.changed({scope:this.scope,activeClip:null,items:[...this.items.values()]});
    return {pending:false,retryMs:15000};
  }
}

export function queueWait(milliseconds:number,signal:AbortSignal):Promise<void>{
  return new Promise((resolve,reject)=>{
    if(signal.aborted){reject(abortError());return;}
    const abort=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);reject(abortError());};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},milliseconds);
    signal.addEventListener('abort',abort,{once:true});
  });
}

/** The lock is browser-origin + account scoped; releasing a tab never cancels a server job. */
export async function runTeachingProcessingQueue(scope:string,signal:AbortSignal,load:()=>Promise<readonly QueueRecording[]>,changed:(snapshot:TeachingQueueSnapshot)=>void,dependencies:Partial<Dependencies>={},wait=queueWait){
  const deps={...defaults(),...dependencies};
  if(!deps.locks){changed({scope,activeClip:null,items:[]});return;}
  const queue=new TeachingQueueController(scope,signal,changed,deps);
  while(!signal.aborted){
    await deps.locks.request(`sphere-teaching-processing-${scope}`,{ifAvailable:true},async lock=>{
      if(!lock||signal.aborted)return;
      let records:readonly QueueRecording[]=[],readAt=-Infinity;
      while(!signal.aborted){
        try{if(deps.now()-readAt>=15000){records=await load();readAt=deps.now();}if(signal.aborted)return;const result=await queue.cycle(records);await wait(result.retryMs,signal);}
        catch(error){if(signal.aborted)return;await wait(10000,signal);}
      }
    });
    if(!signal.aborted)await wait(5000,signal);
  }
}
