/** @jest-environment node */
import {reconstructionFiles,reconstructionRequest,terminalReconstruction,uploadReconstruction} from '@/src/features/stream/reconstructionClient';
const job={id:'a'.repeat(32),key:'b'.repeat(64)};
afterEach(()=>jest.restoreAllMocks());

test('quality review ends processing without claiming a successful reconstruction',()=>{
  expect(terminalReconstruction({phase:'quality_rejected'})).toBe(true);
  expect(terminalReconstruction({phase:'review_required'})).toBe(true);
  expect(terminalReconstruction({phase:'partial_scene'})).toBe(true);
  expect(terminalReconstruction({phase:'evaluating'})).toBe(false);
  expect(terminalReconstruction({phase:'sparse_complete',navigation:{phase:'pending_auto_prepare'}})).toBe(false);
  expect(terminalReconstruction({phase:'sparse_complete',navigation:{phase:'features'}})).toBe(false);
  expect(terminalReconstruction({phase:'sparse_complete',navigation:{phase:'ready'}})).toBe(true);
});

function source(){
  const files=Object.fromEntries(reconstructionFiles.map(name=>[name,new File([new Uint8Array(name==='video.h264'?2*1048576+7:20)],name)]));
  for(const file of Object.values(files))file.arrayBuffer=async()=>{throw Error('whole_file_read_forbidden');};
  return {files,folder:{getFileHandle:async(name:string)=>({getFile:async()=>files[name]})} as unknown as FileSystemDirectoryHandle};
}
test('local capability is explicit and cookies are excluded',async()=>{
  const fetcher=jest.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}'));
  await reconstructionRequest('/jobs/'+job.id,job);
  const [url,options]=fetcher.mock.calls[0];
  expect(url).toBe('http://127.0.0.1:3342/jobs/'+job.id);
  expect(options?.credentials).toBe('omit');
  const headers=options?.headers as Headers;expect(headers.get('X-Job-Key')).toBe(job.key);expect(headers.has('Authorization')).toBe(false);
});
test('resumes at confirmed offsets and streams chunks no larger than 1 MiB',async()=>{
  const {folder}=source();const sizes:number[]=[];const offsets=Object.fromEntries(reconstructionFiles.map(name=>[name,name==='video.h264'?1048576:20]));
  jest.spyOn(globalThis,'fetch').mockImplementation(async(url,options)=>{
    if(String(url).endsWith('/offsets'))return Response.json(offsets);
    const body=options!.body as Blob,offset=Number((options!.headers as Headers).get('X-Upload-Offset'));sizes.push(body.size);
    return Response.json({offset:offset+body.size});
  });
  const progress=jest.fn();await uploadReconstruction(folder,job,progress,new AbortController().signal);
  expect(sizes).toEqual([1048576,7]);
  const [done,total]=progress.mock.calls.at(-1)!;expect(done).toBe(total);
});
test('ambiguous chunk failure is not automatically repeated',async()=>{
  const {folder}=source();const fetcher=jest.spyOn(globalThis,'fetch').mockImplementation(async(_url,options)=>{
    if(options?.method==='PUT')throw Error('network_result_unknown');
    return Response.json(Object.fromEntries(reconstructionFiles.map(name=>[name,0])));
  });
  await expect(uploadReconstruction(folder,job,()=>{},new AbortController().signal)).rejects.toThrow('network_result_unknown');
  expect(fetcher).toHaveBeenCalledTimes(2);
});
test('invalid worker offset prevents all writes',async()=>{
  const {folder}=source();const fetcher=jest.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({'manifest.json':-1}));
  await expect(uploadReconstruction(folder,job,()=>{},new AbortController().signal)).rejects.toThrow('invalid_worker_offset');
  expect(fetcher).toHaveBeenCalledTimes(1);
});
