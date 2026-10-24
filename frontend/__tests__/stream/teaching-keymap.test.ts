import { calibrated, calibrateProfile, defaultTeachingProfile, fromPercent, movementTargets, profileIssue, vehicleButtons, type TeachingProfile } from '@/src/features/stream/teachingKeymap';
const geometry={width:960,height:540};
function vehicle():TeachingProfile {
  let profile:TeachingProfile={...defaultTeachingProfile,mode:'vehicle_buttons'};
  vehicleButtons.forEach((button,index)=>{profile=calibrateProfile(profile,geometry,button,{x:100+index*100,y:450});});
  return profile;
}
test('a vehicle is never driven using unconfirmed example coordinates or another resolution',()=>{
  expect(profileIssue({...defaultTeachingProfile,mode:'vehicle_buttons'},geometry)).not.toBeNull();
  const profile=vehicle();expect(profileIssue(profile,geometry)).toBeNull();
  expect(profileIssue(profile,{width:1920,height:1080})).not.toBeNull();
});
test('calibration round-trips the last pixel and every actual Android coordinate',()=>{
  for(const point of [{x:0,y:0},{x:959,y:539},{x:732,y:418}]){
    const profile=calibrateProfile(defaultTeachingProfile,geometry,'forward',point);
    expect(fromPercent(profile.vehicle.forward,geometry)).toEqual(point);
  }
});
test('held throttle and steering are independent targets, opposite keys release instead of oscillating',()=>{
  const profile=vehicle(),keys=new Set(['KeyW','KeyD']);
  expect(movementTargets(keys,profile,geometry)).toEqual({primary:{x:100,y:450},secondary:{x:400,y:450}});
  keys.add('KeyS');keys.add('KeyA');expect(movementTargets(keys,profile,geometry)).toEqual({primary:null,secondary:null});
  keys.delete('KeyW');keys.delete('KeyD');expect(movementTargets(keys,profile,geometry)).toEqual({primary:{x:200,y:450},secondary:{x:300,y:450}});
});
test('action calibration is optional for driving, duplicate movement buttons are rejected',()=>{
  let profile=vehicle();expect(calibrated(profile,geometry,'action')).toBe(false);expect(profileIssue(profile,geometry)).toBeNull();
  profile=calibrateProfile(profile,geometry,'reverse',{x:100,y:450});expect(profileIssue(profile,geometry)).toContain('одну точку');
});
