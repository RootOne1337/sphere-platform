import { stickPoint, type TeachingPoint } from './teachingContacts';

export type VehicleButton = 'forward' | 'reverse' | 'left' | 'right';
export type CalibrationTarget = 'stick' | 'action' | VehicleButton;
export type PercentPoint = { x: number; y: number };
export type TeachingProfile = {
  schema: 'sphere-touch-keymap-v1';
  mode: 'stick' | 'vehicle_buttons';
  stick_x: number; stick_y: number; radius: number; action_x: number; action_y: number;
  vehicle: Record<VehicleButton, PercentPoint>;
  calibration: { width: number; height: number; buttons: CalibrationTarget[] } | null;
};
export const vehicleButtons: VehicleButton[] = ['forward','reverse','left','right'];
export const calibrationNames: Record<CalibrationTarget,string> = {
  stick:'центр стика',action:'кнопку действия',forward:'газ / вперёд',reverse:'тормоз / назад',left:'поворот влево',right:'поворот вправо',
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
  return target==='stick'?{...profile,stick_x:x,stick_y:y,calibration}:target==='action'?{...profile,action_x:x,action_y:y,calibration}
    :{...profile,vehicle:{...profile.vehicle,[target]:{x,y}},calibration};
}
export function profileIssue(profile: TeachingProfile, geometry: Geometry): string | null {
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
  if(profile.mode==='stick') {
    const stick=fromPercent({x:profile.stick_x,y:profile.stick_y},geometry);
    return {stick,primary:stickPoint(keys,stick,profile.radius*Math.min(geometry.width,geometry.height)/100,keys.has('ShiftLeft')||keys.has('ShiftRight'))};
  }
  const forward=Number(keys.has('KeyW'))-Number(keys.has('KeyS')),turn=Number(keys.has('KeyD'))-Number(keys.has('KeyA'));
  return {primary:forward?fromPercent(profile.vehicle[forward>0?'forward':'reverse'],geometry):null,
    secondary:turn?fromPercent(profile.vehicle[turn>0?'right':'left'],geometry):null};
}
export const cameraContact = (profile: TeachingProfile): 1|2 => profile.mode==='vehicle_buttons'?2:1;
