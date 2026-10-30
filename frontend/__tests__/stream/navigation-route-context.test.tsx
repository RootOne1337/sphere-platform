import {act,render,screen,waitFor} from '@testing-library/react';
import {webcrypto} from 'node:crypto';
import {TextDecoder,TextEncoder} from 'node:util';
import {NavigationRouteContext} from '@/src/features/stream/NavigationRouteContext';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
import {navigationReply} from '@/src/features/stream/routeNavigation';
import type {RouteSource} from '@/src/features/stream/routeSource';
jest.mock('@/src/features/stream/RecordedRouteFrame',()=>({RecordedRouteFrame:({ticks}:{ticks:number})=><div>source-frame-{ticks}</div>}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
const job={id:'a'.repeat(32),key:'b'.repeat(64)},manifestSha='c'.repeat(64);
const source={clip:'d'.repeat(32),scope:'e'.repeat(32),manifestSha,folder:{},rows:[{relative_ticks_90k:0},{relative_ticks_90k:90000}]} as RouteSource;
const data={schema:'sphere-recovered-scene-v1',source_manifest_sha256:manifestSha,
  cameras:[{center:[0,0,0],ticks_90k:0,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0]]},
    {center:[0,0,1],ticks_90k:90000,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,1]]}],points:[[0,0,3,255,255,255]]};
beforeEach(()=>{
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});Object.defineProperty(globalThis,'TextDecoder',{configurable:true,value:TextDecoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});jest.clearAllMocks();
});
test('the saved map, source frame and stream share one view while a live pin is bound to the exact geometry',async()=>{
  const raw=new TextEncoder().encode(JSON.stringify(data)),sha=Buffer.from(await webcrypto.subtle.digest('SHA-256',raw)).toString('hex');
  jest.mocked(reconstructionRequest).mockImplementation(async path=>({json:async()=>({alternatives:[]}),arrayBuffer:async()=>Uint8Array.from(raw).buffer}) as Response);
  const props={job,source,assetsReady:true,comparison:<div>live-frame</div>};
  const view=render(<NavigationRouteContext {...props} observation={null}/>);
  await screen.findByText('source-frame-0');expect(screen.getByText('live-frame')).toBeInTheDocument();
  const parsed=navigationReply({id:'s',captureEpoch:'epoch',sequence:1,jpegSha256:'f'.repeat(64),geometrySha256:sha,referenceTicks90k:90000,computeMs:10,method:'descriptor_pnp',physicalActions:0,executionQualified:false,groundRoute:false,
    pose:{state:'localized',reason:'verified',inliers:30,segment:0,progress_units:1,polyline_px:[],center:[0,0,1],rotation:[1,0,0,0,1,0,0,0,1]}},'s','epoch',1,'f'.repeat(64))!;
  const capturedAt=performance.now();view.rerender(<NavigationRouteContext {...props} observation={{reply:parsed,capturedAt,answeredAt:capturedAt+10}}/>);
  await screen.findByLabelText('Подтверждённое живое положение');await screen.findByText('source-frame-90000');
  const calls=jest.mocked(reconstructionRequest).mock.calls.length;
  view.rerender(<NavigationRouteContext {...props} job={{...job}} observation={{reply:parsed,capturedAt,answeredAt:capturedAt+10}}/>);
  await act(async()=>{await Promise.resolve();});expect(reconstructionRequest).toHaveBeenCalledTimes(calls);
  expect(screen.getByText('source-frame-90000')).toBeInTheDocument();
  view.rerender(<NavigationRouteContext {...props} observation={{reply:{...parsed,geometrySha256:'0'.repeat(64)},capturedAt,answeredAt:capturedAt+10}}/>);
  await waitFor(()=>expect(screen.queryByLabelText('Подтверждённое живое положение')).not.toBeInTheDocument());
  expect(jest.mocked(reconstructionRequest).mock.calls.every(c=>c[2]?.method!=='POST')).toBe(true);
});
test('a source mismatch never displays the unrelated map or a live pin',async()=>{
  const raw=new TextEncoder().encode(JSON.stringify({...data,source_manifest_sha256:'0'.repeat(64)}));
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({alternatives:[]}),arrayBuffer:async()=>raw.buffer} as Response);
  render(<NavigationRouteContext job={job} source={source} assetsReady observation={null} comparison={<div>live-frame</div>}/>);
  await screen.findByText(/Геометрия относится к другой записи/);
  expect(screen.queryByLabelText('Обзор ориентиров и камер')).not.toBeInTheDocument();expect(screen.getByText('live-frame')).toBeInTheDocument();
});

test('a short display gap retains only a labelled past measurement, never a fresh live pin',async()=>{
  const raw=new TextEncoder().encode(JSON.stringify(data)),sha=Buffer.from(await webcrypto.subtle.digest('SHA-256',raw)).toString('hex');
  jest.mocked(reconstructionRequest).mockImplementation(async()=>({json:async()=>({alternatives:[]}),arrayBuffer:async()=>Uint8Array.from(raw).buffer}) as Response);
  const props={job,source,assetsReady:true,busy:true};
  const view=render(<NavigationRouteContext {...props} observation={null}/>);
  await screen.findByText('source-frame-0');
  jest.useFakeTimers();
  try{
    const parsed=navigationReply({id:'s',captureEpoch:'epoch',sequence:1,jpegSha256:'f'.repeat(64),geometrySha256:sha,referenceTicks90k:90000,computeMs:10,method:'descriptor_pnp',physicalActions:0,executionQualified:false,groundRoute:false,
      pose:{state:'localized',reason:'verified',inliers:30,segment:0,progress_units:1,polyline_px:[],center:[0,0,1],rotation:[1,0,0,0,1,0,0,0,1]}},'s','epoch',1,'f'.repeat(64))!;
    const capturedAt=performance.now(),observation={reply:parsed,capturedAt,answeredAt:capturedAt+10};
    view.rerender(<NavigationRouteContext {...props} observation={observation}/>);
    expect(screen.getByLabelText('Подтверждённое живое положение')).toBeInTheDocument();
    act(()=>jest.advanceTimersByTime(260));
    expect(screen.queryByLabelText('Подтверждённое живое положение')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Последняя измеренная позиция · ожидаем обновление')).toBeInTheDocument();
    expect(screen.getByText('Обновляем подтверждение положения')).toBeInTheDocument();
    expect(screen.queryByText(/Положение сейчас не подтверждено/)).not.toBeInTheDocument();
    view.rerender(<NavigationRouteContext {...props} observation={{...observation,reply:{...parsed,geometrySha256:'0'.repeat(64)}}}/>);
    expect(screen.queryByLabelText('Последняя измеренная позиция · ожидаем обновление')).not.toBeInTheDocument();
    view.rerender(<NavigationRouteContext {...props} observation={observation}/>);
    act(()=>jest.advanceTimersByTime(750));
    expect(screen.queryByLabelText('Последняя измеренная позиция · ожидаем обновление')).not.toBeInTheDocument();
    expect(screen.getByText(/Положение сейчас не подтверждено/)).toBeInTheDocument();
    view.rerender(<NavigationRouteContext {...props} busy={false} observation={observation}/>);
    expect(screen.queryByText(/Положение сейчас не подтверждено/)).not.toBeInTheDocument();
  }finally{view.unmount();jest.useRealTimers();}
});
