import {render,screen,waitFor} from '@testing-library/react';
import {TeachingProcessingQueue} from '@/src/features/stream/TeachingProcessingQueue';
import {readTeachingLibrary} from '@/src/features/stream/teachingLibrary';
import {runTeachingProcessingQueue} from '@/src/features/stream/teachingQueue';
jest.mock('@/src/features/stream/teachingLibrary',()=>({readTeachingLibrary:jest.fn()}));
jest.mock('@/src/features/stream/teachingQueue',()=>({runTeachingProcessingQueue:jest.fn()}));
const scope='b'.repeat(32);
beforeEach(()=>{
  jest.clearAllMocks();
  Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:jest.fn()}});
  Object.defineProperty(navigator,'locks',{configurable:true,value:{request:jest.fn()}});
  jest.mocked(readTeachingLibrary).mockResolvedValue({records:[],truncated:false});
  jest.mocked(runTeachingProcessingQueue).mockImplementation(async(_scope,_signal,load,changed)=>{await load();changed({scope,activeClip:null,items:[]});});
});
test('mount recovers the account library without any selected clip, preview or live stream',async()=>{
  const changed=jest.fn(),view=render(<TeachingProcessingQueue scope={scope} refresh={0} onSnapshot={changed}/>);
  await waitFor(()=>expect(readTeachingLibrary).toHaveBeenCalledWith(scope,{signal:expect.any(AbortSignal)}));
  expect(changed).toHaveBeenCalledWith({scope,activeClip:null,items:[]});
  const signal=jest.mocked(runTeachingProcessingQueue).mock.calls[0][1];view.unmount();expect(signal.aborted).toBe(true);
});
test('record-finalization refresh resamples the library and retires only its old HTTP lifecycle',async()=>{
  const view=render(<TeachingProcessingQueue scope={scope} refresh={0}/>);
  await waitFor(()=>expect(readTeachingLibrary).toHaveBeenCalledTimes(1));
  const previous=jest.mocked(runTeachingProcessingQueue).mock.calls[0][1];
  view.rerender(<TeachingProcessingQueue scope={scope} refresh={1}/>);
  await waitFor(()=>expect(readTeachingLibrary).toHaveBeenCalledTimes(2));expect(previous.aborted).toBe(true);
});
test('capture/pilot pause starts no background job and resumes the same account after release',async()=>{
  const view=render(<TeachingProcessingQueue scope={scope} refresh={0} paused/>);
  expect(runTeachingProcessingQueue).not.toHaveBeenCalled();expect(screen.getByRole('status')).toHaveTextContent('Уже запущенные задания не отменяются');
  view.rerender(<TeachingProcessingQueue scope={scope} refresh={0} paused={false}/>);
  await waitFor(()=>expect(runTeachingProcessingQueue).toHaveBeenCalledTimes(1));
});
test('missing OPFS or Web Locks is visible and cannot fall back to an unsafe new intent',async()=>{
  Object.defineProperty(navigator,'locks',{configurable:true,value:undefined});
  render(<TeachingProcessingQueue scope={scope} refresh={0}/>);
  expect(await screen.findByRole('status')).toHaveTextContent('новые задания не запускаются');expect(runTeachingProcessingQueue).not.toHaveBeenCalled();
});
test('library read failure is visible; an account change aborts the old owner',async()=>{
  jest.mocked(readTeachingLibrary).mockRejectedValue(Error('storage_denied'));
  const view=render(<TeachingProcessingQueue scope={scope} refresh={0}/>);
  expect(await screen.findByRole('status')).toHaveTextContent('доступ к локальному хранилищу');
  const previous=jest.mocked(runTeachingProcessingQueue).mock.calls[0][1];
  view.rerender(<TeachingProcessingQueue scope={'c'.repeat(32)} refresh={0}/>);
  expect(previous.aborted).toBe(true);
});
