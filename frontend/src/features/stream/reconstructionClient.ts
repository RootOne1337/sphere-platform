export const reconstructionBase = 'http://127.0.0.1:3342';
export const reconstructionFiles = ['manifest.json','frames.jsonl','inputs.jsonl','video.h264','COMPLETE'] as const;
export type ReconstructionJob = {id:string; key:string; creation?:{mask:'avatar'|'game';steps:number;prepare_route:true;route_only:true}};
export type NavigationState = {phase:string;id?:string;error?:string|null;executionQualified?:false;resourceProfile?:{kind:string;minRamGiB:number};summary?:{cameras:number;landmarks:number;first_seconds?:number;last_seconds?:number;source_coverage?:{recording_start_seconds:number;recording_end_seconds:number;uncovered_start_seconds:number;uncovered_end_seconds:number;endpoints_observed:boolean};camera_trace_only:true;map_support:{all_reference_neighborhoods_supported:boolean;unobserved_intervals?:{start_seconds:number;end_seconds:number}[]}}};
export type SceneAppearance = {state:'unverified'|'passed'|'rejected';mean_psnr?:number;mean_ssim?:number;min_psnr?:number;min_ssim?:number;views?:{image:string;psnr:number;ssim:number}[]};
export type SurfaceState = {visual_review?:{state:'issues_found'|'limited_preview';issues:string[]};id?:string;fragment?:{first_view:number;view_count:number};phase:string;error?:string;available?:boolean;views?:number;total_views?:number;result?:{sha256:string;bytes:number;triangles:number;vertices:number;textures:number;texture_pixels:number;source_images:string[];mesh_faces:number;unknown_faces:number;seconds:number}};
export type HudTelemetry = {phase:string;accepted_count?:number;unknown_count?:number;selected_count?:number;source_manifest_sha256?:string;units?:string;samples?:{ticks_90k:number;hud_kmh:number|null}[]};
export type ReconstructionState = {telemetry?:HudTelemetry;completed_items?:number;total_items?:number;navigation?:NavigationState;camera_motion?:{warning:string|null;rapid_reversals?:number;speed_outliers?:number;heuristic_only?:boolean;navigation_qualified:false};phase:string; error?:string; geometry_available?:boolean; sparse_available?:boolean; dense_available?:boolean; dense_partial_available?:boolean; surface?:SurfaceState|null; fragments?:SurfaceState[]; surface_supported?:boolean; appearance?:SceneAppearance; checkpoint?:{steps:number;target_steps:number;partial:true}; quality?:{registered:number; selected:number; coverage:number; points:number; mean_reprojection_px:number; components?:number}; result?:{ply_sha256:string; ply_bytes:number}};
export function boundHudTelemetry(telemetry:HudTelemetry|undefined,sourceManifestSha:string|null|undefined):HudTelemetry|undefined {
  return sourceManifestSha && telemetry?.source_manifest_sha256===sourceManifestSha && ['ready','processing','failed','unavailable'].includes(telemetry.phase) ? telemetry : undefined;
}
export function hudChart(samples:HudTelemetry['samples']) {
  if(!Array.isArray(samples)||samples.length>601||samples.some((s,i)=>!Number.isSafeInteger(s.ticks_90k)||s.ticks_90k<0||(i>0&&s.ticks_90k<=samples[i-1].ticks_90k)||(s.hud_kmh!==null&&(typeof s.hud_kmh!=='number'||!Number.isFinite(s.hud_kmh)||s.hud_kmh<0))))return null;
  const accepted=samples.filter((s):s is {ticks_90k:number;hud_kmh:number}=>s.hud_kmh!==null);
  if(!accepted.length)return null;
  const min=Math.min(...accepted.map(s=>s.hud_kmh)),max=Math.max(...accepted.map(s=>s.hud_kmh));
  const start=samples[0].ticks_90k,end=samples[samples.length-1].ticks_90k, span=Math.max(1,end-start), top=Math.max(1,max);
  const segments:{x:number;y:number}[][]=[];let previous:number|null=null;
  for(const sample of samples){
    if(sample.hud_kmh===null){previous=null;continue;}
    if(previous===null||sample.ticks_90k-previous>18000)segments.push([]);
    segments[segments.length-1].push({x:10+280*(sample.ticks_90k-start)/span,y:90-80*sample.hud_kmh/top});previous=sample.ticks_90k;
  }
  return {min,max,segments};
}
export class ReconstructionResponseError extends Error {
  constructor(public readonly status:number, code:string){super(code);this.name='ReconstructionResponseError';}
}
export const processingSurface = (state:ReconstructionState) => [state.surface,...state.fragments??[]].find(item=>item&&!['ready','review_required','failed','cancelled'].includes(item.phase));
export const activeSurface = (state:ReconstructionState) => !!processingSurface(state);
export const terminalReconstruction = (state:ReconstructionState) => ['complete','sparse_complete','failed','cancelled','quality_rejected','review_required','partial_scene'].includes(state.phase)&&!activeSurface(state)&&!['pending_auto_prepare','preparing','features'].includes(state.navigation?.phase??'')
  &&(!state.navigation||['not_prepared','ready','rejected','failed','cancelled'].includes(state.navigation.phase));
export async function reconstructionRequest(path:string, job:ReconstructionJob|null, init:RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set('X-Sphere-Reconstruction','1');
  if(job) headers.set('X-Job-Key',job.key);
  const timeout=AbortSignal.timeout(20000);
  const response=await fetch(reconstructionBase+path,{...init,headers,credentials:'omit',cache:'no-store',signal:init.signal?AbortSignal.any([init.signal,timeout]):timeout});
  if(!response.ok) {
    const error=await response.json().catch(()=>({error:'local_worker_unavailable'}));
    throw new ReconstructionResponseError(response.status,String(error.error??response.status).slice(0,200));
  }
  return response;
}
export async function uploadReconstruction(folder:FileSystemDirectoryHandle, job:ReconstructionJob, progress:(bytes:number,total:number)=>void, signal:AbortSignal) {
  const files=await Promise.all(reconstructionFiles.map(async name=>({name,file:await(await folder.getFileHandle(name)).getFile()})));
  const limits:Record<string,number>={'manifest.json':65536,'frames.jsonl':16*1048576,'inputs.jsonl':8*1048576,'video.h264':2**31,COMPLETE:1024};
  if(files.some(({name,file})=>file.size<1||file.size>limits[name]))throw Error('source_file_quota');
  const offsets=await(await reconstructionRequest(`/jobs/${job.id}/offsets`,job,{signal})).json() as Record<string,number>;
  const total=files.reduce((sum,{file})=>sum+file.size,0);let copied=0;
  for(const {name,file} of files) {
    const first=offsets[name];
    if(!Number.isSafeInteger(first)||first<0||first>file.size)throw Error('invalid_worker_offset');
    copied+=first;progress(copied,total);
    for(let offset=first;offset<file.size;) {
      if(signal.aborted)throw new DOMException('Aborted','AbortError');
      const end=Math.min(offset+1048576,file.size);
      const response=await reconstructionRequest(`/jobs/${job.id}/input/${name}`,job,{method:'PUT',headers:{'Content-Type':'application/octet-stream','X-Upload-Offset':String(offset)},body:file.slice(offset,end),signal});
      const confirmed=await response.json();if(confirmed.offset!==end)throw Error('worker_upload_not_confirmed');
      copied+=end-offset;offset=end;progress(copied,total);
    }
  }
}
