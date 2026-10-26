import {reconstructionRequest,ReconstructionResponseError,type NavigationState,type ReconstructionJob} from './reconstructionClient';

const idPattern=/^[0-9a-f]{32}$/;
const terminal=new Set(['ready','failed','rejected','cancelled']);

/** A shared idempotent preparation intent for the scene and direction views. */
export async function prepareRoute(job:ReconstructionJob,scope:string,clip:string):Promise<NavigationState> {
  if(!idPattern.test(scope)||!idPattern.test(clip))throw Error('route_recording_identity_invalid');
  const key=`sphere-reconstruction-${scope}-${clip}:route-intent`;
  const saved=sessionStorage.getItem(key);
  const id=saved&&idPattern.test(saved)?saved:crypto.randomUUID().replaceAll('-','');
  sessionStorage.setItem(key,id);
  const result=await(await reconstructionRequest(`/jobs/${job.id}/navigation/prepare`,job,
    {method:'POST',body:JSON.stringify({id})})).json() as NavigationState;
  if(terminal.has(result.phase)&&sessionStorage.getItem(key)===id)sessionStorage.removeItem(key);
  return result;
}

export function preparationError(error:unknown):string {
  if(error instanceof ReconstructionResponseError) {
    if(error.message==='resource_guard')return 'Не хватает ресурсов для подготовки. Освободите память и повторите проверку; исходная запись не изменена.';
    if(error.message==='one_active_job_only'||error.message==='route_workspace_busy')return 'Другая обработка ещё выполняется. Дождитесь её завершения.';
    if(error.message==='surface_completed_source_required'||error.message==='job_file_unavailable')return 'Камеры и исходная сцена ещё не прошли проверку. Откройте «Сцена» и проверьте причину.';
  }
  return 'Ответ не подтверждён. Проверьте состояние этого же задания; повторного запуска нет.';
}
