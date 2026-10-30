import {defaultTeachingProfile,profileIssue,calibrated,type TeachingProfile,type CalibrationTarget} from './teachingKeymap';
type Geometry={width:number;height:number};
const targets:CalibrationTarget[]=['stick','look','action','forward','reverse','left','right'];
export function defaultWalkingProfile(geometry:Geometry):TeachingProfile{
  return {...defaultTeachingProfile,look:{x:65,y:50},calibration:{...geometry,buttons:['stick','look']}};
}
/** User-supplied HUD layout, stored as relative centres, bound on application. */
export function blackRussiaScooterProfile(geometry:Geometry,current?:TeachingProfile):TeachingProfile{
  const base=defaultWalkingProfile(geometry),stick=current&&calibrated(current,geometry,'stick')?current:base;
  const look=current&&calibrated(current,geometry,'look')?current.look:base.look;
  return {...base,mode:'vehicle_buttons',steering:'stick',stick_x:stick.stick_x,stick_y:stick.stick_y,radius:stick.radius,look,
    vehicle:{...base.vehicle,forward:{x:93.1,y:88.7},reverse:{x:82.4,y:88.7}},
    calibration:{...geometry,buttons:['stick','look','forward','reverse']}};
}
export function teachingProfileKey(scope:string,device:string,g:Geometry){return `sphere-keymap-v1:${scope}:${device}:${g.width}x${g.height}`;}
export function loadTeachingProfile(storage:Pick<Storage,'getItem'>,key:string,g:Geometry):TeachingProfile{
  try{
    const raw=storage.getItem(key);if(!raw||raw.length>4096)return defaultWalkingProfile(g);
    const p=JSON.parse(raw) as TeachingProfile;
    if(p.schema!=='sphere-touch-keymap-v1'||!['stick','vehicle_buttons'].includes(p.mode)||p.steering!==undefined&&p.steering!=='stick'
      ||[p.stick_x,p.stick_y,p.action_x,p.action_y,p.look?.x,p.look?.y,...Object.values(p.vehicle??{}).flatMap(v=>[v.x,v.y])].some(v=>typeof v!=='number'||!Number.isFinite(v)||v<0||v>100)
      ||!Number.isFinite(p.radius)||p.radius<1||p.radius>20||Object.keys(p.vehicle??{}).sort().join(',')!=='forward,left,reverse,right'
      ||p.calibration?.width!==g.width||p.calibration.height!==g.height||!Array.isArray(p.calibration.buttons)
      ||p.calibration.buttons.some(v=>!targets.includes(v))||profileIssue(p,g))return defaultWalkingProfile(g);
    return p;
  }catch{return defaultWalkingProfile(g);}
}
export function saveTeachingProfile(storage:Pick<Storage,'setItem'>,key:string,profile:TeachingProfile):boolean{
  try{storage.setItem(key,JSON.stringify(profile));return true;}catch{return false;}
}
