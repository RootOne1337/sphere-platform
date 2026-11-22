import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingLocalWorker} from '@/src/features/stream/TeachingLocalWorker';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';

jest.mock('@/src/features/stream/reconstructionClient',()=>({reconstructionRequest:jest.fn()}));
afterEach(()=>jest.clearAllMocks());

test('health recovery only reads status and never creates a job',async()=>{
  jest.mocked(reconstructionRequest).mockRejectedValueOnce(Error('offline'))
    .mockResolvedValue({json:async()=>({service:'sphere-reconstruction-v1',one_active_job:true})} as Response);
  render(<TeachingLocalWorker/>);
  await screen.findByText('Не подключена');
  fireEvent.click(screen.getByRole('button',{name:'Проверить'}));
  await screen.findByText('Доступна');
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalledTimes(2));
  expect(jest.mocked(reconstructionRequest).mock.calls.every(([path,job,init])=>path==='/health'&&job===null&&!init?.method)).toBe(true);
});
