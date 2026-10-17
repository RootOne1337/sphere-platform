import { parseInputAvailability } from '@/src/features/stream/inputAvailability';
const session='a'.repeat(32), epoch='00112233-4455-6677-8899-aabbccddeeff';
const snapshot={type:'input_availability',schema_version:1,session_id:session,capture_epoch:epoch,revision:4,state:'automation',task_id:'owned-task-1234'};
it('binds availability to the current media peer and capture without asserting native execution',()=>{
  expect(parseInputAvailability(snapshot,session,epoch)).toEqual({revision:4,state:'automation',taskId:'owned-task-1234'});
  expect(parseInputAvailability({...snapshot,state:'manual',task_id:null},session,epoch)?.state).toBe('manual');
});
it.each([
  {session_id:'b'.repeat(32)},{capture_epoch:'old'}, {revision:Number.MAX_SAFE_INTEGER+1},{revision:-1}, {revision:1.5},
  {task_id:null},{state:'manual'},{state:'ready'}, {schema_version:2},{owner:'not-an-input-owner'},
])('rejects a foreign or malformed snapshot: %j',patch=>{
  expect(parseInputAvailability({...snapshot,...patch},session,epoch)).toBeNull();
});
it('waits for the current capture binding even when the control channel arrives first',()=>{
  expect(parseInputAvailability(snapshot,session,null)).toBeNull();
});
