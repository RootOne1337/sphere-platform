import { stickPoint, type TeachingPoint } from './teachingContacts';

export type VehicleButton = 'forward' | 'reverse' | 'left' | 'right';
export type CalibrationTarget = 'stick' | 'action' | 'look' | VehicleButton;
export type PercentPoint = { x: number; y: number };
export const keyRoles = ['forward','reverse','left','right','action','slow'] as const;
export type TeachingKeyRole = typeof keyRoles[number];
export type TeachingKeys = Record<TeachingKeyRole,string>;
export const defaultTeachingKeys: TeachingKeys = {forward:'KeyW',reverse:'KeyS',left:'KeyA',right:'KeyD',action:'Space',slow:'ShiftLeft'};
export const keyRoleNames: Record<TeachingKeyRole,string> = {forward:'Вперёд / газ',reverse:'Назад / тормоз',left:'Влево',right:'Вправо',action:'Действие',slow:'Медленный ход'};
export type TeachingProfile = {
  schema: 'sphere-touch-keymap-v1';
  mode: 'stick' | 'vehicle_buttons';
  stick_x: number; stick_y: number; radius: number; action_x: number; action_y: number;
  vehicle: Record<VehicleButton, PercentPoint>;
  calibration: { width: number; height: number; buttons: CalibrationTarget[] } | null;
  /** Optional physical keyboard mapping; recorded contacts remain Android coordinates. */
  keys?: TeachingKeys;
  look?:PercentPoint;
};
export const teachingKeys = (profile: TeachingProfile): TeachingKeys => profile.keys ?? defaultTeachingKeys;
export function keyLabel(code: string): string {
  return ({Space:'Пробел',ShiftLeft:'Левый Shift',ShiftRight:'Правый Shift',ArrowUp:'↑',ArrowDown:'↓',ArrowLeft:'←',ArrowRight:'→'} as Record<string,string>)[code] ?? code.replace(/^(Key|Digit)/,'');
}
export function keyBindingIssue(keys: TeachingKeys): string | null {
  if(!keys || Object.keys(keys).length!==keyRoles.length || keyRoles.some(role=>typeof keys[role]!=='string'||! /^(Key[A-Z]|Digit[0-9]|Arrow(Up|Down|Left|Right)|Space|Shift(Left|Right))$/.test(keys[role])))return 'Выберите букву, цифру, стрелку, пробел или Shift. Escape всегда останавливает ввод.';
  if(new Set(Object.values(keys)).size!==keyRoles.length)return 'Одна клавиша уже назначена другому действию. Выберите свободную клавишу.';
  return null;
}
export function bindTeachingKey(profile: TeachingProfile, role: TeachingKeyRole, code: string): TeachingProfile {
  const keys={...teachingKeys(profile),[role]:code};
  const issue=keyBindingIssue(keys);if(issue)throw Error(issue);
  return {...profile,keys};
}
export function teachingRole(code: string, profile: TeachingProfile): TeachingKeyRole | null {
  const keys=teachingKeys(profile);
  // Preserve the original two-Shift default without making explicit mappings ambiguous.
  if(!profile.keys&&code==='ShiftRight')return 'slow';
  return keyRoles.find(role=>keys[role]===code)??null;
}
function canonicalKeys(physical: ReadonlySet<string>, profile: TeachingProfile): Set<string> {
  const result=new Set<string>();
  physical.forEach(code=>{const role=teachingRole(code,profile);if(role)result.add(defaultTeachingKeys[role]);});
  return result;
}
export const vehicleButtons: VehicleButton[] = ['forward','reverse','left','right'];
export const calibrationNames: Record<CalibrationTarget,string> = {
  stick:'центр стика',action:'кнопку действия',look:'свободную область поворота камеры',forward:'газ / вперёд',reverse:'тормоз / назад',left:'поворот влево',right:'поворот вправо',
};
export const defaultTeachingProfile: TeachingProfile = {
  schema:'sphere-touch-keymap-v1',mode:'stick',stick_x:15,stick_y:82,radius:12,action_x:92,action_y:88,
  vehicle:{forward:{x:94,y:78},reverse:{x:81,y:78},left:{x:8,y:82},right:{x:24,y:82}},calibration:null,
};
type Geometry = { width: number; height: number };
export function fromPercent(point: PercentPoint, geometry: Geometry): TeachingPoint {
  return {x:Math.round(point.x*(geometry.width-1)/100),y:Math.round(point.y*(geometry.height-1)/100)};
}
export function calibrated(profile: TeachingProfile, geometry: Geometry, target: CalibrationTarget): boolean {
  return profile.calibration?.width===geometry.width && profile.calibration.height===geometry.height && profile.calibration.buttons.includes(target);
}
export function calibrateProfile(profile: TeachingProfile, geometry: Geometry, target: CalibrationTarget, point: TeachingPoint): TeachingProfile {
  const x=point.x/Math.max(1,geometry.width-1)*100,y=point.y/Math.max(1,geometry.height-1)*100;
  const buttons=profile.calibration?.width===geometry.width&&profile.calibration.height===geometry.height?profile.calibration.buttons:[];
  const calibration={...geometry,buttons:[...new Set([...buttons,target])]};
  return target==='look'?{...profile,look:{x,y},calibration}:target==='stick'?{...profile,stick_x:x,stick_y:y,calibration}:target==='action'?{...profile,action_x:x,action_y:y,calibration}
    :{...profile,vehicle:{...profile.vehicle,[target]:{x,y}},calibration};
}
export function profileIssue(profile: TeachingProfile, geometry: Geometry): string | null {
  const keysIssue=keyBindingIssue(teachingKeys(profile));if(keysIssue)return keysIssue;
  if(profile.mode==='stick') {
    const center=fromPercent({x:profile.stick_x,y:profile.stick_y},geometry),radius=profile.radius/100*Math.min(geometry.width,geometry.height);
    return center.x-radius<0||center.y-radius<0||center.x+radius>=geometry.width||center.y+radius>=geometry.height?'Зона стика выходит за экран. Уменьшите радиус или измените центр.':null;
  }
  if(vehicleButtons.some(button=>!calibrated(profile,geometry,button)))return 'Укажите четыре кнопки транспорта на текущем экране. После смены разрешения калибровку нужно подтвердить заново.';
  const points=vehicleButtons.map(button=>fromPercent(profile.vehicle[button],geometry));
  if(points.some((point,index)=>points.slice(0,index).some(other=>point.x===other.x&&point.y===other.y)))return 'Кнопки транспорта настроены в одну точку. Проверьте газ, тормоз и повороты.';
  return null;
}
/** A repeated desired state is a hold. The contact driver suppresses duplicate edges. */
export function movementTargets(keys: ReadonlySet<string>, profile: TeachingProfile, geometry: Geometry): {stick?:TeachingPoint; primary:TeachingPoint|null; secondary?:TeachingPoint|null} {
  keys=canonicalKeys(keys,profile);
  if(profile.mode==='stick') {
    const stick=fromPercent({x:profile.stick_x,y:profile.stick_y},geometry);
    return {stick,primary:stickPoint(keys,stick,profile.radius*Math.min(geometry.width,geometry.height)/100,keys.has('ShiftLeft')||keys.has('ShiftRight'))};
  }
  const forward=Number(keys.has('KeyW'))-Number(keys.has('KeyS')),turn=Number(keys.has('KeyD'))-Number(keys.has('KeyA'));
  return {primary:forward?fromPercent(profile.vehicle[forward>0?'forward':'reverse'],geometry):null,
    secondary:turn?fromPercent(profile.vehicle[turn>0?'right':'left'],geometry):null};
}
export const cameraContact = (profile: TeachingProfile): 1|2 => profile.mode==='vehicle_buttons'?2:1;
