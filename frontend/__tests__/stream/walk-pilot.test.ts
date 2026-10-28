import {calibrateProfile,defaultTeachingProfile} from '@/src/features/stream/teachingKeymap';
import {readWalkPlan,walkingCalibrationIssue,walkingStickTarget} from '@/src/features/stream/walkPilot';
const geometry={width:960,height:540};
const profile=calibrateProfile(defaultTeachingProfile,geometry,'stick',{x:150,y:400});
const plan={schema:'sphere-walk-plan-v1',phase:'following',reason:'walk_camera_relative_pursuit',stick:[.1,-.2],
  progressFraction:.3,maxStick:.35,maxSeconds:60,groundRoute:false,executionQualified:false,cameraBodyAssumption:true};
test('native targets require an explicit current-resolution stick calibration',()=>{
  expect(walkingCalibrationIssue(defaultTeachingProfile,geometry)).toMatch(/центр стика/);
  expect(walkingCalibrationIssue(profile,{width:1920,height:1080})).toMatch(/центр стика/);
  expect(()=>walkingStickTarget(defaultTeachingProfile,geometry,[0,-.2])).toThrow();
  const {center,target}=walkingStickTarget(profile,geometry,[.1,-.2]);
  expect(center).toEqual({x:150,y:400});expect(target!.x).toBeGreaterThan(center.x);expect(target!.y).toBeLessThan(center.y);
  expect(walkingStickTarget(profile,geometry,[0,0]).target).toBeNull();
});
test('unbounded, forged-qualified and nonneutral stopped replies cannot become input',()=>{
  expect(readWalkPlan(plan)).toEqual(plan);
  for(const changed of [{stick:[1,0]},{stick:[NaN,0]},{executionQualified:true},{phase:'stopped'},
    {progressFraction:2},{maxSeconds:120},{cameraBodyAssumption:false}])expect(readWalkPlan({...plan,...changed})).toBeNull();
  expect(readWalkPlan({...plan,phase:'stopped',stick:[0,0]})).not.toBeNull();
  expect(()=>walkingStickTarget(profile,geometry,[0,-1])).toThrow();
});
