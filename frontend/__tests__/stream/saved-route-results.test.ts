import {readSavedRouteResults} from '@/src/features/stream/savedRouteResults';
import {reconstructionRequest,type ReconstructionJob} from '@/src/features/stream/reconstructionClient';
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
const source='a'.repeat(64),current='b'.repeat(32),prior={id:'c'.repeat(32),key:'d'.repeat(64)};
beforeEach(()=>jest.clearAllMocks());

test('a failed same-source prior attempt exposes its preferred diagnostic without claiming a ready map',async()=>{
  jest.mocked(reconstructionRequest).mockImplementation(async path=>({json:async()=>path.endsWith('/geometry-alternatives')?
    {preferredAlternativeId:'verified-173',alternatives:[{id:'larger',cameras:240,points:50000},{id:'verified-173',cameras:173,points:20556,label:'Сохранённая геометрия'}]}:
    {phase:'failed',error:'resource_guard',source_manifest_sha256:source,geometry_available:true,quality:{registered:144,points:9529},navigation:{phase:'not_prepared'}}}) as Response);
  const results=await readSavedRouteResults([prior],current,source,new AbortController().signal);
  expect(results).toEqual([{job:prior,kind:'diagnostic',label:'Сохранённая геометрия',cameras:173,points:20556}]);
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});

test('foreign sources are excluded before reading their alternative metadata',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'complete',source_manifest_sha256:'f'.repeat(64),geometry_available:true,navigation:{phase:'ready'}})} as Response);
  expect(await readSavedRouteResults([prior],current,source,new AbortController().signal)).toEqual([]);
  expect(reconstructionRequest).toHaveBeenCalledTimes(1);
});

test('unavailable optional alternatives keep the source-bound primary result available',async()=>{
  jest.mocked(reconstructionRequest).mockImplementation(async path=>{
    if(path.endsWith('/geometry-alternatives'))throw new Error('catalog unavailable');
    return {json:async()=>({phase:'failed',source_manifest_sha256:source,geometry_available:true,quality:{registered:144,points:9529},navigation:{phase:'not_prepared'}})} as Response;
  });
  expect(await readSavedRouteResults([prior],current,source,new AbortController().signal)).toEqual([
    {job:prior,kind:'geometry',label:'Основная геометрия',cameras:144,points:9529},
  ]);
});

test.each([null,[],{alternatives:[]},{preferredAlternativeId:{},alternatives:[{id:'saved-173',cameras:173,points:20556}]}].map(catalog=>({catalog})))('malformed optional catalog $catalog retains the verified primary',async({catalog})=>{
  jest.mocked(reconstructionRequest).mockImplementation(async path=>({json:async()=>path.endsWith('/geometry-alternatives')?catalog:
    {phase:'failed',source_manifest_sha256:source,geometry_available:true,quality:{registered:144,points:9529},navigation:{phase:'not_prepared'}}}) as Response);
  expect(await readSavedRouteResults([prior],current,source,new AbortController().signal)).toEqual([
    {job:prior,kind:'geometry',label:'Основная геометрия',cameras:144,points:9529},
  ]);
});

test('aborting a late prior-status response cannot publish a result',async()=>{
  let release:(value:unknown)=>void=()=>{};const pending=new Promise(resolve=>{release=resolve;});
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>pending} as Response);
  const abort=new AbortController(),result=readSavedRouteResults([prior],current,source,abort.signal);
  abort.abort();release({phase:'complete',source_manifest_sha256:source,geometry_available:true,navigation:{phase:'ready'}});
  await expect(result).rejects.toMatchObject({name:'AbortError'});
});

test('inspection is capped at eight attempts and two requests in flight',async()=>{
  let active=0,peak=0;
  jest.mocked(reconstructionRequest).mockImplementation(async()=>{active++;peak=Math.max(peak,active);await Promise.resolve();active--;
    return {json:async()=>({phase:'complete',source_manifest_sha256:source,geometry_available:true,navigation:{phase:'ready'}})} as Response;});
  const attempts=Array.from({length:20},(_,index)=>({id:index.toString(16).padStart(32,'0'),key:'e'.repeat(64)})) as ReconstructionJob[];
  const result=await readSavedRouteResults(attempts,current,source,new AbortController().signal);
  expect(result).toHaveLength(8);expect(reconstructionRequest).toHaveBeenCalledTimes(8);expect(peak).toBeLessThanOrEqual(2);
});
