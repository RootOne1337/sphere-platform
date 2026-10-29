import {WalkCameraServo,horizontalCameraTurn} from '@/src/features/stream/walkCamera';
const rotation=(yaw:number)=>[Math.cos(yaw),0,-Math.sin(yaw),0,1,0,Math.sin(yaw),0,Math.cos(yaw)];
const target=(yaw:number)=>[Math.sin(yaw),0,Math.cos(yaw)];
test('relative rotation preserves direction for both camera headings',()=>{
  expect(horizontalCameraTurn(rotation(.5),rotation(.7))).toBeCloseTo(.2);
  expect(horizontalCameraTurn(rotation(-.5),rotation(-.7))).toBeCloseTo(-.2);
});
test.each([12,-12])('closed-loop feedback converges for touch gain %s without vertical input',gain=>{
  const servo=new WalkCameraServo();let heading=0,now=1000,sequence=0,pulses=0,aligned=false;
  for(let i=0;i<90;i++){
    const step=servo.update({rotation:rotation(heading),target:target(1-heading),sequence:++sequence,capturedAt:now,now,canStroke:true});
    expect(step.failed).toBe(false);
    if(step.fraction!==null){
      expect(Math.abs(step.fraction)).toBeLessThanOrEqual(.04);
      heading+=step.fraction*gain;servo.finishStroke(true,now+30);pulses++;
    }
    if(!step.hold){aligned=true;break;}
    now+=100;
  }
  expect(aligned).toBe(true);expect(Math.abs(1-heading)).toBeLessThanOrEqual(.14);
  expect(pulses).toBeGreaterThan(3);expect(servo.snapshot().gainRadiansPerShortSide).toBeCloseTo(gain);
});
test('old/pre-effect feedback never estimates camera gain',()=>{
  const servo=new WalkCameraServo();const view={rotation:rotation(0),target:target(.8),sequence:1,capturedAt:1000,now:1000,canStroke:true};
  expect(servo.update(view).fraction).toBe(.004);servo.finishStroke(true,1030);
  expect(servo.update({...view,sequence:2,capturedAt:1100,now:1100}).reason).toBe('walk_camera_waiting_feedback');
  expect(servo.snapshot().gainRadiansPerShortSide).toBeNull();
  expect(servo.update({...view,sequence:3,capturedAt:2500,now:2500}).reason).toBe('walk_camera_feedback_timeout');
});
test('camera waits for native stick release and rejects stale poses or steep pitch',()=>{
  const view={rotation:rotation(0),target:target(.8),sequence:1,capturedAt:1000,now:1000,canStroke:false};
  expect(new WalkCameraServo().update(view).fraction).toBeNull();
  expect(new WalkCameraServo().update({...view,now:1251}).failed).toBe(true);
  expect(new WalkCameraServo().update({...view,target:[0,4,1]}).reason).toBe('walk_camera_pitch_mismatch');
});
test('missing camera response is bounded and never changes into blind movement',()=>{
  const servo=new WalkCameraServo();let last;
  for(let i=0;i<18;i++){
    const now=1000+i*100;
    last=servo.update({rotation:rotation(0),target:target(.8),sequence:i+1,capturedAt:now,now,canStroke:true});
    if(last.fraction!==null)servo.finishStroke(true,now+20);
    if(last.failed)break;
  }
  expect(last?.reason).toBe('walk_camera_response_not_observed');expect(last?.hold).toBe(true);
});
test('unconfirmed input and unsent expired plans cannot acquire gain',()=>{
  const servo=new WalkCameraServo(),view={rotation:rotation(0),target:target(.8),sequence:1,capturedAt:1000,now:1000,canStroke:true};
  servo.update(view);servo.cancelUnsentStroke();expect(servo.snapshot().pulses).toBe(0);
  servo.update({...view,sequence:2});servo.finishStroke(false,1010);
  expect(servo.update({...view,sequence:3,now:1100}).reason).toBe('walk_camera_input_unconfirmed');
});
