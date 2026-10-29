import {calibrateProfile,defaultTeachingProfile} from '@/src/features/stream/teachingKeymap';
import {readWalkPlan,walkingCalibrationIssue,walkingCameraIssue,walkingStickTarget,WalkStickSlew} from '@/src/features/stream/walkPilot';
import {walkCameraInputSummary,walkInputSummary} from '@/src/features/stream/walkRunDiagnostics';
import type {TeachingInput} from '@/src/features/stream/teachingContacts';
const geometry={width:960,height:540};
const profile=calibrateProfile(defaultTeachingProfile,geometry,'stick',{x:150,y:400});
test('walking ramps up from the actual neutral vector after a delivery pause',()=>{
  const smooth=new WalkStickSlew();
  expect(smooth.next([0,-.35],1000)[1]).toBeCloseTo(-.06);
  expect(smooth.next([0,-.35],1050)[1]).toBeCloseTo(-.12);
  expect(smooth.next([0,0],1060)).toEqual([0,0]);
  expect(smooth.next([0,-.35],1110)[1]).toBeCloseTo(-.06);
  expect(Math.hypot(...smooth.next([0,-.35],4000))).toBeLessThanOrEqual(.180001);
});
test('native camera gesture distance and duration are separate from walking counters',()=>{
  const events:TeachingInput[]=[
    {stage:'submitted',at_ms:1000,sequence:1,gesture:4,action:0,pointer_id:1,x:700,y:200},
    {stage:'receipt',at_ms:1145,sequence:6,gesture:4,action:1,pointer_id:1,x:720,y:200,outcome:'applied'},
  ];
  expect(walkInputSummary(events)).toEqual({submitted:0,applied:0});
  expect(walkCameraInputSummary(events)).toEqual({strokesSubmitted:1,strokesApplied:1,movesApplied:0,lastDistancePx:20,lastDurationMs:145});
});
const plan={schema:'sphere-walk-plan-v1',phase:'following',reason:'walk_camera_relative_pursuit',stick:[.1,-.2],
  progressFraction:.3,maxStick:.35,maxSeconds:60,groundRoute:false,executionQualified:false,cameraBodyAssumption:true};
test('camera origin requires current geometry, edge clearance and separation from the movement stick',()=>{
  expect(walkingCameraIssue(profile,geometry)).toMatch(/Укажите/);
  const configured=calibrateProfile(profile,geometry,'look',{x:700,y:200});
  expect(walkingCameraIssue(configured,geometry)).toBeNull();
  expect(walkingCameraIssue(configured,{width:1920,height:1080})).toMatch(/Укажите/);
  expect(walkingCameraIssue(calibrateProfile(profile,geometry,'look',{x:1,y:100}),geometry)).toMatch(/краю/);
  expect(walkingCameraIssue(calibrateProfile(profile,geometry,'look',{x:150,y:400}),geometry)).toMatch(/пересекает/);
});
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
