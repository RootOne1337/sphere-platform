import { fireEvent, render, screen } from '@testing-library/react';
import { PointerPathPreview } from '@/src/features/scripts/studio/PointerPathPreview';

it('shows one gesture with an inspectable time axis without expanding it into nodes or sending input',()=>{
  render(<PointerPathPreview path={{schema_version:1,frame_width:960,frame_height:540,
    points:[{t_ms:0,action:0,x:100,y:200},{t_ms:3000,action:2,x:300,y:100},{t_ms:5500,action:1,x:100,y:200}]}} />);
  expect(screen.getByText('Один непрерывный жест')).toBeVisible();
  expect(screen.getByText('3 точек · 5500 мс')).toBeVisible();
  fireEvent.change(screen.getByRole('slider',{name:'Время жеста'}),{target:{value:'4000'}});
  expect(screen.getByText('4000 / 5500 мс')).toBeVisible();
  expect(screen.getByRole('img',{name:'Путь пальца от начала до отпускания'}).querySelectorAll('path')).toHaveLength(1);
});
