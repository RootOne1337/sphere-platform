import {reconstructionRequest,ReconstructionResponseError,type ReconstructionState} from './reconstructionClient';
import {readReconstructionLink,listReconstructionLinks} from './reconstructionLink';
import type {TeachingLibraryRecord} from './teachingLibrary';
import type {TeachingCatalogEntry,TeachingCatalogPreparationPhase,TeachingCatalogNavigationPhase} from './teachingCatalog';

export type TeachingCatalogStatus=Pick<TeachingCatalogEntry,'preparation'|'navigation'|'statusCheckedAt'>;
const phases=new Set(['uploading','starting','verifying','extracting','motion_sampling','image_route_indexing','vehicle_speed_reference','features','matching','cameras','training','evaluating','complete','sparse_complete','partial_scene','review_required','quality_rejected','failed','cancelled']);
const terminal=new Set(['complete','sparse_complete','partial_scene','review_required','quality_rejected','failed','cancelled']);
const navPhases=new Set<TeachingCatalogNavigationPhase>(['not_prepared','pending_auto_prepare','preparing','features','ready','failed','rejected','cancelled']);
const safeReason=(value:unknown)=>typeof value==='string'&&/^[a-z0-9_]{1,160}$/.test(value)?value:undefined;

/** A job capability alone is not proof that its pixels belong to this clip. */
export function projectTeachingCatalogStatus(status:ReconstructionState,manifestSha:string,jobId:string,checkedAt:number):TeachingCatalogStatus{
  if(!status||typeof status.phase!=='string'||!phases.has(status.phase)||!Number.isFinite(checkedAt)||checkedAt<0)throw Error('catalog_status_invalid');
  const bound=status.source_manifest_sha256===manifestSha;
  if(!bound&&!(status.phase==='uploading'&&status.source_manifest_sha256==null))return {
    preparation:{phase:'unavailable',reason:'catalog_source_unconfirmed',updatedAt:checkedAt,jobId},
    navigation:{phase:'unavailable',error:'catalog_source_unconfirmed'},statusCheckedAt:checkedAt};
  let phase:TeachingCatalogPreparationPhase=status.phase==='uploading'?'uploading':status.phase==='failed'||status.phase==='quality_rejected'?'failed':status.phase==='cancelled'?'cancelled':terminal.has(status.phase)?'ready':'processing';
  const nav=bound?status.navigation:undefined;
  if(nav?.phase==='pending_auto_prepare'||nav?.phase==='preparing'||nav?.phase==='features')phase='processing';
  return {preparation:{phase,reason:safeReason(status.error),updatedAt:checkedAt,jobId},
    navigation:{phase:nav&&navPhases.has(nav.phase as TeachingCatalogNavigationPhase)?nav.phase as TeachingCatalogNavigationPhase:'not_prepared',error:safeReason(nav?.error)},
    statusCheckedAt:checkedAt};
}

/** Bounded authenticated metadata reads; never creates, retries or starts work. */
export async function readTeachingCatalogStatus(record:TeachingLibraryRecord,signal?:AbortSignal):Promise<TeachingCatalogStatus>{
  const checkedAt=()=>Date.now();
  try{
    let job=await readReconstructionLink(record.folder,record.id);
    if(!job){
      const archived=await listReconstructionLinks(record.folder,record.id);
      if(archived.length===1)job=archived[0];
      else if(archived.length>1)return {preparation:{phase:'unavailable',reason:'reconstruction_attempt_selection_required',updatedAt:checkedAt()},statusCheckedAt:checkedAt()};
    }
    if(!job)return {};
    if(!record.manifestSha)return {preparation:{phase:'unavailable',reason:'catalog_source_unconfirmed',jobId:job.id,updatedAt:checkedAt()},statusCheckedAt:checkedAt()};
    const response=await reconstructionRequest(`/jobs/${job.id}`,job,{signal});
    return projectTeachingCatalogStatus(await response.json(),record.manifestSha,job.id,checkedAt());
  }catch(error){
    if(signal?.aborted)throw error;
    const reason=error instanceof ReconstructionResponseError?error.status===403?'catalog_access_denied':error.status===404?'catalog_job_missing':safeReason(error.message)??'catalog_status_unavailable':
      error instanceof SyntaxError||error instanceof Error&&error.message==='catalog_status_invalid'?'catalog_status_invalid':'catalog_status_unavailable';
    return {preparation:{phase:'unavailable',reason,updatedAt:checkedAt()},navigation:{phase:'unavailable',error:reason},statusCheckedAt:checkedAt()};
  }
}

export async function readTeachingCatalogStatuses(records:readonly TeachingLibraryRecord[],signal?:AbortSignal):Promise<Record<string,TeachingCatalogStatus>>{
  const result:Record<string,TeachingCatalogStatus>={};let at=0;
  const worker=async()=>{while(at<records.length){if(signal?.aborted)throw new DOMException('Чтение статусов отменено','AbortError');
    const record=records[at++];result[record.id]=await readTeachingCatalogStatus(record,signal);}};
  await Promise.all([worker(),worker()]);return result;
}
