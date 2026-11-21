import {WalkRunDiagnostics,boundedWalkSummary} from '@/src/features/stream/walkRunDiagnostics';

test('stage totals retain early slow frames after the detailed tail rolls over',()=>{
  const d=new WalkRunDiagnostics(1000);d.add('jpeg',1001,{durationMs:400,ageMs:410});
  for(let i=0;i<400;i++)d.add('jpeg',1002+i,{durationMs:5});
  expect(d.snapshot()).toHaveLength(256);
  expect(d.summary().jpeg).toEqual({count:401,durationMs:2400,maxDurationMs:400,maxAgeMs:410});
});

test('bounded scalar upload keeps the final failure and native closure without mutating full browser data',()=>{
  const observations=Array.from({length:600},(_,i)=>({i,reason:'x'.repeat(1500)}));
  const body={observationCount:600,observations,nativeInputs:[{stage:'closed'}]};
  const summary=boundedWalkSummary(body);
  expect(new Blob([JSON.stringify(summary)]).size).toBeLessThanOrEqual(480*1024);
  expect(summary.observations.at(-1)).toEqual(observations.at(-1));expect(summary.observationCount).toBe(600);
  expect(body.observations).toHaveLength(600);expect(summary.nativeInputs).toEqual([{stage:'closed'}]);
});

test('report reduction retains intermittent UNKNOWNs instead of sampling only alternating successes',()=>{
  const observations=Array.from({length:600},(_,i)=>({i,state:i%2?'waiting':'following',poseState:i%2?'unknown':'localized',reason:'x'.repeat(900)}));
  const result=boundedWalkSummary({observations,nativeInputs:[]});
  expect(new Blob([JSON.stringify(result)]).size).toBeLessThanOrEqual(480*1024);
  expect(result.observations.filter(r=>r.poseState==='unknown')).toHaveLength(300);
  expect(result.observations.at(-1)?.i).toBe(599);expect(observations).toHaveLength(600);
});
