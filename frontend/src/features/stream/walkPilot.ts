import type {TeachingInput} from './teachingContacts';
import {calibrated,fromPercent,profileIssue,type TeachingProfile} from './teachingKeymap';

export type WalkPlan={schema:'sphere-walk-plan-v1';phase:'waiting'|'following'|'stopped'|'arrived';reason:string;
  stick:[number,number];progressFraction:number|null;maxStick:.35;maxSeconds:60;
  groundRoute:false;executionQualified:false;cameraBodyAssumption:true};
export type WalkInputLease={active():boolean;set(vector:[number,number]):void;close():Promise<boolean>};
export type WalkInputControl={issue:string|null;open(signal:AbortSignal,journal:(event:TeachingInput)=>void):Promise<WalkInputLease>};
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
export const walkReasonLabel=(reason:string):string=>({
  walk_confirming_start:'Узнаём старт по нескольким свежим кадрам',
  walk_camera_relative_pursuit:'Идём к ближайшей точке записанного пути',
  walk_start_outside_recorded_beginning:'Старт далеко от начала записи',
  walk_localization_lost:'Ориентиры потеряны — движение прекращено',
  walk_relocalizing_neutral:'Стик отпущен: повторно подтверждаем положение рядом с последней позицией',
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
  walk_waiting_fresh_reply:'Стик отпущен: повторно подтверждаем три свежих решения',
  walk_stream_changed:'Поток остановился или изменился',
  walk_native_closed:'Нативный ввод закрылся',
  walk_manual_stop:'Остановлено оператором',
} as Record<string,string>)[reason]??`Пеший тест остановлен: ${reason}`;
