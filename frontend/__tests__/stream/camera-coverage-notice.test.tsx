import {render,screen} from '@testing-library/react';
import {CameraCoverageNotice} from '@/src/features/stream/CameraCoverageNotice';
import {sceneCameraCoverage} from '@/src/features/stream/sceneGeometrySelection';

const measured=Array.from({length:124},(_,index)=>916830+Math.round(index*(3133350-916830)/123));
const ticks=new Set([0,...Array.from({length:906},(_,index)=>index+1),...measured,3592440]);
const cameras=measured.map((ticks_90k,index)=>({ticks_90k,center:[index,0,0]}));
const range={firstTicks:0,lastTicks:3592440,frames:1032};

test('partial camera times explicitly retain the complete source and exact missing boundaries',()=>{
  const coverage=sceneCameraCoverage(cameras,range,ticks)!;
  render(<CameraCoverageNotice coverage={coverage}/>);
  const note=screen.getByLabelText('Время исходного видео и восстановленных камер');
  expect(note).toHaveClass('min-h-28');
  expect(note).toHaveTextContent('Исходное видео целиком: 0.000–39.916 с · кадров: 1032');
  expect(note).toHaveTextContent('Камеры в интервале 10.187–34.815 с · ракурсов: 124');
  expect(note).toHaveTextContent('Начало и конец видео сохранены; положения камер на этих участках ещё не восстановлены: 0.000–10.187 с; 34.815–39.916 с.');
  expect(note).toHaveTextContent('это не оценка точности геометрии');
  expect(note).not.toHaveTextContent('209');
  expect(screen.queryByRole('button')).not.toBeInTheDocument();expect(screen.queryByRole('slider')).not.toBeInTheDocument();
});

test('internal camera gaps remain unpainted and exact ranges are available without claiming missing video',()=>{
  const sourceTicks=new Set([0,45000,90000,450000,495000,540000]);
  const view=sceneCameraCoverage([0,90000,450000,540000].map(ticks_90k=>({ticks_90k,center:[0,0,0]})),{firstTicks:0,lastTicks:540000,frames:6},sourceTicks)!;
  render(<CameraCoverageNotice coverage={view}/>);
  expect(screen.getByLabelText('Временные группы восстановленных камер').children).toHaveLength(2);
  expect(screen.getByText('1.000–5.000 с')).toBeInTheDocument();
  expect(screen.getByText(/Внутренние интервалы без соседних камер/)).toHaveTextContent('1 · 4.000 с');
  expect(screen.queryByText(/Начало и конец видео сохранены/)).not.toBeInTheDocument();
});

test('unknown source range never claims that camera subset is the whole video',()=>{
  render(<CameraCoverageNotice coverage={sceneCameraCoverage(cameras,undefined,ticks)!}/>);
  expect(screen.getByText('Полный временной интервал исходного видео не подтверждён.')).toBeInTheDocument();
  expect(screen.queryByText(/Исходное видео целиком/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Ползунок видео включает всю запись/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Временные группы восстановленных камер')).not.toBeInTheDocument();
});
