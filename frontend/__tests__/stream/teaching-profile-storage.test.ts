import {defaultWalkingProfile,loadTeachingProfile,saveTeachingProfile,teachingProfileKey} from '@/src/features/stream/teachingProfileStorage';
import {calibrateProfile} from '@/src/features/stream/teachingKeymap';
import {walkingCalibrationIssue,walkingCameraIssue} from '@/src/features/stream/walkPilot';
const g={width:1920,height:1080};
beforeEach(()=>localStorage.clear());
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
