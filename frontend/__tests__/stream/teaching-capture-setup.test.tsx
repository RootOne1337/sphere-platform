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
