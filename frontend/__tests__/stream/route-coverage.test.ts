import {routeCoverage} from '@/src/features/stream/routeCoverage';
import {activeSurface,terminalReconstruction} from '@/src/features/stream/reconstructionClient';

const cameras=Array.from({length:81},(_,i)=>({image:`${i}.png`,ticks_90k:i*45000,center:[i,0,0]}));
test('a short model is explicitly a timestamp interval, not the complete capture',()=>{
  expect(routeCoverage(cameras,cameras.slice(20,38).map(c=>c.image))).toMatchObject({first:10,last:18.5,sourceEnd:40,views:18,totalViews:81,coveredSeconds:8.5,fraction:.2125});
});
test('gaps and overlaps do not invent temporal coverage',()=>{
  expect(routeCoverage(cameras,['0.png','1.png','1.png','80.png'])?.coveredSeconds).toBe(.5);
  expect(routeCoverage(cameras,['unknown.png'])).toBeNull();
  expect(routeCoverage([],[])).toBeNull();
});
test('a new fragment keeps the global recorder gate and polling active',()=>{
  const state={phase:'complete',surface:{phase:'ready'},fragments:[{id:'a'.repeat(32),phase:'densifying'}]};
  expect(activeSurface(state)).toBe(true);expect(terminalReconstruction(state)).toBe(false);
});
