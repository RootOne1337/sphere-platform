import {calibrated,fromPercent,profileIssue,type TeachingProfile} from './teachingKeymap';
import {WalkStickSlew,walkingCameraIssue,type WalkInputControl,type WalkInputLease} from './walkPilot';
import type {TeachingPoint} from './teachingContacts';

export type VehicleCommand={pedal:'coast'|'throttle'|'brake';steering:number};
export type VehiclePlan=VehicleCommand&{schema:'sphere-vehicle-plan-v1';phase:'waiting'|'following'|'stopped'|'arrived';reason:string;
  progressFraction:number|null;maxSteering:.35;maxSpeedKmh:number;maxSeconds:number;maxDecisionAgeMs:450;maxAnswerHoldMs:350;groundRoute:false;executionQualified:false;cameraBodyAssumption:true;
  targetSpeedKmh:number|null;observedSpeedKmh:number|null;speedAccepted:boolean;targetViewCamera:[number,number,number]|null};
export type VehicleInputLease=WalkInputLease&{setVehicle(command:VehicleCommand):void};
export type VehicleInputControl=Omit<WalkInputControl,'open'>&{hudProfile:'black_russia_scooter_v1';open(...args:Parameters<WalkInputControl['open']>):Promise<VehicleInputLease>};

/** No sparse-map or HUD diagnostic can grant native input through this parser. */
export function readVehiclePlan(value:unknown):VehiclePlan|null {
  const p=value as VehiclePlan&{stick?:unknown};
  const speed=(v:unknown)=>v===null||typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=350;
  if(!p||p.schema!=='sphere-vehicle-plan-v1'||!['waiting','following','stopped','arrived'].includes(p.phase)
    ||typeof p.reason!=='string'||!/^[a-z0-9_]{1,100}$/.test(p.reason)
    ||!['coast','throttle','brake'].includes(p.pedal)||!Number.isFinite(p.steering)||Math.abs(p.steering)>.35
    ||p.maxSteering!==.35||!Number.isInteger(p.maxSeconds)||p.maxSeconds<60||p.maxSeconds>1800
    ||!Number.isInteger(p.maxSpeedKmh)||p.maxSpeedKmh<1||p.maxSpeedKmh>30
    ||p.maxDecisionAgeMs!==450||p.maxAnswerHoldMs!==350
    ||p.groundRoute!==false||p.executionQualified!==false||p.cameraBodyAssumption!==true
    ||typeof p.speedAccepted!=='boolean'||!speed(p.targetSpeedKmh)||!speed(p.observedSpeedKmh)
    ||p.targetSpeedKmh!==null&&p.targetSpeedKmh>p.maxSpeedKmh
    ||p.speedAccepted&&p.observedSpeedKmh===null
    ||p.progressFraction!==null&&(!Number.isFinite(p.progressFraction)||p.progressFraction<0||p.progressFraction>1)
    ||p.targetViewCamera!==null&&(!Array.isArray(p.targetViewCamera)||p.targetViewCamera.length!==3||p.targetViewCamera.some(n=>!Number.isFinite(n)||Math.abs(n)>1e9))
    ||p.phase==='following'&&(!p.speedAccepted||p.targetSpeedKmh===null||p.observedSpeedKmh===null)
    ||p.phase!=='following'&&(p.pedal!=='coast'||p.steering!==0)
    ||p.stick!==undefined&&(!Array.isArray(p.stick)||p.stick.length!==2||p.stick[0]!==p.steering||p.stick[1]!==0))return null;
  return p;
}
/** Hold an approved vehicle command, not a predicted pose. Reply admission and
 * independent raw RGB/native ACK freshness keep their existing strict fences. */
export function vehicleDecisionDeadline(capturedAt:number,answeredAt:number):number|null {
  if(!Number.isFinite(capturedAt)||!Number.isFinite(answeredAt)||answeredAt<capturedAt||answeredAt-capturedAt>=250)return null;
  return Math.min(capturedAt+450,answeredAt+350);
}

export function vehicleCalibrationIssue(profile:TeachingProfile,geometry:{width:number;height:number}|null):string|null {
  if(!geometry)return 'Подключите прямой поток.';
  if(profile.mode!=='vehicle_buttons'||profile.steering!=='stick')return 'Выберите транспорт с педалями и аналоговым стиком.';
  if(profile.hudProfile!=='black_russia_scooter_v1')return 'Примените подтверждённый профиль HUD скутера; скорость из неизвестного интерфейса не используется.';
  if(['stick','forward','reverse'].some(target=>!calibrated(profile,geometry,target as 'stick'|'forward'|'reverse')))return 'Укажите газ, тормоз и центр стика на текущем экране.';
  const issue=profileIssue(profile,geometry);if(issue)return issue;
  const center=fromPercent({x:profile.stick_x,y:profile.stick_y},geometry),short=Math.min(geometry.width,geometry.height);
  if(['forward','reverse'].some(target=>{const point=fromPercent(profile.vehicle[target as 'forward'|'reverse'],geometry);
    return Math.hypot(point.x-center.x,point.y-center.y)<=short*(profile.radius/100+.05);}))return 'Педаль пересекает зону стика. Проверьте точки управления.';
  return null;
}
export function vehicleCameraIssue(profile:TeachingProfile,geometry:{width:number;height:number}|null):string|null {
  const issue=walkingCameraIssue(profile,geometry);if(issue)return issue;
  if(!geometry||!profile.look)return 'Укажите свободную область камеры.';
  const camera=fromPercent(profile.look,geometry),margin=Math.min(geometry.width,geometry.height)*.05;
  if(['forward','reverse'].some(target=>{const pedal=fromPercent(profile.vehicle[target as 'forward'|'reverse'],geometry);
    return Math.hypot(pedal.x-camera.x,pedal.y-camera.y)<=margin;}))return 'Область камеры пересекает педаль. Выберите свободную область.';
  return null;
}
export function vehicleSteeringTarget(profile:TeachingProfile,geometry:{width:number;height:number},steering:number){
  if(vehicleCalibrationIssue(profile,geometry)||!Number.isFinite(steering)||Math.abs(steering)>.350001)throw Error('vehicle_controls_not_calibrated_or_bounded');
  const center=fromPercent({x:profile.stick_x,y:profile.stick_y},geometry),radius=profile.radius/100*Math.min(geometry.width,geometry.height);
  return {center,target:Math.abs(steering)<.001?center:{x:Math.round(center.x+steering*radius),y:center.y}};
}

/** Held binary pedals, never PWM or recorded-key playback. Pedal changes use
 * UP then DOWN: dragging a finger from gas to brake is not a new button press. */
export class VehicleContacts {
  private pedal:VehicleCommand['pedal']='coast';
  private slew=new WalkStickSlew();
  constructor(private control:{hasContact(id:number):boolean;set(id:number,point:TeachingPoint|null,notAfter?:number):void},
    private profile:TeachingProfile,private geometry:{width:number;height:number}){}
  neutral(now:number){this.pedal='coast';this.slew.next([0,0],now);}
  apply(command:VehicleCommand,now:number,notAfter:number){
    if(!['coast','throttle','brake'].includes(command.pedal)||!Number.isFinite(notAfter)||notAfter<=now||notAfter-now>350)throw Error('vehicle_decision_expired');
    // Returning to straight while driving is an ordinary steering correction.
    // A genuine safety neutral uses neutral() and centers immediately instead.
    const steering=this.slew.next([command.steering,0],now,false)[0];
    const {center,target}=vehicleSteeringTarget(this.profile,this.geometry,steering);
    if(Math.abs(steering)>=.001&&!this.control.hasContact(1))this.control.set(1,center,notAfter);
    if(Math.abs(steering)>=.001||this.control.hasContact(1))this.control.set(1,target,notAfter);
    if(command.pedal!==this.pedal&&this.control.hasContact(0))this.control.set(0,null,notAfter);
    const pedal=command.pedal==='coast'?null:fromPercent(this.profile.vehicle[command.pedal==='throttle'?'forward':'reverse'],this.geometry);
    this.control.set(0,pedal,notAfter);this.pedal=command.pedal;
  }
}

export function vehicleReasonLabel(reason:string,positionPreviouslyConfirmed=false):string|null {
  return ({vehicle_confirming_current_position:'Три свежих подтверждения текущего места перед движением',
    vehicle_confirming_position:positionPreviouslyConfirmed?'Положение потеряно: газ отпущен, ожидаем подтверждённые ориентиры':'Ищем положение по ориентирам; педали отпущены',
    vehicle_fresh_pose_required:'Ожидаем свежее положение; движение приостановлено',
    vehicle_speed_unconfirmed:'Скорость не подтверждена — газ отпущен; ждём свежие показания',
    vehicle_continuous_pursuit:'Следуем маршруту: газ удерживается, руль корректируется по свежим кадрам',
    vehicle_confirming_end:'Подтверждаем конец маршрута и остановку транспорта',
    vehicle_camera_trace_end_confirmed:'Конец записанного пути подтверждён; транспорт остановлен',
    vehicle_relocalization_timeout:'Положение не восстановилось за 15 секунд; сеанс завершён с отпущенными педалями',
    vehicle_time_limit:'Достигнут выбранный предел длительности; транспорт остановлен',
    vehicle_heading_outside_pursuit_cone:'Ракурс слишком отличается от пути; остановитесь и совместите камеру с направлением транспорта',
    vehicle_start_outside_recorded_beginning:'Начало записи не подтверждено. Для запуска с середины выберите подхват текущего места',
    vehicle_motion_without_route_progress:'Продвижение по маршруту не подтверждается; педали отпущены',
    vehicle_pose_or_corridor_unqualified:'Положение выходит за подтверждённый участок маршрута; движение остановлено',
    vehicle_pose_discontinuity:'Положение изменилось скачком; требуется повторная проверка места',
    vehicle_progress_discontinuity:'Обнаружен скачок по маршруту; движение остановлено',
    vehicle_pose_binding_or_age:'Источник или последовательность кадров изменились; прежний сеанс остановлен',
    vehicle_pose_invalid:'Получено некорректное положение; движение остановлено',
    vehicle_target_direction_unknown:'Направление ближайшей цели не подтверждено; движение приостановлено',
    vehicle_target_view_unknown:'Ориентация ближайшей цели не подтверждена; движение приостановлено',
    vehicle_reference_speed_invalid:'Профиль скорости записи не прошёл проверку; движение остановлено',
    vehicle_motion_feedback_invalid:'Подтверждение ввода не прошло проверку; контакты освобождены',
    vehicle_confirming_start:'Подтверждаем начало маршрута',vehicle_camera_relative_pursuit:'Следуем пути: газ и руль корректируются по свежему кадру',
    vehicle_speed_unknown:'Скорость на спидометре не подтверждена — педали отпущены',
    vehicle_reference_speed_unknown:'В этом месте нет подтверждённой скорости записи — педали отпущены',
    vehicle_speed_profile_unavailable:'Для записи нет проверенного профиля скорости. Откройте «Библиотека» и подготовьте маршрут.',
    vehicle_source_speed_not_prepared:'Профиль скорости этой записи ещё не подготовлен. Откройте «Библиотека» и проверьте обработку; газ не включён.',
    vehicle_source_profile_mismatch:'Профиль транспорта записи не совпадает с выбранным HUD. Используйте запись с тем же режимом скутера.',
    vehicle_hud_profile_required:'Нужен явно выбранный профиль HUD скутера для записи и живого экрана',
    vehicle_controls_not_calibrated_or_bounded:'Точки транспорта не подтверждены для текущего экрана',
    vehicle_start_unconfirmed:'Запуск транспорта не подтверждён; контакты освобождаются',
    vehicle_reply_not_bound:'Ответ транспорта не связан с этим кадром и сеансом',
    vehicle_motion_feedback_required:'Обновите страницу и локальный обработчик: протокол транспорта не совпадает',
    vehicle_manual_override:'Транспорт остановлен для ручного управления. Дождитесь освобождения контактов и включите ручное управление.',
    vehicle_decision_expired:'Свежий ответ транспорта не получен — газ отпущен, руль по центру',
  } as Record<string,string>)[reason]??null;
}
