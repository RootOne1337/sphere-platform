import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import ReferenceComparison from '@/src/features/stream/ReferenceComparison';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
jest.mock('@/src/features/stream/reconstructionClient',()=>({reconstructionRequest:jest.fn()}));
const job={id:'a'.repeat(32),key:'b'.repeat(64)};
beforeEach(()=>{
  jest.clearAllMocks();URL.createObjectURL=jest.fn(()=> 'blob:comparison');URL.revokeObjectURL=jest.fn();
  (reconstructionRequest as jest.Mock).mockResolvedValue({blob:async()=>new Blob(['png'])});
});
test('a legacy completed file does not claim verified reconstruction',()=>{
  render(<ReferenceComparison job={job} appearance={{state:'unverified'}}/>);
  expect(screen.getByText(/Качество этого результата ещё не проверено/)).toBeVisible();
  expect(reconstructionRequest).not.toHaveBeenCalled();
});
test('rejected scenes show their matching source pair and revoke image URLs',async()=>{
  const views=[{image:'00000000.png',psnr:13,ssim:.58},{image:'00000060.png',psnr:20,ssim:.7}];
  const view=render(<ReferenceComparison job={job} appearance={{state:'rejected',views}}/>);
  await screen.findByAltText('Исходный кадр');
  expect(screen.getByText(/Качество не прошло проверку/)).toBeVisible();
  expect(reconstructionRequest).toHaveBeenCalledWith(`/jobs/${job.id}/reference/0/render`,job,expect.anything());
  fireEvent.change(screen.getByLabelText('Кадр сравнения'),{target:{value:'1'}});
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalledWith(`/jobs/${job.id}/reference/1/source`,job,expect.anything()));
  await screen.findByAltText('Рендер реконструкции');view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(4);
});
