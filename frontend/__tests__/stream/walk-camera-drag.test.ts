import {WalkCameraDrag} from '@/src/features/stream/walkCameraDrag';
const rotation=(y:number)=>[Math.cos(y),0,-Math.sin(y),0,1,0,Math.sin(y),0,Math.cos(y)];
test.each([12,-12,3])('held camera finger follows fresh geometric feedback with gain %s',gain=>{
  const servo=new WalkCameraDrag();let heading=0,offset=0,recognized=false,downs=0,ups=0,aligned=false;
  for(let i=0;i<240;i++){
    const now=1000+i*50,yaw=1.2-heading;
    const step=servo.update({rotation:rotation(heading),target:[Math.sin(yaw),0,Math.cos(yaw)],sequence:i+1,capturedAt:now,now,canStroke:true});
    expect(step.failed).toBe(false);
    if(step.action){
      if(step.action==='down'){offset=0;recognized=false;downs++;}
      if(step.action==='move'){
        const next=step.fraction!;let delta=next-offset;
        if(!recognized){delta=Math.abs(next)>.012?next-Math.sign(next)*.012:0;recognized=Math.abs(next)>.012;}
        heading+=delta*gain;offset=next;
      }
      if(step.action==='up')ups++;
      servo.finishStroke(true,now+5);
    }
    if(!step.hold){aligned=true;break;}
  }
  expect(aligned).toBe(true);expect(Math.abs(1.2-heading)).toBeLessThan(.20);
  expect(downs).toBeLessThanOrEqual(3);expect(ups).toBe(downs);
});
test('a quiet early response holds the same camera finger and retries without UP/DOWN',()=>{
  const servo=new WalkCameraDrag(),view={rotation:rotation(0),target:[.3,0,1],sequence:1,capturedAt:1000,now:1000,canStroke:true};
  expect(servo.update(view).action).toBe('down');servo.finishStroke(true,1005);
  expect(servo.update({...view,sequence:2,capturedAt:1050,now:1050}).action).toBe('move');servo.finishStroke(true,1055);
  const early=servo.update({...view,sequence:3,capturedAt:1150,now:1150});
  expect(early.action).toBeUndefined();expect(early.failed).toBe(false);
  const later=servo.update({...view,sequence:4,capturedAt:1500,now:1500});
  expect(later.action).toBe('move');expect(later.fraction).toBeGreaterThan(.018);
});
test('native uncertainty or stale geometry never generates another camera movement',()=>{
  const servo=new WalkCameraDrag(),view={rotation:rotation(0),target:[.3,0,1],sequence:1,capturedAt:1000,now:1000,canStroke:true};
  servo.update(view);servo.finishStroke(false,1005);
  expect(servo.update({...view,sequence:2,now:1050}).failed).toBe(true);
  expect(new WalkCameraDrag().update({...view,now:1300}).reason).toBe('walk_camera_pose_unavailable');
});
test('crossing a larger touch-slop threshold does not lock later corrections into large oscillating steps',()=>{
  const servo=new WalkCameraDrag();let heading=0,offset=0,recognized=false,aligned=false;
  for(let i=0;i<150;i++){
    const now=1000+i*50,yaw=.6-heading,step=servo.update({rotation:rotation(heading),target:[Math.sin(yaw),0,Math.cos(yaw)],sequence:i+1,capturedAt:now,now,canStroke:true});
    expect(step.failed).toBe(false);
    if(step.action){
      if(step.action==='down'){offset=0;recognized=false;}
      if(step.action==='move'){
        const next=step.fraction!;let delta=next-offset;
        if(!recognized){delta=Math.abs(next)>.03?next-Math.sign(next)*.03:0;recognized=Math.abs(next)>.03;}
        heading+=delta*12;offset=next;
      }
      servo.finishStroke(true,now+5);
    }
    if(!step.hold){aligned=true;break;}
  }
  expect(aligned).toBe(true);expect(servo.snapshot().minimumFraction).toBeLessThan(.012);
});
