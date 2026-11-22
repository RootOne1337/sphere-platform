import {act,render,screen} from '@testing-library/react';
import {WalkLivePreview,type WalkPreviewFrame} from '@/src/features/stream/WalkLivePreview';
jest.mock('next/image',()=>({__esModule:true,default:({src,alt}:{src:string;alt:string})=><img src={src} alt={alt}/>}));
let decodes:{url:string;done:()=>void;fail:()=>void}[],urls:number;
const frame=(sequence:number):WalkPreviewFrame=>({blob:new Blob(['jpeg'],{type:'image/jpeg'}),sequence,capturedAt:1000,points:[[10,20],[30,40]]});
beforeEach(()=>{
  decodes=[];urls=0;jest.useFakeTimers();jest.spyOn(performance,'now').mockReturnValue(1000);
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:jest.fn(()=>`blob:frame-${++urls}`)});
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:jest.fn()});
  jest.spyOn(window,'Image').mockImplementation(()=>{
    const image={src:'',decode:()=>new Promise<void>((resolve,reject)=>{decodes.push({url:image.src,done:resolve,fail:()=>reject(Error('decode'))});})};
    return image as HTMLImageElement;
  });
});
afterEach(()=>{jest.useRealTimers();jest.restoreAllMocks();});
test('coalesces pending previews and never queues every source frame',async()=>{
  const r=render(<WalkLivePreview frame={frame(1)} active/>);
  r.rerender(<WalkLivePreview frame={frame(2)} active/>);r.rerender(<WalkLivePreview frame={frame(3)} active/>);
  expect(decodes).toHaveLength(1);
  await act(async()=>decodes[0].done());expect(decodes).toHaveLength(2);
  await act(async()=>decodes[1].done());
  expect(screen.getByAltText('Исходный кадр локализации')).toHaveAttribute('src','blob:frame-2');
  expect(URL.createObjectURL).toHaveBeenCalledTimes(2);expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:frame-1');
  r.unmount();expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:frame-2');
});
test('overlay expires and stopping cannot present an old direction as live',async()=>{
  const r=render(<WalkLivePreview frame={frame(1)} active/>);await act(async()=>decodes[0].done());
  expect(screen.getByLabelText('Направление на этом кадре')).toBeInTheDocument();
  act(()=>jest.advanceTimersByTime(251));expect(screen.queryByLabelText('Направление на этом кадре')).not.toBeInTheDocument();
  r.rerender(<WalkLivePreview frame={frame(1)} active={false}/>);
  expect(screen.queryByLabelText('Направление на этом кадре')).not.toBeInTheDocument();
});
test('failed preview decoding preserves the preceding image and revokes pending URL',async()=>{
  const r=render(<WalkLivePreview frame={frame(1)} active/>);await act(async()=>decodes[0].done());
  r.rerender(<WalkLivePreview frame={frame(2)} active/>);await act(async()=>decodes[1].fail());
  expect(screen.getByAltText('Исходный кадр локализации')).toHaveAttribute('src','blob:frame-1');
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:frame-2');
});
