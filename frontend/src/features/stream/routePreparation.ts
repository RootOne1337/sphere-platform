import {reconstructionRequest,ReconstructionResponseError,type NavigationState,type ReconstructionJob} from './reconstructionClient';

const idPattern=/^[0-9a-f]{32}$/;
const terminal=new Set(['ready','failed','rejected','cancelled']);
const phaseLabels:Record<string,string>={not_prepared:'не подготовлена',pending_auto_prepare:'ожидается подготовка',preparing:'подготовка',features:'поиск ориентиров',ready:'готова к проверке',failed:'ошибка подготовки',rejected:'не прошла проверку',cancelled:'отменена'};
const errorLabels:Record<string,string>={route_preparation_interrupted:'обработка прервалась при остановке сервиса',route_preparation_not_started:'автоматический запуск не подтверждён',route_camera_motion_requires_review:'траекторию камеры нужно проверить',camera_intrinsics_degenerate:'некорректные параметры восстановленной камеры',route_preparation_attempt_quota:'исчерпан лимит попыток подготовки этой сцены',route_map_has_unobserved_sections:'не хватает ориентиров на части пути',resource_guard:'недостаточно свободных ресурсов'};
export const navigationPhaseLabel=(phase:string|null|undefined)=>phase?(phaseLabels[phase]??'состояние уточняется'):'не прочитана';
export const navigationErrorLabel=(code:string)=>errorLabels[code]??'причину можно проверить в диагностике';
/** A confirmed quota rejection cannot be fixed by submitting another intent. */
export const preparationQuotaReached=(error:unknown)=>error instanceof ReconstructionResponseError&&error.status===409&&error.message==='route_preparation_attempt_quota';

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
    if(preparationQuotaReached(error))return 'Исчерпан лимит попыток для этой сцены. Повторные запуски не исправят ошибку траектории; откройте «Сцена» для диагностики.';
    if(error.message==='route_camera_motion_requires_review')return 'Траектория камер требует проверки. Откройте «Сцена»: карта для направления пока не подготовлена.';
    if(error.message==='camera_intrinsics_degenerate')return 'Расчёт дал некорректные параметры камеры. Откройте «Сцена»; исходная запись сохранена.';
    if(error.message==='one_active_job_only'||error.message==='route_workspace_busy')return 'Другая обработка ещё выполняется. Дождитесь её завершения.';
    if(error.message==='surface_completed_source_required'||error.message==='job_file_unavailable')return 'Камеры и исходная сцена ещё не прошли проверку. Откройте «Сцена» и проверьте причину.';
  }
  return 'Ответ не подтверждён. Проверьте состояние этого же задания; повторного запуска нет.';
}
