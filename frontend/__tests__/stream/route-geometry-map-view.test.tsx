import {fireEvent,render,screen} from '@testing-library/react';
import RouteGeometryMap from '@/src/features/stream/RouteGeometryMap';

test('shows actual counts and explicitly reports gaps and unknown road scale',()=>{
  render(<RouteGeometryMap cameras={[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:45000},
    {center:[2,1,0],ticks_90k:200000}]} points={[[0,1,2,255,255,255],[1,1,1,1,1,1]]}/>);
  expect(screen.getByRole('img',{name:'Проекция опорных точек и положений камеры'})).toBeInTheDocument();
  expect(screen.getByText(/3 камер · 2 точек/)).toBeInTheDocument();
  expect(screen.getByText(/Разрывы больше секунды не соединяются: 1/)).toBeInTheDocument();
  expect(screen.getByText(/не доказывает положение дороги/)).toBeInTheDocument();
});
test('warns about the whole path without inventing an exact faulty section',()=>{
  render(<RouteGeometryMap motionWarning cameras={[{center:[0,0,0],ticks_90k:0},
    {center:[1,0,0],ticks_90k:45000}]} points={[]}/>);
  expect(screen.getByRole('status')).toHaveTextContent('точные границы ошибки не установлены');
});
test('selects only source-backed camera timestamps by pointer, keyboard or slider',()=>{
  const seek=jest.fn(),cameras=[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:45000},
    {center:[2,1,0],ticks_90k:200000}];
  const view=render(<RouteGeometryMap cameras={cameras} points={[]} selectedTicks={0} validTicks={new Set([0,200000])}
    onSeekCamera={seek} sourcePreview={<div>Исходное видео</div>}/>);
  expect(screen.getByText('Исходное видео')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:/исходный кадр 2/i})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/исходный кадр 3/i}));expect(seek).toHaveBeenLastCalledWith(200000);
  fireEvent.keyDown(screen.getByRole('button',{name:/исходный кадр 1/i}),{key:'Enter'});expect(seek).toHaveBeenLastCalledWith(0);
  fireEvent.change(screen.getByLabelText('Ракурс на схеме ориентиров'),{target:{value:'1'}});expect(seek).toHaveBeenCalledTimes(2);
  fireEvent.change(screen.getByLabelText('Ракурс на схеме ориентиров'),{target:{value:'2'}});expect(seek).toHaveBeenLastCalledWith(200000);
  view.rerender(<RouteGeometryMap cameras={cameras} points={[]} selectedTicks={100000} validTicks={new Set([0,200000])} onSeekCamera={seek}/>);
  expect(screen.getByText(/разница с текущим кадром 0.61 с/)).toBeInTheDocument();
  expect(screen.getByText(/Разрывы больше секунды не соединяются: 1/)).toBeInTheDocument();
});
test('without verified source binding map stays read-only',()=>{
  render(<RouteGeometryMap cameras={[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:9000}]} points={[]} sourcePreview={<div>Не должен появиться</div>}/>);
  expect(screen.getByText(/Связь с исходной записью не подтверждена/)).toBeInTheDocument();
  expect(screen.queryByText('Не должен появиться')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Ракурс на схеме ориентиров')).not.toBeInTheDocument();
});
test('point density can be increased without inventing more 3D points',()=>{
  const points=Array.from({length:6000},(_,i)=>[(i%50)/10,Math.floor(i/50)/10,0,255,255,255]);
  const view=render(<RouteGeometryMap cameras={[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:9000}]} points={points}/>);
  const before=view.container.querySelectorAll('svg circle').length;
  fireEvent.click(screen.getByRole('checkbox',{name:'Больше точек'}));
  const after=view.container.querySelectorAll('svg circle').length;
  expect(after).toBeGreaterThan(before);expect(after).toBeLessThanOrEqual(points.length+3);
});

test('route colors stay distinct from depth and warning and the selected camera retains its real heading',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0]]},
    {center:[0,0,1],ticks_90k:9000,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,1]]}];
  const view=render(<RouteGeometryMap cameras={cameras} points={[[0,0,2,240,120,50],[1,0,4,240,120,50]]} motionWarning selectedTicks={0}/>);
  expect(screen.getByText(/Оси первого ракурса/)).toBeInTheDocument();
  expect(screen.getByLabelText('Цвет опорных точек')).toHaveValue('depth');
  expect(screen.getByText(/Глубина вдоль взгляда/)).toBeInTheDocument();
  expect(screen.getByLabelText('Направление взгляда выбранной камеры')).toBeInTheDocument();
  expect(view.container.querySelector('line[stroke="#22d3ee"]')).toBeInTheDocument();
  expect(view.container.querySelector('line[stroke="#fbbf24"]')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Цвет опорных точек'),{target:{value:'rgb'}});
  expect(view.container.querySelector('circle[fill="rgb(240,120,50)"]')).toBeInTheDocument();
  expect(screen.queryByText(/Глубина вдоль взгляда/)).not.toBeInTheDocument();
});

test('a backwards camera turns the diagram up with independent manual rotation and reset',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0]]},
    {center:[0,0,1],ticks_90k:9000,camera_to_world:[[-1,0,0,0],[0,1,0,0],[0,0,-1,1]]}];
  render(<RouteGeometryMap cameras={cameras} points={[]} selectedTicks={9000}/>);
  const group=screen.getByLabelText('Поворот схемы');
  expect(Number(group.getAttribute('data-angle-radians'))).toBeCloseTo(Math.PI);
  fireEvent.click(screen.getByRole('button',{name:'Повернуть карту вправо на 90 градусов'}));
  expect(Number(group.getAttribute('data-angle-radians'))).toBeCloseTo(Math.PI/2);
  fireEvent.click(screen.getByRole('button',{name:'Сброс поворота'}));
  expect(Number(group.getAttribute('data-angle-radians'))).toBeCloseTo(Math.PI);
  fireEvent.change(screen.getByLabelText('Ориентация карты'),{target:{value:'reference'}});
  expect(Number(group.getAttribute('data-angle-radians'))).toBeCloseTo(0);
});
