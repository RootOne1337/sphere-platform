import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingCaptureSetup} from '@/src/features/stream/TeachingCaptureSetup';
import {api} from '@/lib/api';
jest.mock('@/lib/api',()=>({api:{post:jest.fn(),get:jest.fn()}}));
const snapshot={supported:true,protocol:1,settings:{profile:'detail',max_fps:30,max_bitrate_bps:24000000},
  active:{width:1920,height:1080,source_fps:60,codec_max_fps:60,target_fps:30,max_bitrate_bps:24000000,target_bitrate_bps:24000000,adaptation:'webrtc'}};
afterEach(()=>jest.clearAllMocks());
test('the capture preset is an explicit one-device update, not a claim of measured 30 FPS',async()=>{
  jest.mocked(api.post).mockResolvedValue({data:snapshot});
  render(<TeachingCaptureSetup deviceId="one" disabled={false} quality={null}/>);
  expect(api.post).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Съёмка · 30 FPS / 24 Мбит'}));
  await screen.findByText(/Android подтвердил 1920/);
  expect(api.post).toHaveBeenCalledWith('/streaming/one/quality',{profile:'detail',max_fps:30,max_bitrate_bps:24000000},expect.any(Object));
  expect(screen.queryByText(/фактических FPS/)).not.toBeInTheDocument();
});
test('an uncertain application disables repeat until an explicit readback succeeds',async()=>{
  jest.mocked(api.post).mockRejectedValue(Error('lost'));
  jest.mocked(api.get).mockResolvedValue({data:snapshot});
  render(<TeachingCaptureSetup deviceId="one" disabled={false} quality={null}/>);
  const preset=screen.getByRole('button',{name:'Съёмка · 30 FPS / 24 Мбит'});fireEvent.click(preset);
  await screen.findByText(/Подтверждение не получено/);expect(preset).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Проверить настройки съёмки'}));
  await waitFor(()=>expect(preset).toBeEnabled());expect(api.post).toHaveBeenCalledTimes(1);expect(api.get).toHaveBeenCalledTimes(1);
});
test('the accepted request does not hide a lower active codec limit',async()=>{
  jest.mocked(api.post).mockResolvedValue({data:{...snapshot,active:{...snapshot.active,codec_max_fps:30,max_bitrate_bps:12000000,target_bitrate_bps:8400000}}});
  render(<TeachingCaptureSetup deviceId="one" disabled={false} quality={null}/>);
  fireEvent.click(screen.getByRole('button',{name:'Съёмка · 30 FPS / 24 Мбит'}));
  await screen.findByText(/активный предел — 12\.0/);
  expect(screen.getByText('до 30 FPS')).toBeInTheDocument();
  expect(screen.getByText('8.4 Мбит/с')).toBeInTheDocument();
  expect(screen.queryByText(/фактических FPS/)).not.toBeInTheDocument();
});
test('older recordings do not inherit the stricter cadence claim',()=>{
  const quality={received_encoded_fps:30,received_bitrate_bps:9000000,max_media_gap_ms:90,
    gaps_over_200ms:0,gaps_over_500ms:0,disk_queue_high_water_bytes:0,max_disk_write_ms:1,
    cadence_30fps_confirmed:true,measured_seconds:4};
  render(<TeachingCaptureSetup deviceId="one" disabled={false} quality={quality}/>);
  expect(screen.getByText(/старая проверка ритма/)).toBeInTheDocument();
  expect(screen.queryByText(/ритм 30 FPS подтверждён по RTP/)).not.toBeInTheDocument();
});
test('current RTP quality exposes the short stalls and percentile',()=>{
  const quality={cadence_policy:'rtp-30fps-gap50-v1',received_encoded_fps:29.8,received_bitrate_bps:9000000,
    max_media_gap_ms:67,p95_media_gap_ms:34,gaps_over_50ms:1,gaps_over_100ms:0,
    gaps_over_200ms:0,gaps_over_500ms:0,disk_queue_high_water_bytes:0,max_disk_write_ms:1,
    cadence_30fps_confirmed:false,measured_seconds:4};
  render(<TeachingCaptureSetup deviceId="one" disabled={false} quality={quality}/>);
  expect(screen.getByText(/ровный ритм 30 FPS не подтверждён/)).toBeInTheDocument();
  expect(screen.getByText(/>50 мс: 1/)).toBeInTheDocument();
  expect(screen.getByText(/Интервал p95 ≤ 34 мс/)).toBeInTheDocument();
});
test('60 FPS can only be requested after source and codec report that capability',async()=>{
  jest.mocked(api.get).mockResolvedValue({data:snapshot});
  jest.mocked(api.post).mockResolvedValue({data:{...snapshot,settings:{...snapshot.settings,max_fps:60},
    active:{...snapshot.active,target_fps:60}}});
  const target=jest.fn();render(<TeachingCaptureSetup deviceId="one" disabled={false} quality={null} onConfirmedTarget={target}/>);
  const fast=screen.getByRole('button',{name:'Съёмка · 60 FPS / 24 Мбит'});expect(fast).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Проверить настройки съёмки'}));
  await waitFor(()=>expect(fast).toBeEnabled());fireEvent.click(fast);
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/streaming/one/quality',
    {profile:'detail',max_fps:60,max_bitrate_bps:24000000},expect.any(Object)));
  await waitFor(()=>expect(target).toHaveBeenLastCalledWith(60));
});
test('a 30 FPS codec never offers the 60 FPS preset',async()=>{
  jest.mocked(api.get).mockResolvedValue({data:{...snapshot,active:{...snapshot.active,codec_max_fps:30}}});
  render(<TeachingCaptureSetup deviceId="one" disabled={false} quality={null}/>);
  fireEvent.click(screen.getByRole('button',{name:'Проверить настройки съёмки'}));
  await screen.findByText('до 30 FPS');
  expect(screen.getByRole('button',{name:'Съёмка · 60 FPS / 24 Мбит'})).toBeDisabled();
});
