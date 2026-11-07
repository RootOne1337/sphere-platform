/** @jest-environment node */
import {TeachingQueueController,runTeachingProcessingQueue,type QueueRecording,type TeachingQueueSnapshot} from '@/src/features/stream/teachingQueue';
import {ReconstructionResponseError,type ReconstructionJob,type ReconstructionState} from '@/src/features/stream/reconstructionClient';

const scope='a'.repeat(32),clip=(n:number)=>n.toString(16).padStart(32,'0');
const record=(n=1,options:Partial<QueueRecording>={}):QueueRecording=>({id:clip(n),createdAt:n,complete:true,manifestSha:'b'.repeat(64),sourceState:'saved',folder:{} as FileSystemDirectoryHandle,prepareAfterRecording:true,hudHidden:false,...options});
const job=(n=1):ReconstructionJob=>({id:(n+100).toString(16).padStart(32,'0'),key:'d'.repeat(64),creation:{mask:'game',steps:30000,prepare_route:true,route_only:true}});
const response=(state:ReconstructionState)=>({json:async()=>({...(state.phase==='uploading'?{}:{source_manifest_sha256:'b'.repeat(64)}),...state})}) as Response;
function locks(){
  const owned=new Set<string>();
  const request=jest.fn(async(name:string,options:unknown,body?:(lock:object|null)=>Promise<unknown>)=>{
    const callback=(typeof options==='function'?options:body) as (lock:object|null)=>Promise<unknown>;
    if(owned.has(name))return callback(null);
    owned.add(name);try{return await callback({name});}finally{owned.delete(name);}
  });
  return {request} as unknown as LockManager;
}
function setup(records=[record()],overrides:Record<string,unknown>={}){
  const abort=new AbortController(),saved=new Map<FileSystemDirectoryHandle,ReconstructionJob>(),states=new Map<string,ReconstructionState>(),snapshots:TeachingQueueSnapshot[]=[];
  const requests:{path:string;jobId?:string;method?:string;body?:string}[]=[];
  const dependencies={
    readLink:jest.fn(async(folder:FileSystemDirectoryHandle)=>saved.get(folder)??null),
    listLinks:jest.fn(async(folder:FileSystemDirectoryHandle)=>{const value=saved.get(folder);return value?[value]:[];}),
    ensureLink:jest.fn(async(folder:FileSystemDirectoryHandle,_clip:string,_mask:string,candidate?:ReconstructionJob)=>{if(!candidate)throw Error('candidate_required');saved.set(folder,candidate);return candidate;}),
    stopped:jest.fn(async()=>false),stop:jest.fn(async()=>{}),now:()=>1000,locks:locks(),
    upload:jest.fn(async(_folder:FileSystemDirectoryHandle,_job:ReconstructionJob,_progress:(bytes:number,total:number)=>void,_signal:AbortSignal)=>{}),
    request:jest.fn(async(path:string,bound:ReconstructionJob|null,init?:RequestInit)=>{
      requests.push({path,jobId:bound?.id,method:init?.method,body:typeof init?.body==='string'?init.body:undefined});
      if(path==='/jobs'){
        const value=JSON.parse(String(init?.body));states.set(value.id,{phase:'uploading'});return response({phase:'uploading'});
      }
      if(path.endsWith('/start')){states.set(bound!.id,{phase:'matching'});return response({phase:'matching'});}
      const state=states.get(bound!.id);if(!state)throw new ReconstructionResponseError(404,'job_not_found');return response(state);
    }),...overrides,
  };
  const queue=new TeachingQueueController(scope,abort.signal,value=>snapshots.push(value),dependencies);
  return {queue,abort,saved,states,snapshots,requests,dependencies,records};
}
test('reload with no selected clip recovers the recorded intent and processes two records FIFO, one at a time',async()=>{
  const first=record(1),second=record(2),test=setup([second,first]);
  await test.queue.cycle(test.records);
  expect(test.dependencies.ensureLink.mock.calls.map(call=>call[1])).toEqual([first.id]);
  expect(test.requests.filter(item=>item.path==='/jobs')).toHaveLength(1);
  expect(test.snapshots.at(-1)).toMatchObject({scope,activeClip:first.id,items:expect.arrayContaining([{clip:second.id,phase:'waiting',updatedAt:1000}])});
  const firstJob=test.saved.get(first.folder)!;test.states.set(firstJob.id,{phase:'sparse_complete',navigation:{phase:'ready'}});
  await test.queue.cycle(test.records);
  expect(test.dependencies.ensureLink.mock.calls.map(call=>call[1])).toEqual([first.id,second.id]);
  expect(test.requests.filter(item=>item.path.endsWith('/start'))).toHaveLength(2);
  expect(test.snapshots.at(-1)?.activeClip).toBe(second.id);
  expect(JSON.stringify(test.snapshots)).not.toContain(firstJob.key);
});
test.each<[Partial<QueueRecording>,string]>([
  [{hudHidden:true,hudHiddenView:'first_person'},'none'],
  [{hudHidden:true,hudHiddenView:'third_person'},'avatar'],
  [{hudHidden:true},'avatar'],
  [{hudHidden:false,hudHiddenView:'first_person'},'game'],
])('the first automatic job uses the sealed recording mask preference %j',async(options,mask)=>{
  const source=record(1,options),test=setup([source]);
  await test.queue.cycle(test.records);
  expect(test.saved.get(source.folder)?.creation?.mask).toBe(mask);
  const creates=test.requests.filter(item=>item.path==='/jobs');
  expect(creates).toHaveLength(1);
  expect(JSON.parse(creates[0].body!).mask).toBe(mask);
});
test('a durable manual creation is recovered without retrofitting consent onto legacy recordings',async()=>{
  const durable=record(1,{prepareAfterRecording:false}),legacy=record(2,{prepareAfterRecording:false}),test=setup([durable,legacy]);
  test.saved.set(durable.folder,job());test.states.set(job().id,{phase:'matching'});
  await test.queue.cycle(test.records);
  expect(test.requests[0].jobId).toBe(job().id);expect(test.dependencies.ensureLink).not.toHaveBeenCalled();
  test.states.set(job().id,{phase:'sparse_complete',navigation:{phase:'ready'}});
  await test.queue.cycle(test.records);expect(test.requests.every(item=>item.jobId===job().id)).toBe(true);
});
test('a missing current pointer recovers its sole archived durable creation without recorded auto consent',async()=>{
  const test=setup([record(1,{prepareAfterRecording:false})]);
  test.dependencies.readLink.mockResolvedValue(null);test.dependencies.listLinks.mockResolvedValue([job()]);test.states.set(job().id,{phase:'matching'});
  await test.queue.cycle(test.records);expect(test.requests[0].jobId).toBe(job().id);expect(test.dependencies.ensureLink).not.toHaveBeenCalled();
});
test('ambiguous archived attempts never select one or allocate a replacement',async()=>{
  const test=setup();test.dependencies.listLinks.mockResolvedValue([job(1),job(2)]);
  await test.queue.cycle(test.records);expect(test.requests).toHaveLength(0);expect(test.dependencies.ensureLink).not.toHaveBeenCalled();
  expect(test.snapshots.at(-1)?.items[0].reason).toBe('reconstruction_attempt_selection_required');
});
test.each([
  {complete:false},{manifestSha:null},{manifestSha:'broken'},{sourceState:'unverified'},
  {sourceState:'unavailable'},{prepareAfterRecording:false},
])('unverified, incomplete and non-consenting sources never create a job: %j',async options=>{
  const test=setup([record(1,options)]);await test.queue.cycle(test.records);
  expect(test.dependencies.ensureLink).not.toHaveBeenCalled();expect(test.dependencies.request).not.toHaveBeenCalled();expect(test.dependencies.upload).not.toHaveBeenCalled();
});
test.each(['failed','cancelled','quality_rejected'])('terminal %s is read once and never retried on later scans/remount',async phase=>{
  const source=record(),test=setup([source]);test.saved.set(source.folder,job());test.states.set(job().id,{phase,error:'existing_failure'});
  await test.queue.cycle(test.records);await test.queue.cycle(test.records);
  const next=new TeachingQueueController(scope,test.abort.signal,value=>test.snapshots.push(value),test.dependencies);await next.cycle(test.records);
  expect(test.dependencies.ensureLink).not.toHaveBeenCalled();expect(test.requests.every(item=>!item.method)).toBe(true);
  expect(test.snapshots.at(-1)?.items[0].phase).toBe(phase==='cancelled'?'cancelled':'failed');
});
test('explicit durable stop is honored before any HTTP and after remount',async()=>{
  const source=record(),test=setup([source]);test.saved.set(source.folder,job());test.dependencies.stopped.mockResolvedValue(true);
  await test.queue.cycle(test.records);
  await new TeachingQueueController(scope,test.abort.signal,()=>{},test.dependencies).cycle(test.records);
  expect(test.requests).toHaveLength(0);expect(test.snapshots.at(-1)?.items[0].phase).toBe('stopped');
});
test('stop observed during upload prevents start and releases owned upload lock',async()=>{
  const source=record(),test=setup([source]);test.dependencies.upload.mockImplementation(async()=>{test.dependencies.stopped.mockResolvedValue(true);});
  await test.queue.cycle(test.records);
  expect(test.requests.some(item=>item.path.endsWith('/start'))).toBe(false);
  expect(test.snapshots.at(-1)?.items[0].phase).toBe('stopped');
});
test('metadata retries are bounded and retain exactly one candidate before any HTTP',async()=>{
  const test=setup();test.dependencies.ensureLink.mockRejectedValue(Error('write_not_confirmed'));
  await test.queue.cycle(test.records);await test.queue.cycle(test.records);await test.queue.cycle(test.records);await test.queue.cycle(test.records);
  expect(test.dependencies.ensureLink).toHaveBeenCalledTimes(3);
  expect(new Set(test.dependencies.ensureLink.mock.calls.map(call=>call[3]!.id)).size).toBe(1);
  expect(test.requests).toHaveLength(0);
  expect(test.snapshots.at(-1)?.items[0]).toMatchObject({phase:'unavailable',reason:'preparation_metadata_retry_limit'});
});
test('a transient metadata failure eventually commits the same id before upload',async()=>{
  const test=setup(),save=test.dependencies.ensureLink.getMockImplementation()!;
  test.dependencies.ensureLink.mockRejectedValueOnce(Error('write_not_confirmed')).mockImplementation(save);
  await test.queue.cycle(test.records);expect(test.requests).toHaveLength(0);
  await test.queue.cycle(test.records);
  expect(test.dependencies.ensureLink.mock.calls[0][3]).toBe(test.dependencies.ensureLink.mock.calls[1][3]);
  expect(JSON.parse(test.requests.find(item=>item.path==='/jobs')!.body!).id).toBe(test.dependencies.ensureLink.mock.calls[0][3]!.id);
});
test('service busy keeps the first durable intent and does not create a later record',async()=>{
  const first=record(1),second=record(2),test=setup([first,second]),request=test.dependencies.request.getMockImplementation()!;
  test.dependencies.request.mockImplementation(async(path,bound,init)=>{
    if(path==='/jobs')throw new ReconstructionResponseError(409,'one_active_job_only');return request(path,bound,init);
  });
  await test.queue.cycle(test.records);await test.queue.cycle(test.records);
  expect(test.dependencies.ensureLink).toHaveBeenCalledTimes(1);
  expect(test.snapshots.at(-1)?.items[0]).toMatchObject({phase:'waiting',reason:'one_active_job_only'});
  expect(test.dependencies.request.mock.calls.filter(call=>call[0]==='/jobs').map(call=>JSON.parse(String(call[2]?.body)).id)).toEqual([test.saved.get(first.folder)!.id,test.saved.get(first.folder)!.id]);
});
test('ambiguous create reads the same job and never allocates or starts another one',async()=>{
  const test=setup(),request=test.dependencies.request.getMockImplementation()!;
  test.dependencies.request.mockImplementation(async(path,bound,init)=>{
    if(path==='/jobs'){const value=JSON.parse(String(init?.body));test.states.set(value.id,{phase:'matching'});throw Error('network_timeout');}return request(path,bound,init);
  });
  await test.queue.cycle(test.records);await test.queue.cycle(test.records);
  expect(test.dependencies.request.mock.calls.filter(call=>call[0]==='/jobs')).toHaveLength(1);
  expect(test.dependencies.ensureLink).toHaveBeenCalledTimes(1);expect(test.dependencies.upload).not.toHaveBeenCalled();
});
test('a lost start response reads processing on the same id without replaying start',async()=>{
  const test=setup(),request=test.dependencies.request.getMockImplementation()!;
  test.dependencies.request.mockImplementation(async(path,bound,init)=>{
    const value=await request(path,bound,init);if(path.endsWith('/start'))throw Error('network_timeout');return value;
  });
  await test.queue.cycle(test.records);await test.queue.cycle(test.records);
  expect(test.requests.filter(item=>item.path.endsWith('/start'))).toHaveLength(1);expect(test.dependencies.upload).toHaveBeenCalledTimes(1);
});
test('aborted account lifecycle makes no late create/upload/start requests',async()=>{
  const test=setup();test.abort.abort();await expect(test.queue.cycle(test.records)).rejects.toMatchObject({name:'AbortError'});
  expect(test.requests).toHaveLength(0);
});
test('account cancellation during upload releases its own lock and sends no start/cancel intent',async()=>{
  const test=setup();test.dependencies.upload.mockImplementation(async()=>{test.abort.abort();throw new DOMException('Aborted','AbortError');});
  await expect(test.queue.cycle(test.records)).rejects.toMatchObject({name:'AbortError'});
  expect(test.requests.some(item=>item.path.endsWith('/start')||item.path.endsWith('/cancel'))).toBe(false);
  const saved=test.saved.get(test.records[0].folder)!;let available=false;
  await test.dependencies.locks.request(`sphere-reconstruction-upload-${saved.id}`,{ifAvailable:true},async lock=>{available=!!lock;});
  expect(available).toBe(true);
});
test('raw parser/network error text cannot expose a capability through the catalog snapshot',async()=>{
  const test=setup();test.dependencies.request.mockRejectedValue(Error('Invalid JSON near private key '+job().key));
  await test.queue.cycle(test.records);
  expect(test.snapshots.at(-1)?.items[0].reason).toBe('local_worker_unavailable');expect(JSON.stringify(test.snapshots)).not.toContain(job().key);
});
test('a server source binding mismatch is refused without upload, start or job replacement',async()=>{
  const source=record(),test=setup([source]);test.saved.set(source.folder,job());test.states.set(job().id,{phase:'uploading',source_manifest_sha256:'f'.repeat(64)});
  await test.queue.cycle(test.records);
  expect(test.dependencies.upload).not.toHaveBeenCalled();expect(test.dependencies.stop).toHaveBeenCalledWith(source.folder,job());
  expect(test.requests.every(item=>!item.method)).toBe(true);expect(test.snapshots.at(-1)?.items[0].reason).toBe('preparation_source_mismatch');
});
test.each([null,undefined])('a non-upload terminal response without an exact source hash cannot publish ready: %s',async sourceHash=>{
  const source=record(),test=setup([source]);test.saved.set(source.folder,job());test.states.set(job().id,{phase:'sparse_complete',source_manifest_sha256:sourceHash,navigation:{phase:'ready'}});
  await test.queue.cycle(test.records);
  expect(test.snapshots.some(snapshot=>snapshot.items.some(item=>item.phase==='ready'))).toBe(false);
  expect(test.snapshots.at(-1)?.items[0]).toMatchObject({phase:'stopped',reason:'preparation_source_mismatch'});
  expect(test.requests.every(item=>!item.method)).toBe(true);
});
test('a previously cached terminal result is rechecked when the sealed source hash changes',async()=>{
  const source=record(),test=setup([source]);test.saved.set(source.folder,job());test.states.set(job().id,{phase:'sparse_complete',source_manifest_sha256:source.manifestSha,navigation:{phase:'ready'}});
  await test.queue.cycle(test.records);expect(test.snapshots.at(-1)?.items[0].phase).toBe('ready');
  await test.queue.cycle([{...source,manifestSha:'c'.repeat(64)}]);
  expect(test.snapshots.at(-1)?.items[0]).toMatchObject({phase:'stopped',reason:'preparation_source_mismatch'});expect(test.requests).toHaveLength(2);
});
test('a failed durable stop write is reported as unconfirmed, not falsely stopped',async()=>{
  const source=record(),test=setup([source]);test.saved.set(source.folder,job());test.states.set(job().id,{phase:'uploading',source_manifest_sha256:'f'.repeat(64)});
  test.dependencies.stop.mockRejectedValue(Error('write_denied'));
  await test.queue.cycle(test.records);await test.queue.cycle(test.records);
  expect(test.snapshots.at(-1)?.items[0]).toMatchObject({phase:'unavailable',reason:'preparation_stop_not_confirmed'});expect(test.requests).toHaveLength(1);
});
test('two tabs share one account lock; another account has an independent owner',async()=>{
  const shared=locks(),first=setup(),second=setup(),other=setup();
  const wait=(_time:number,signal:AbortSignal)=>new Promise<void>(resolve=>{if(signal.aborted)resolve();else signal.addEventListener('abort',()=>resolve(),{once:true});});
  const load1=jest.fn(async()=>first.records),load2=jest.fn(async()=>second.records),loadOther=jest.fn(async()=>other.records);
  const one=runTeachingProcessingQueue(scope,first.abort.signal,load1,()=>{},{...first.dependencies,locks:shared},wait);
  for(let count=0;count<50&&!first.requests.some(item=>item.path.endsWith('/start'));count++)await Promise.resolve();
  const two=runTeachingProcessingQueue(scope,second.abort.signal,load2,()=>{},{...second.dependencies,locks:shared},wait);
  const three=runTeachingProcessingQueue('e'.repeat(32),other.abort.signal,loadOther,()=>{},{...other.dependencies,locks:shared},wait);
  for(let count=0;count<50&&!other.requests.some(item=>item.path.endsWith('/start'));count++)await Promise.resolve();
  expect(load1).toHaveBeenCalled();expect(load2).not.toHaveBeenCalled();expect(loadOther).toHaveBeenCalled();
  first.abort.abort();second.abort.abort();other.abort.abort();await Promise.all([one,two,three]);
});
