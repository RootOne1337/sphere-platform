import type {TeachingInput} from './teachingContacts';
import {calibrated,fromPercent,profileIssue,type TeachingProfile} from './teachingKeymap';

export type WalkPlan={schema:'sphere-walk-plan-v1';phase:'waiting'|'following'|'stopped'|'arrived';reason:string;
  stick:[number,number];progressFraction:number|null;maxStick:.35;maxSeconds:60;
  groundRoute:false;executionQualified:false;cameraBodyAssumption:true};
export type WalkInputLease={active():boolean;failure?():string|null;set(vector:[number,number]):void;canLook?():boolean;look?(fraction:number,notAfter:number):Promise<boolean>;
  drag?(fraction:number|null,notAfter:number):Promise<boolean>;cameraLimits?:{min:number;max:number};close():Promise<boolean>};
export type WalkInputControl={issue:string|null;cameraIssue?:string|null;open(signal:AbortSignal,journal:(event:TeachingInput)=>void):Promise<WalkInputLease>};
/** No input owner exists yet: a short presentation gap may recover before open. */
export function waitForFreshWalkSource(fresh:()=>boolean,signal:AbortSignal):Promise<boolean>{
  if(signal.aborted)return Promise.resolve(false);
  if(fresh())return Promise.resolve(true);
  return new Promise(resolve=>{
    const finish=(value:boolean)=>{clearInterval(poll);clearTimeout(timeout);signal.removeEventListener('abort',aborted);resolve(value);};
    const aborted=()=>finish(false);
    const poll=setInterval(()=>{if(fresh())finish(true);},16);
    const timeout=setTimeout(()=>finish(false),1000);
    signal.addEventListener('abort',aborted,{once:true});
  });
}
export function walkingCameraIssue(profile:TeachingProfile,geometry:{width:number;height:number}|null):string|null {
  if(!geometry||!profile.look||!calibrated(profile,geometry,'look'))return 'Укажите свободную область поворота камеры на текущем экране.';
  const p=fromPercent(profile.look,geometry),margin=Math.min(geometry.width,geometry.height)*.05;
  if(p.x<margin||p.x>=geometry.width-margin||p.y<margin||p.y>=geometry.height-margin)return 'Зона камеры слишком близко к краю экрана.';
  const stick=fromPercent({x:profile.stick_x,y:profile.stick_y},geometry);
  if(Math.hypot(p.x-stick.x,p.y-stick.y)<Math.min(geometry.width,geometry.height)*profile.radius/100+margin)return 'Область камеры пересекает стик. Выберите свободную область.';
  return null;
}
export function walkTargetCamera(value:unknown):[number,number,number]|null {
  return Array.isArray(value)&&value.length===3&&value.every(n=>Number.isFinite(n)&&Math.abs(n)<=1e9)?value as [number,number,number]:null;
}
export function readWalkPlan(value:unknown):WalkPlan|null {
  const p=value as WalkPlan;
  if(!p||p.schema!=='sphere-walk-plan-v1'||!['waiting','following','stopped','arrived'].includes(p.phase)
    ||typeof p.reason!=='string'||!/^[a-z0-9_]{1,100}$/.test(p.reason)
    ||p.maxStick!==.35||p.maxSeconds!==60||p.groundRoute!==false||p.executionQualified!==false||p.cameraBodyAssumption!==true
    ||!Array.isArray(p.stick)||p.stick.length!==2||p.stick.some(v=>!Number.isFinite(v))||Math.hypot(...p.stick)>.350001
    ||p.phase!=='following'&&p.stick.some(v=>v!==0)
    ||p.progressFraction!==null&&(!Number.isFinite(p.progressFraction)||p.progressFraction<0||p.progressFraction>1))return null;
  return p;
}
export function walkingCalibrationIssue(profile:TeachingProfile,geometry:{width:number;height:number}|null):string|null {
  if(!geometry)return 'Подключите прямой поток.';
  if(profile.mode!=='stick')return 'Выберите схему «Стик»: пеший тест не управляет транспортом.';
  if(!calibrated(profile,geometry,'stick'))return 'Укажите центр стика на текущем экране перед пешим тестом.';
  return profileIssue(profile,geometry);
}
export function walkingStickTarget(profile:TeachingProfile,geometry:{width:number;height:number},vector:[number,number]) {
  if(walkingCalibrationIssue(profile,geometry)||!Array.isArray(vector)||vector.length!==2
      ||vector.some(v=>!Number.isFinite(v))||Math.hypot(...vector)>.350001)throw Error('walk_stick_not_calibrated_or_bounded');
  const center=fromPercent({x:profile.stick_x,y:profile.stick_y},geometry);
  const radius=profile.radius/100*Math.min(geometry.width,geometry.height);
  return {center,target:Math.hypot(...vector)<.001?null:{x:Math.round(center.x+vector[0]*radius),y:Math.round(center.y+vector[1]*radius)}};
}
/** Neutral is a MOVE to the calibrated center, never a repeated tap. */
export function applyWalkingStick(control:{hasContact(id:number):boolean;set(id:number,point:{x:number;y:number}|null):void},profile:TeachingProfile,geometry:{width:number;height:number},vector:[number,number]){
  const {center,target}=walkingStickTarget(profile,geometry,vector);
  if(target&&!control.hasContact(0))control.set(0,center);
  if(target||control.hasContact(0))control.set(0,target??center);
}
/** Rate-limit from the vector actually sent after a neutral pause, not from
 * the server's previous desired vector. Neutralization itself is immediate. */
export class WalkStickSlew {
  private vector:[number,number]=[0,0];private at:number|null=null;
  next(target:[number,number],now:number):[number,number]{
    if(!Number.isFinite(now)||this.at!==null&&now<this.at||target.some(v=>!Number.isFinite(v))||Math.hypot(...target)>.350001)throw Error('walk_stick_not_calibrated_or_bounded');
    const dt=this.at===null?.05:Math.min(.1,(now-this.at)/1000);this.at=now;
    if(Math.hypot(...target)<.001){this.vector=[0,0];return [0,0];}
    const delta=[target[0]-this.vector[0],target[1]-this.vector[1]],length=Math.hypot(...delta),scale=length?Math.min(1,dt*1.2/length):0;
    this.vector=[this.vector[0]+delta[0]*scale,this.vector[1]+delta[1]*scale];return [...this.vector];
  }
}
export const walkReasonLabel=(reason:string):string=>({
  walk_confirming_start:'Узнаём старт по нескольким свежим кадрам',
  walk_confirming_current_position:'Узнаём текущую точку маршрута: три свежих подтверждения перед движением',
  walk_camera_relative_pursuit:'Идём к ближайшей точке записанного пути',
  walk_start_outside_recorded_beginning:'Положение найдено за пределами начального участка: вернитесь ближе к старту записи',
  walk_localization_lost:'Ориентиры потеряны — движение прекращено',
  walk_relocalizing_neutral:'Стик в центре: повторно подтверждаем положение рядом с последней позицией',
  walk_relocalization_timeout:'Положение не восстановилось за 2 секунды — тест остановлен',
  walk_relocalization_drift:'Повторно найденная позиция слишком отличается — тест остановлен',
  walk_relocalization_budget:'Лимит трёх повторных привязок исчерпан — тест остановлен',
  walk_pose_binding_or_age:'Поза устарела или источник изменился',
  walk_pose_or_corridor_unqualified:'Положение вне проверяемого коридора',
  walk_progress_reversed:'Прогресс по маршруту пошёл в обратную сторону',
  walk_progress_jump:'Обнаружен скачок положения на маршруте',
  walk_no_route_progress:'Продвижение не подтверждается: возможно препятствие',
  walk_confirming_end:'Проверяем конец пути — стик отпущен',
  walk_camera_trace_end_confirmed:'Конец пути камеры подтверждён',
  walk_target_direction_unknown:'Направление к ближайшей цели не определено',
  walk_time_limit:'Предел 60 секунд достигнут',
  walk_decision_expired:'Нет свежего решения — стик освобождается',
  walk_waiting_fresh_reply:'Стик в центре: ждём новое свежее решение',
  walk_stream_changed:'Поток остановился или изменился',
  walk_native_closed:'Нативный ввод закрылся',
  contact_video_stale:'Ввод остановлен: браузер не подтвердил новый видеокадр за 250 мс',
  contact_ack_timeout:'Android не подтвердил команду за 500 мс — ввод закрыт',
  contact_channel_closed:'Прямой канал ввода закрылся',
  contact_ready_timeout:'Android не подтвердил готовность стика за 6 секунд',
  camera_stroke_expired:'Поворот камеры не успел завершиться на свежем решении — ввод освобождён',
  walk_camera_aligned:'Взгляд вдоль пути · двигаемся',
  walk_camera_alignment_required:'Стик в центре: направляем камеру вдоль пути',
  walk_camera_calibrating:'Стик в центре: проверяем отклик горизонтального поворота камеры',
  walk_camera_turning:'Стик в центре: плавно направляем камеру вдоль пути',
  walk_camera_waiting_feedback:'Стик в центре: ждём новый кадр после поворота камеры',
  walk_camera_waiting_neutral:'Ждём подтверждения нейтрали стика перед коррекцией камеры',
  walk_camera_pose_unavailable:'Для поворота камеры нет свежей подтверждённой позы',
  walk_camera_pitch_mismatch:'Взгляд сильно отклонён по вертикали: восстановите ракурс записи',
  walk_camera_input_unconfirmed:'Android не подтвердил поворот камеры',
  walk_camera_feedback_timeout:'После поворота нет подтверждённого отклика камеры',
  walk_camera_response_not_observed:'Android принял свайпы, но ракурс не изменился. Проверьте начало свайпа: свободная область вне кнопок и стика',
  walk_camera_response_wrong_direction:'Камера повернулась в неожиданную сторону — тест остановлен',
  walk_camera_response_too_large:'Камера повернулась слишком резко — тест остановлен',
  walk_camera_gain_unqualified:'Отклик камеры не прошёл проверку чувствительности',
  walk_camera_not_converging:'Повороты не направляют взгляд к пути — тест остановлен',
  walk_camera_alignment_timeout:'Не удалось направить камеру вдоль пути за 8 секунд',
  walk_camera_pulse_limit:'Лимит небольших поворотов камеры достигнут',
  walk_camera_resolution_limit:'Чувствительность камеры слишком велика для точного короткого свайпа. Уменьшите её в игре',
  walk_camera_releasing:'Направление камеры выставлено · завершаем удерживаемый свайп',
  walk_camera_recentering:'Переставляем палец камеры; стик остаётся в центре',
  walk_source_not_ready:'Свежий кадр не появился перед открытием ввода. Проверьте прямой поток и повторите запуск',
  walk_manual_stop:'Остановлено оператором',
} as Record<string,string>)[reason]??`Пеший тест остановлен: ${reason}`;
