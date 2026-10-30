import {WalkCameraDrag} from '@/src/features/stream/walkCameraDrag';
const rotation=(y:number)=>[Math.cos(y),0,-Math.sin(y),0,1,0,Math.sin(y),0,Math.cos(y)];

test.each([[5,4],[-8,6],[3,-5]])('recorded-view servo converges in yaw and pitch for signed gains %s %s',(gx,gy)=>{
  const servo=new WalkCameraDrag();let yaw=0,pitch=0,x=0,y=0,aligned=false;
  const r=(h:number,v:number)=>[Math.cos(h),0,-Math.sin(h),-Math.sin(h)*Math.sin(v),Math.cos(v),-Math.cos(h)*Math.sin(v),Math.sin(h)*Math.cos(v),Math.sin(v),Math.cos(h)*Math.cos(v)];
  const desired=[Math.sin(.6)*Math.cos(.28),Math.sin(.28),Math.cos(.6)*Math.cos(.28)];
  for(let i=0;i<150;i++){
    const now=1000+i*50,R=r(yaw,pitch),target=[0,1,2].map(k=>R.slice(k*3,k*3+3).reduce((sum,n,j)=>sum+n*desired[j],0));
    const step=servo.update({rotation:R,target,sequence:i+1,capturedAt:now,now,canStroke:true,referenceView:true});
    expect(step.failed).toBe(false);
    if(step.action){
      if(step.action==='down'){x=y=0;}
      if(step.action==='move'){yaw+=(step.fraction!-x)*gx;pitch+=((step.verticalFraction??0)-y)*gy;x=step.fraction!;y=step.verticalFraction??0;}
      servo.finishStroke(true,now+5);
    }
    if(step.reason==='walk_camera_aligned'&&!step.hold){aligned=true;break;}
  }
  expect(aligned).toBe(true);expect(Math.abs(yaw-.6)).toBeLessThan(.1);expect(Math.abs(pitch-.28)).toBeLessThan(.08);
  expect(servo.snapshot().pitchGainRadiansPerShortSide).not.toBeNull();
});
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

test('server alignment remains authoritative between entry and exit thresholds after a pause',()=>{
  const servo=new WalkCameraDrag(),base={rotation:rotation(0),target:[Math.sin(.12),0,Math.cos(.12)],sequence:1,capturedAt:1000,now:1000,canStroke:true};
  expect(servo.update(base).hold).toBe(false); // No alignment was requested.
  const step=servo.update({...base,sequence:2,alignmentRequired:true});
  expect(step.action).toBe('down');expect(step.hold).toBe(true);
  servo.finishStroke(true,1005);
  const paused=servo.pause(1100);expect(paused.action).toBe('up');servo.finishStroke(true,1105);
  const resumed=servo.update({...base,sequence:3,capturedAt:1800,now:1800,alignmentRequired:true});
  expect(resumed.hold).toBe(true);expect(resumed.reason).not.toBe('walk_camera_aligned');expect(resumed.action).toBe('down');
});

test('one early opposite response waits for settling rather than learning a wrong sign or aborting',()=>{
  const servo=new WalkCameraDrag();
  const view=(at:number,heading:number,sequence:number)=>({rotation:rotation(heading),target:[-.5,0,1],sequence,capturedAt:at,now:at,canStroke:true});
  expect(servo.update(view(1000,0,1)).action).toBe('down');servo.finishStroke(true,1005);
  expect(servo.update(view(1050,0,2)).action).toBe('move');servo.finishStroke(true,1055);
  const correcting=servo.update(view(1500,.06,3));expect(correcting.action).toBe('move');servo.finishStroke(true,1505);
  const early=servo.update(view(1650,.085,4));expect(early.failed).toBe(false);expect(early.action).toBeUndefined();
  const settled=servo.update(view(1950,-.02,5));expect(settled.failed).toBe(false);expect(servo.snapshot().gainRadiansPerShortSide).toBeGreaterThan(0);
});

test('sustained opposite response is still terminal and never produces another movement',()=>{
  const servo=new WalkCameraDrag();
  const view=(at:number,h:number,sequence:number)=>({rotation:rotation(h),target:[-.5,0,1],sequence,capturedAt:at,now:at,canStroke:true});
  servo.update(view(1000,0,1));servo.finishStroke(true,1005);servo.update(view(1050,0,2));servo.finishStroke(true,1055);
  servo.update(view(1500,.06,3));servo.finishStroke(true,1505);
  expect(servo.update(view(1950,.10,4)).failed).toBe(false);
  const rejected=servo.update(view(2050,.11,5));expect(rejected.failed).toBe(true);expect(rejected.reason).toBe('walk_camera_response_wrong_direction');expect(rejected.action).toBeUndefined();
});
