export const reconstructionBase = 'http://127.0.0.1:3342';
export const reconstructionFiles = ['manifest.json','frames.jsonl','inputs.jsonl','video.h264','COMPLETE'] as const;
export type ReconstructionJob = {id:string; key:string};
export type SceneAppearance = {state:'unverified'|'passed'|'rejected';mean_psnr?:number;mean_ssim?:number;min_psnr?:number;min_ssim?:number;views?:{image:string;psnr:number;ssim:number}[]};
export type SurfaceState = {visual_review?:{state:'issues_found'|'limited_preview';issues:string[]};id?:string;fragment?:{first_view:number;view_count:number};phase:string;error?:string;available?:boolean;views?:number;total_views?:number;result?:{sha256:string;bytes:number;triangles:number;vertices:number;textures:number;texture_pixels:number;source_images:string[];mesh_faces:number;unknown_faces:number;seconds:number}};
export type ReconstructionState = {camera_motion?:{warning:string|null;rapid_reversals?:number;heuristic_only?:boolean;navigation_qualified:false};phase:string; error?:string; geometry_available?:boolean; dense_available?:boolean; dense_partial_available?:boolean; surface?:SurfaceState|null; fragments?:SurfaceState[]; surface_supported?:boolean; appearance?:SceneAppearance; checkpoint?:{steps:number;target_steps:number;partial:true}; quality?:{registered:number; selected:number; coverage:number; points:number; mean_reprojection_px:number}; result?:{ply_sha256:string; ply_bytes:number}};
export const processingSurface = (state:ReconstructionState) => [state.surface,...state.fragments??[]].find(item=>item&&!['ready','review_required','failed','cancelled'].includes(item.phase));
export const activeSurface = (state:ReconstructionState) => !!processingSurface(state);
export const terminalReconstruction = (state:ReconstructionState) => ['complete','failed','cancelled','quality_rejected','review_required','partial_scene'].includes(state.phase)&&!activeSurface(state);
export async function reconstructionRequest(path:string, job:ReconstructionJob|null, init:RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set('X-Sphere-Reconstruction','1');
  if(job) headers.set('X-Job-Key',job.key);
  const timeout=AbortSignal.timeout(20000);
  const response=await fetch(reconstructionBase+path,{...init,headers,credentials:'omit',cache:'no-store',signal:init.signal?AbortSignal.any([init.signal,timeout]):timeout});
  if(!response.ok) {
    const error=await response.json().catch(()=>({error:'local_worker_unavailable'}));
    throw Error(String(error.error??response.status).slice(0,200));
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
