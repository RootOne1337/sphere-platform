import {readVehiclePlan,vehicleCalibrationIssue,vehicleCameraIssue,vehicleDecisionDeadline,vehicleReasonLabel,VehicleContacts,type VehiclePlan} from '@/src/features/stream/vehiclePilot';
import {blackRussiaScooterProfile,defaultWalkingProfile} from '@/src/features/stream/teachingProfileStorage';
import {calibrateProfile} from '@/src/features/stream/teachingKeymap';

const geometry={width:1920,height:1080};
const plan:VehiclePlan={schema:'sphere-vehicle-plan-v1',phase:'following',reason:'vehicle_camera_relative_pursuit',
  pedal:'throttle',steering:.2,progressFraction:.4,maxSteering:.35,maxSpeedKmh:15,maxSeconds:180,maxDecisionAgeMs:450,maxAnswerHoldMs:350,groundRoute:false,executionQualified:false,cameraBodyAssumption:true,
  targetSpeedKmh:12,observedSpeedKmh:10,speedAccepted:true,targetViewCamera:null};
test('initial acquisition is not described as losing a previously acquired vehicle pose',()=>{
  expect(vehicleReasonLabel('vehicle_confirming_position')).toBe('Ищем положение по ориентирам; педали отпущены');
  expect(vehicleReasonLabel('vehicle_confirming_position',true)).toContain('Положение потеряно');
  expect(vehicleReasonLabel('vehicle_confirming_current_position')).toContain('Три свежих подтверждения');
});
test('an out-of-corridor pose reports a pause while waiting for reentry',()=>{
  const outside:VehiclePlan={...plan,phase:'waiting',reason:'vehicle_outside_control_corridor',
    pedal:'coast',steering:0,targetSpeedKmh:null,observedSpeedKmh:null,speedAccepted:false};
  expect(readVehiclePlan(outside)).toEqual(outside);
  expect(vehicleReasonLabel(outside.reason,true)).toContain('Ждём подтверждения возврата');
});
test('following requires same-reply accepted actual speed, target speed and camera direction',()=>{
  expect(readVehiclePlan(plan)).toEqual(plan);
  for(const change of [{observedSpeedKmh:null},{targetSpeedKmh:null},{speedAccepted:false},{maxSpeedKmh:51},{targetSpeedKmh:16},
    {observedSpeedKmh:NaN},{observedSpeedKmh:351},{maxSteering:1},{steering:.351},{executionQualified:true},
    {groundRoute:true},{pedal:'reverse'},{stick:[.2,-.1]},{targetViewCamera:[Infinity,0,1]}])expect(readVehiclePlan({...plan,...change})).toBeNull();
});

test('a negotiated50kmh cap admits a50kmh target but retains integer and target bounds',()=>{
  const capped={...plan,maxSpeedKmh:50,targetSpeedKmh:50,observedSpeedKmh:49};
  expect(readVehiclePlan(capped)).toEqual(capped);
  for(const change of [{maxSpeedKmh:51},{maxSpeedKmh:50.5},{targetSpeedKmh:50.01},{maxSpeedKmh:0}])
    expect(readVehiclePlan({...capped,...change})).toBeNull();
});
test('unknown, stopped and arrived never retain throttle or steering; unknown is not fabricated zero speed',()=>{
  for(const phase of ['waiting','stopped','arrived']){
    const neutral={...plan,phase,pedal:'coast',steering:0,targetSpeedKmh:null,observedSpeedKmh:null,speedAccepted:false,targetViewCamera:null};
    expect(readVehiclePlan(neutral)).toEqual(neutral);
    expect(readVehiclePlan({...neutral,pedal:'throttle'})).toBeNull();
    expect(readVehiclePlan({...neutral,steering:.01})).toBeNull();
  }
});
test('automatic vehicle input needs explicit layout, HUD profile and matching geometry',()=>{
  expect(vehicleCalibrationIssue(defaultWalkingProfile(geometry),geometry)).not.toBeNull();
  const profile=blackRussiaScooterProfile(geometry);
  expect(vehicleCalibrationIssue(profile,geometry)).toBeNull();
  expect(vehicleCameraIssue(profile,geometry)).toBeNull();
  expect(vehicleCalibrationIssue({...profile,hudProfile:undefined},geometry)).not.toBeNull();
  expect(vehicleCalibrationIssue(profile,{width:960,height:540})).not.toBeNull();
});
test('camera or pedal calibration cannot overlap another control role',()=>{
  const profile=blackRussiaScooterProfile(geometry);
  const pedal=calibrateProfile(profile,geometry,'forward',{x:288,y:885});
  expect(vehicleCalibrationIssue(pedal,geometry)).toContain('пересекает');
  const camera=calibrateProfile(profile,geometry,'look',{x:1787,y:958});
  expect(vehicleCameraIssue(camera,geometry)).toContain('пересекает');
});
function driver(){
  const held=new Set<number>(),events:{id:number;point:{x:number;y:number}|null}[]=[];
  const control={hasContact:(id:number)=>held.has(id),set:(id:number,point:{x:number;y:number}|null)=>{events.push({id,point});if(point)held.add(id);else held.delete(id);}};
  const controller=new VehicleContacts(control,blackRussiaScooterProfile(geometry),geometry);
  return {controller,events,held};
}
test('visual tempo requires a measured rate and a nonrenewable throttle pulse',()=>{
  const visual={...plan,maxSpeedKmh:5,tempoAccepted:true,observedTempo:.12,targetTempo:.2,throttlePulseMs:120,
    targetSpeedKmh:null,observedSpeedKmh:null,speedAccepted:false};
  expect(readVehiclePlan(visual)).toEqual(visual);
  expect(readVehiclePlan({...visual,observedTempo:null})).toBeNull();
  expect(readVehiclePlan({...visual,throttlePulseMs:350})).toBeNull();
  expect(readVehiclePlan({...visual,observedSpeedKmh:2})).toBeNull();

  jest.useFakeTimers();
  try{
    const f=driver(),gas={pedal:'throttle',steering:0,throttlePulseMs:120} as const;
    const apply=(decision=gas)=>f.controller.apply(decision,performance.now(),performance.now()+250);
    apply();
    expect(f.held.has(0)).toBe(true);
    jest.advanceTimersByTime(100);
    const duringPulse={...gas};
    apply(duringPulse);
    jest.advanceTimersByTime(20);
    expect(f.held.has(0)).toBe(false);
    const duringCooldown={...gas};
    apply(duringCooldown);
    expect(f.held.has(0)).toBe(false);
    jest.advanceTimersByTime(180);
    expect(apply(duringCooldown)).toBe('coast');
    expect(f.held.has(0)).toBe(false);
    apply({...gas});
    expect(f.held.has(0)).toBe(true);
  }finally{jest.useRealTimers();}
});
test('pedal transitions release before the next button while steering remains on its calibrated horizontal axis',()=>{
  const f=driver();f.controller.apply({pedal:'throttle',steering:.3},1000,1200);
  expect(f.events[0]).toEqual({id:1,point:{x:288,y:885}});
  expect(f.events[1].point?.y).toBe(885);expect(f.events[1].point!.x).toBeGreaterThan(288);
  f.events.length=0;f.controller.apply({pedal:'brake',steering:.3},1050,1250);
  const pedal=f.events.filter(e=>e.id===0);
  expect(pedal).toEqual([{id:0,point:null},{id:0,point:{x:1581,y:957}}]);
  f.events.length=0;f.controller.apply({pedal:'coast',steering:0},1100,1300);
  expect(f.events.find(e=>e.id===1)!.point!.x).toBeGreaterThan(288);
  expect(f.events.at(-1)).toEqual({id:0,point:null});
});

test('a steady cruise pulse keeps its original deadline and drops on a cautious decision',()=>{
  jest.useFakeTimers();
  try{
    const f=driver(),cruise={pedal:'throttle',steering:0,throttlePulseMs:240} as const;
    const apply=(decision=cruise)=>f.controller.apply(decision,performance.now(),performance.now()+350);
    expect(apply()).toBe('throttle');
    jest.advanceTimersByTime(200);apply({...cruise});
    jest.advanceTimersByTime(40);
    expect(f.held.has(0)).toBe(false);
    jest.advanceTimersByTime(80);apply({...cruise});
    expect(f.held.has(0)).toBe(true);
    expect(f.controller.apply({...cruise,throttlePulseMs:120},performance.now(),performance.now()+350)).toBe('coast');
    expect(f.held.has(0)).toBe(false);
  }finally{jest.useRealTimers();}
});

test('straightening while driving ramps steering; explicit neutral still resets immediately',()=>{
  const f=driver();
  for(let at=1000;at<=1300;at+=20)f.controller.apply({pedal:'throttle',steering:.35},at,at+200);
  const before=f.events.filter(e=>e.id===1).at(-1)!.point!.x;
  f.events.length=0;f.controller.apply({pedal:'throttle',steering:0},1320,1500);
  const after=f.events.find(e=>e.id===1)!.point!.x;
  expect(after).toBeGreaterThan(288);expect(before-after).toBeLessThanOrEqual(4);
  f.controller.neutral(1340);f.events.length=0;
  f.controller.apply({pedal:'throttle',steering:.35},1360,1500);
  expect(f.events.find(e=>e.id===1)!.point!.x).toBeLessThan(288+.03*129.6);
});
test('an expired or malformed vehicle decision cannot activate a pedal',()=>{
  const f=driver();
  for(const [steering,now,until] of [[.1,1000,1000],[.1,1000,1400],[NaN,1000,1100],[.5,1000,1100]]){
    expect(()=>f.controller.apply({pedal:'throttle',steering},now,until)).toThrow();
    expect(f.events).toHaveLength(0);
  }
});
test('vehicle holds bridge 150ms computation at5Hz but never admit an old reply or unbounded hold',()=>{
  expect(vehicleDecisionDeadline(1000,1150)).toBe(1450);
  expect(vehicleDecisionDeadline(1200,1350)).toBe(1650);
  expect(vehicleDecisionDeadline(1400,1550)).toBe(1850);
  expect(vehicleDecisionDeadline(1000,1250)).toBeNull();
  expect(vehicleDecisionDeadline(1100,1099)).toBeNull();
  expect(readVehiclePlan({...plan,maxDecisionAgeMs:451})).toBeNull();
});
test('a neutral pause resets slew, so a new command starts from the actually sent neutral',()=>{
  const f=driver();f.controller.apply({pedal:'throttle',steering:.35},1000,1200);
  f.controller.apply({pedal:'throttle',steering:.35},1100,1300);f.controller.neutral(1150);
  f.events.length=0;f.controller.apply({pedal:'throttle',steering:.35},1200,1400);
  const x=f.events.find(e=>e.id===1)!.point!.x;
  expect(x).toBeLessThan(288+.1*129.6);
});
