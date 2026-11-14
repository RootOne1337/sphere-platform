import type {ReconstructionState} from './reconstructionClient';

export const routeSourceMismatch='Задание относится к другой записи или её исходник не подтверждён. Выберите сохранённую попытку этой записи; управление не включено.';

/** A capability identifies a job, not the currently selected recording. */
export function assertReconstructionSource(state:ReconstructionState,manifestSha:string|null|undefined,allowUpload=false):void {
  if(!manifestSha)return; // Older isolated callers have no recording context.
  if(allowUpload&&state?.phase==='uploading'&&state.source_manifest_sha256==null)return;
  if(!/^[0-9a-f]{64}$/.test(manifestSha)||state?.source_manifest_sha256!==manifestSha)throw Error(routeSourceMismatch);
}

export function routeRecordingIdentity(title:string|undefined,clip:string,jobId:string):string {
  return `Запись: ${title?.trim()||'Без названия'} · видео ${clip.slice(0,8)} · обработка ${jobId.slice(0,8)}`;
}
