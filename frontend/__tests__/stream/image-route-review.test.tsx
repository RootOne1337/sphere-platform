import React from 'react';
import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import ImageRouteReview,{ImageRouteReviewPanel,readImageRouteReview,type ImageRouteReviewData} from '@/src/features/stream/ImageRouteReview';
import {reconstructionRequest,ReconstructionResponseError} from '@/src/features/stream/reconstructionClient';
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
const manifest='a'.repeat(64),frames=new Map([[0,0],[1,45000],[2,90000],[3,180000]]);
const fixture=():ImageRouteReviewData=>({schema:'sphere-image-route-review-v1',scope:'OFFLINE_SAME_RECORDING',source_manifest_sha256:manifest,
  position_confirmed:false,arrival_confirmed:false,execution_qualified:false,reference_ticks_90k:[0,90000,180000],samples:[
    {source_index:1,ticks_90k:45000,raw_reference_ticks_90k:180000,raw_score:.9,sequence_reference_ticks_90k:null,sequence_status:'ambiguous'},
    {source_index:2,ticks_90k:90000,raw_reference_ticks_90k:90000,raw_score:.8,sequence_reference_ticks_90k:90000,sequence_status:'reference_selected'}]});
afterEach(()=>{jest.mocked(reconstructionRequest).mockReset();jest.useRealTimers();});

test('binds samples and references to this exact recording without mutating input',()=>{
  const data=fixture(),before=JSON.stringify(data);
  expect(readImageRouteReview(data,manifest,frames)).toEqual(data);
  expect(JSON.stringify(data)).toBe(before);
  expect(()=>readImageRouteReview(data,'b'.repeat(64),frames)).toThrow('binding');
  expect(()=>readImageRouteReview(data,manifest,new Map([[0,0],[1,45001],[2,90000],[3,180000]]))).toThrow('sample');
});
test.each([
  (d:ImageRouteReviewData)=>{d.execution_qualified=true as false;},
  (d:ImageRouteReviewData)=>{d.position_confirmed=true as false;},
  (d:ImageRouteReviewData)=>{d.scope='LIVE' as typeof d.scope;},
  (d:ImageRouteReviewData)=>{d.reference_ticks_90k=[0,99];},
  (d:ImageRouteReviewData)=>{d.samples[0].raw_score=NaN;},
  (d:ImageRouteReviewData)=>{d.samples[0].raw_score=true as unknown as number;},
  (d:ImageRouteReviewData)=>{d.samples[0].sequence_reference_ticks_90k=0;},
  (d:ImageRouteReviewData)=>{d.samples[1].sequence_reference_ticks_90k=null;},
  (d:ImageRouteReviewData)=>{d.samples[0].raw_reference_ticks_90k=45000;},
  (d:ImageRouteReviewData)=>{d.samples.push({...d.samples[0]});},
])('rejects mismatched, unbounded or authority-bearing data',change=>{const data=fixture();change(data);expect(()=>readImageRouteReview(data,manifest,frames)).toThrow();});

test('the denominator includes unknown queries; seeking uses actual query and reference timestamps',()=>{
  const seek=jest.fn();render(<ImageRouteReviewPanel data={fixture()} onSeek={seek}/>);
  expect(screen.getByText('Несколько похожих участков')).toBeVisible();
  expect(screen.getByRole('button',{name:'Открыть найденный ракурс'})).toBeDisabled();
  expect(screen.getAllByText('1 / 2')).not.toHaveLength(0);
  fireEvent.change(screen.getByRole('slider',{name:'Запрос сопоставления кадров'}),{target:{value:'1'}});
  expect(seek).toHaveBeenLastCalledWith(90000);
  fireEvent.click(screen.getByRole('button',{name:'Открыть найденный ракурс'}));
  expect(seek).toHaveBeenLastCalledWith(90000);
  fireEvent.change(screen.getByRole('slider'),{target:{value:'0'}});
  fireEvent.click(screen.getByRole('button',{name:'По одному кадру'}));
  fireEvent.click(screen.getByRole('button',{name:'Открыть найденный ракурс'}));
  expect(seek).toHaveBeenLastCalledWith(180000);
  fireEvent.click(screen.getByRole('button',{name:'Открыть запрос'}));
  expect(seek).toHaveBeenLastCalledWith(45000);
  expect(reconstructionRequest).not.toHaveBeenCalled();
});

test('loads a bound review automatically and ignores a late result from another job',async()=>{
  let finish!:(response:Response)=>void;
  jest.mocked(reconstructionRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const props={job:{id:'1'.repeat(32),key:'2'.repeat(64)},manifestSha:manifest,frames,refresh:0,visible:true,onSeek:jest.fn()};
  const view=render(<ImageRouteReview {...props}/>);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalledTimes(1));
  jest.mocked(reconstructionRequest).mockRejectedValueOnce(new ReconstructionResponseError(404,'image_route_review_not_found'));
  jest.mocked(reconstructionRequest).mockResolvedValueOnce({json:async()=>({phase:'failed'})} as Response);
  view.rerender(<ImageRouteReview {...props} job={{id:'3'.repeat(32),key:'4'.repeat(64)}}/>);
  await act(async()=>{finish({json:async()=>fixture()} as Response);});
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalledTimes(3));
  expect(screen.queryByLabelText('Проверка сопоставления кадров')).not.toBeInTheDocument();
});

test('refresh loads the available artifact; unavailable results do not start a task',async()=>{
  jest.mocked(reconstructionRequest).mockRejectedValueOnce(new ReconstructionResponseError(404,'image_route_review_not_found'));
  jest.mocked(reconstructionRequest).mockResolvedValueOnce({json:async()=>({phase:'failed'})} as Response);
  const props={job:{id:'1'.repeat(32),key:'2'.repeat(64)},manifestSha:manifest,frames,refresh:0,visible:true,onSeek:jest.fn()};
  const view=render(<ImageRouteReview {...props}/>);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  jest.mocked(reconstructionRequest).mockResolvedValueOnce({json:async()=>fixture()} as Response);
  view.rerender(<ImageRouteReview {...props} refresh={1}/>);
  expect(await screen.findByLabelText('Проверка сопоставления кадров')).toBeVisible();
  expect(reconstructionRequest).toHaveBeenLastCalledWith(expect.stringContaining('/image-route-review'),props.job,expect.objectContaining({signal:expect.any(AbortSignal)}));
  for(const call of jest.mocked(reconstructionRequest).mock.calls)expect(call[2]?.method??'GET').toBe('GET');
});

test('an already running preparation appears automatically; polling stops on success',async()=>{
  jest.useFakeTimers();
  jest.mocked(reconstructionRequest)
    .mockRejectedValueOnce(new ReconstructionResponseError(404,'image_route_review_not_found'))
    .mockResolvedValueOnce({json:async()=>({phase:'image_route_indexing',image_route_review:{phase:'running'}})} as Response)
    .mockResolvedValueOnce({json:async()=>fixture()} as Response);
  render(<ImageRouteReview job={{id:'1'.repeat(32),key:'2'.repeat(64)}} manifestSha={manifest} frames={frames} refresh={0} visible onSeek={jest.fn()}/>);
  await act(async()=>{});
  expect(reconstructionRequest).toHaveBeenCalledTimes(2);
  await act(async()=>{jest.advanceTimersByTime(2500);});
  expect(screen.getByLabelText('Проверка сопоставления кадров')).toBeVisible();
  await act(async()=>{jest.advanceTimersByTime(10000);});
  expect(reconstructionRequest).toHaveBeenCalledTimes(3);
  for(const call of jest.mocked(reconstructionRequest).mock.calls)expect(call[2]?.method??'GET').toBe('GET');
});

test('hiding a pending review cancels polling and cannot load a retired source',async()=>{
  jest.useFakeTimers();
  jest.mocked(reconstructionRequest)
    .mockRejectedValueOnce(new ReconstructionResponseError(404,'image_route_review_not_found'))
    .mockResolvedValueOnce({json:async()=>({phase:'image_route_indexing'})} as Response);
  const props={job:{id:'1'.repeat(32),key:'2'.repeat(64)},manifestSha:manifest,frames,refresh:0,visible:true,onSeek:jest.fn()};
  const view=render(<ImageRouteReview {...props}/>);
  await act(async()=>{});
  view.rerender(<ImageRouteReview {...props} visible={false}/>);
  await act(async()=>{jest.advanceTimersByTime(10000);});
  expect(reconstructionRequest).toHaveBeenCalledTimes(2);
  expect(screen.queryByLabelText('Проверка сопоставления кадров')).not.toBeInTheDocument();
});

test('an index published between 404 and a terminal SfM status still appears automatically',async()=>{
  jest.useFakeTimers();
  jest.mocked(reconstructionRequest)
    .mockRejectedValueOnce(new ReconstructionResponseError(404,'image_route_review_not_found'))
    .mockResolvedValueOnce({json:async()=>({phase:'failed',image_route_review:{phase:'ready'}})} as Response)
    .mockResolvedValueOnce({json:async()=>fixture()} as Response);
  render(<ImageRouteReview job={{id:'1'.repeat(32),key:'2'.repeat(64)}} manifestSha={manifest} frames={frames} refresh={0} visible onSeek={jest.fn()}/>);
  await act(async()=>{});
  await act(async()=>{jest.advanceTimersByTime(2500);});
  expect(screen.getByLabelText('Проверка сопоставления кадров')).toBeVisible();
  expect(reconstructionRequest).toHaveBeenCalledTimes(3);
});

test('forbidden requests do not retry while transient read failures retry within a bounded window',async()=>{
  jest.useFakeTimers();
  const props={job:{id:'1'.repeat(32),key:'2'.repeat(64)},manifestSha:manifest,frames,refresh:0,visible:true,onSeek:jest.fn()};
  jest.mocked(reconstructionRequest).mockRejectedValue(new ReconstructionResponseError(403,'job_capability_required'));
  const view=render(<ImageRouteReview {...props}/>);
  await act(async()=>{});
  await act(async()=>{jest.advanceTimersByTime(5000);});
  expect(reconstructionRequest).toHaveBeenCalledTimes(1);
  jest.mocked(reconstructionRequest).mockRejectedValue(new TypeError('network'));
  view.rerender(<ImageRouteReview {...props} refresh={1}/>);
  await act(async()=>{});
  await act(async()=>{jest.advanceTimersByTime(2500);});
  expect(reconstructionRequest).toHaveBeenCalledTimes(3);
  await act(async()=>{jest.advanceTimersByTime(210000);});
  const count=jest.mocked(reconstructionRequest).mock.calls.length;
  await act(async()=>{jest.advanceTimersByTime(10000);});
  expect(reconstructionRequest).toHaveBeenCalledTimes(count);
});
