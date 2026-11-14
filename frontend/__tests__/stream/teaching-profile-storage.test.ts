import {defaultWalkingProfile,blackRussiaScooterProfile,loadTeachingProfile,saveTeachingProfile,teachingProfileKey} from '@/src/features/stream/teachingProfileStorage';
import {calibrateProfile,fromPercent,movementTargets,profileIssue,cameraContact} from '@/src/features/stream/teachingKeymap';
import {walkingCalibrationIssue,walkingCameraIssue} from '@/src/features/stream/walkPilot';
const g={width:1920,height:1080};
beforeEach(()=>localStorage.clear());

test.each([{width:960,height:540},{width:1920,height:1080}])('scooter preset scales pedals and separates held throttle, steering stick and camera at %j',geometry=>{
  const p=blackRussiaScooterProfile(geometry);
  expect(profileIssue(p,geometry)).toBeNull();expect(cameraContact(p)).toBe(2);
  const held=movementTargets(new Set(['KeyW','KeyD']),p,geometry);
  expect(held.primary).toEqual(fromPercent({x:93.1,y:88.7},geometry));
  expect(held.secondaryStick).toEqual(fromPercent({x:15,y:82},geometry));
  expect(held.secondary!.x).toBeGreaterThan(held.secondaryStick!.x);expect(held.secondary!.y).toBe(held.secondaryStick!.y);
  const brake=movementTargets(new Set(['KeyS','KeyA']),p,geometry);
  expect(brake.primary).toEqual(fromPercent({x:82.4,y:88.7},geometry));expect(brake.secondary!.x).toBeLessThan(brake.secondaryStick!.x);
  const opposed=movementTargets(new Set(['KeyW','KeyS','KeyA','KeyD']),p,geometry);
  expect(opposed.primary).toBeNull();expect(opposed.secondary).toBeNull();
  const key=teachingProfileKey('account','11',geometry);saveTeachingProfile(localStorage,key,p);expect(loadTeachingProfile(localStorage,key,geometry)).toEqual(p);
});

test('applying the scooter preset retains the current calibrated stick and camera',()=>{
  let current=calibrateProfile(defaultWalkingProfile(g),g,'stick',{x:400,y:800});
  current=calibrateProfile(current,g,'look',{x:1300,y:490});
  const p=blackRussiaScooterProfile(g,current);
  expect(p.stick_x).toBe(current.stick_x);expect(p.stick_y).toBe(current.stick_y);expect(p.look).toEqual(current.look);
});
test('default nonoverlapping foot stick and camera are usable without clicking calibration',()=>{
  const p=defaultWalkingProfile(g);expect(walkingCalibrationIssue(p,g)).toBeNull();expect(walkingCameraIssue(p,g)).toBeNull();
  expect(p.stick_x).toBe(15);expect(p.look).toEqual({x:65,y:50});
});
test('manual positions persist per user device and exact geometry',()=>{
  const key=teachingProfileKey('account','emulator11',g),p=calibrateProfile(defaultWalkingProfile(g),g,'stick',{x:390,y:800});
  expect(saveTeachingProfile(localStorage,key,p)).toBe(true);expect(loadTeachingProfile(localStorage,key,g)).toEqual(p);
  expect(loadTeachingProfile(localStorage,teachingProfileKey('other','emulator11',g),g)).toEqual(defaultWalkingProfile(g));
  expect(loadTeachingProfile(localStorage,key,{width:960,height:540})).toEqual(defaultWalkingProfile({width:960,height:540}));
});
test('corrupt/out-of-range stored profile and unavailable storage safely use defaults',()=>{
  for(const raw of ['null','{',JSON.stringify({...defaultWalkingProfile(g),stick_x:1000})]){
    localStorage.setItem('key',raw);expect(loadTeachingProfile(localStorage,'key',g)).toEqual(defaultWalkingProfile(g));
  }
  expect(saveTeachingProfile({setItem:()=>{throw Error('quota');}},'key',defaultWalkingProfile(g))).toBe(false);
});
