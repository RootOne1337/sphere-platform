import {reconstructionRequest,terminalReconstruction,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
import {assertReconstructionSource} from './routeSourceBinding';

export type SavedRouteResult={job:ReconstructionJob;kind:'map'|'diagnostic'|'geometry';label:string;cameras:number|null;points:number|null};

/** Inspect only known archived capabilities, never create work or select a job.
 * At most eight attempts and two requests in flight. Unknown/foreign sources
 * are excluded before any alternative metadata can be shown. */
export async function readSavedRouteResults(attempts:readonly ReconstructionJob[],currentId:string,manifestSha:string,signal:AbortSignal,
  request:typeof reconstructionRequest=reconstructionRequest):Promise<SavedRouteResult[]> {
  if(!/^[0-9a-f]{64}$/.test(manifestSha))return [];
  const candidates=attempts.filter(item=>item.id!==currentId).slice(0,8),results:SavedRouteResult[]=[];let index=0;
  const guard=()=>{if(signal.aborted)throw new DOMException('Aborted','AbortError');};
  const count=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>=0?Number(value):null;
  const inspect=async()=>{while(index<candidates.length){guard();const job=candidates[index++];
    try{
      const state=await(await request(`/jobs/${job.id}`,job,{signal})).json() as ReconstructionState;guard();
      assertReconstructionSource(state,manifestSha);
      if(!terminalReconstruction(state))continue;
      const primary:SavedRouteResult|null=state.geometry_available?{job,kind:state.navigation?.phase==='ready'?'map':'geometry',
        label:state.navigation?.phase==='ready'?'Подготовленная карта':'Основная геометрия',cameras:count(state.quality?.registered),points:count(state.quality?.points)}:null;
      if(primary?.kind==='map'){results.push(primary);continue;}
      let catalog;try{catalog=await(await request(`/jobs/${job.id}/geometry-alternatives`,job,{signal})).json();guard();}
      catch{guard();if(primary)results.push(primary);continue;}
      const selected=catalog!==null&&typeof catalog==='object'&&!Array.isArray(catalog)&&Array.isArray(catalog.alternatives)&&catalog.alternatives.length<=16?
        catalog.alternatives.find((item:{id?:unknown})=>typeof item?.id==='string'&&item.id===catalog.preferredAlternativeId):null;
      if(selected&&/^[a-z0-9][a-z0-9-]{0,47}$/.test(selected.id)&&count(selected.cameras)!==null&&selected.cameras>=2&&selected.cameras<=256&&count(selected.points)!==null){
        results.push({job,kind:'diagnostic',label:typeof selected.label==='string'&&selected.label.length<=128?selected.label:'Сохранённая схема для просмотра',
          cameras:selected.cameras,points:selected.points});
      }else if(primary)results.push(primary);
    }catch{guard();/* A failed read cannot hide or select another attempt. */}
  }};
  await Promise.all([inspect(),inspect()]);guard();
  return results.sort((a,b)=>Number(b.kind==='map')-Number(a.kind==='map')||a.job.id.localeCompare(b.job.id));
}
