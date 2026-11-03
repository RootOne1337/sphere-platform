import {fireEvent,render,screen} from '@testing-library/react';
import RouteGeometryMap from '@/src/features/stream/RouteGeometryMap';
import {routeDisplayPoint,type RouteMapViewport} from '@/src/features/stream/routeMapViewport';
const fills:string[]=[];
beforeEach(()=>{
  fills.length=0;
  const context={setTransform:jest.fn(),clearRect:jest.fn(),globalAlpha:1,fillStyle:'',beginPath:jest.fn(),arc:jest.fn(),fill(){fills.push(String(this.fillStyle));}};
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(context as never);
});
afterEach(()=>jest.restoreAllMocks());

test('expiry hides the live pin without snapping the compass back to a different recorded heading',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0]]},
    {center:[0,0,1],ticks_90k:9000,camera_to_world:[[-1,0,0,0],[0,1,0,0],[0,0,-1,1]]}];
  const live={center:[0,0,.5],ticks_90k:0,camera_to_world:[[0,0,1,0],[0,1,0,0],[-1,0,0,.5]]};
  const view=render(<RouteGeometryMap cameras={cameras} points={[]} selectedTicks={0} liveCamera={live} orientationCamera={live}/>);
  const angle=screen.getByLabelText('Поворот схемы').getAttribute('data-angle-radians');
  view.rerender(<RouteGeometryMap cameras={cameras} points={[]} selectedTicks={9000} orientationCamera={live}/>);
  expect(screen.getByLabelText('Поворот схемы')).toHaveAttribute('data-angle-radians',angle);
  expect(screen.queryByLabelText('Подтверждённое живое положение')).not.toBeInTheDocument();
  expect(screen.getByText(/Поворот схемы сохранён/)).toBeInTheDocument();
});

test('live marker updates do not repaint thousands of depth-coloured landmarks',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0]]},
    {center:[0,0,1],ticks_90k:9000,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,1]]}];
  const points=[[0,0,2,240,120,50],[1,0,4,240,120,50]],view=render(<RouteGeometryMap cameras={cameras} points={points} liveCamera={cameras[0]}/>);
  const count=fills.length;expect(count).toBeGreaterThan(0);
  view.rerender(<RouteGeometryMap cameras={cameras} points={points} selectedTicks={9000} liveCamera={{...cameras[1],center:[.1,0,1]}}/>);
  expect(fills).toHaveLength(count);expect(screen.getByLabelText('Подтверждённое живое положение')).toBeInTheDocument();
  expect(screen.getByText(/цвет облака закреплён/)).toBeInTheDocument();
});

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
  const cloud=()=>Number(screen.getByLabelText('Облако восстановленных ориентиров').getAttribute('data-point-count'));
  const before=cloud();
  fireEvent.click(screen.getByRole('checkbox',{name:'Больше точек'}));
  const after=cloud();
  expect(after).toBeGreaterThan(before);expect(after).toBeLessThanOrEqual(points.length+3);
  expect(view.container.querySelectorAll('svg circle').length).toBeLessThan(10);
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
  expect(fills).toContain('rgb(240,120,50)');
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

test('experimental alternative is visibly unconfirmed while primary presentation remains unchanged',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:9000}];
  const view=render(<RouteGeometryMap cameras={cameras} points={[]} diagnosticId="global-163-requires-review" selectedTicks={0} validTicks={new Set([0,9000])} onSeekCamera={jest.fn()} sourcePreview={<span>Исходное видео</span>}/>);
  expect(screen.getByText(/Экспериментальная реконструкция — маршрут не подтверждён/)).toHaveTextContent('global-163-requires-review');
  expect(screen.getByText('Исходное видео')).toBeInTheDocument();
  view.rerender(<RouteGeometryMap cameras={cameras} points={[]} selectedTicks={0} validTicks={new Set([0,9000])} onSeekCamera={jest.fn()} sourcePreview={<span>Исходное видео</span>}/>);
  expect(screen.queryByText(/Экспериментальная реконструкция — маршрут не подтверждён/)).not.toBeInTheDocument();
  expect(screen.getByText('Карта прохода')).toBeInTheDocument();
});

function mapSurface(){
  const element=screen.getByLabelText('Проекция опорных точек и положений камеры') as unknown as SVGSVGElement;
  jest.spyOn(element,'getBoundingClientRect').mockReturnValue({left:0,top:0,width:600,height:540,right:600,bottom:540,x:0,y:0,toJSON(){return {};}});
  return element;
}
function currentViewport():RouteMapViewport {
  const element=screen.getByLabelText('Окно схемы');return {zoom:Number(element.getAttribute('data-zoom')),panX:Number(element.getAttribute('data-pan-x')),panY:Number(element.getAttribute('data-pan-y'))};
}
function pointer(element:SVGSVGElement,type:string,x:number,y:number){
  const event=new MouseEvent(type,{clientX:x,clientY:y,button:0,bubbles:true});Object.defineProperty(event,'pointerId',{value:1});fireEvent(element,event);
}

test('zoomed and rotated canvas picking still seeks the exact source-backed camera',()=>{
  const seek=jest.fn(),cameras=[{center:[0,0,0],ticks_90k:0,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0]]},
    {center:[1,0,1],ticks_90k:9000,camera_to_world:[[0,0,1,1],[0,1,0,0],[-1,0,0,1]]},
    {center:[2,0,2],ticks_90k:18000,camera_to_world:[[1,0,0,2],[0,1,0,0],[0,0,1,2]]}];
  render(<RouteGeometryMap cameras={cameras} points={[]} selectedTicks={9000} validTicks={new Set([0,9000])} onSeekCamera={seek}/>);
  const surface=mapSurface();fireEvent.keyDown(surface,{key:'+'});fireEvent.keyDown(surface,{key:'ArrowRight'});
  const camera=screen.getByRole('button',{name:'Показать исходный кадр 1 · 0.00 с'}).querySelector('circle')!;
  const point={x:Number(camera.getAttribute('cx')),y:Number(camera.getAttribute('cy'))},angle=Number(screen.getByLabelText('Поворот схемы').getAttribute('data-angle-radians'));
  const displayed=routeDisplayPoint(point,currentViewport(),angle);
  fireEvent.click(surface,{clientX:displayed.x,clientY:displayed.y});expect(seek).toHaveBeenCalledTimes(1);expect(seek).toHaveBeenLastCalledWith(0);
  expect(screen.queryByRole('button',{name:/исходный кадр 3/i})).not.toBeInTheDocument();
});

test('drag pans without seeking, keyboard and Fit reset the viewport without changing compass or geometry',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:9000}],points=[[0,1,0,255,20,10]],seek=jest.fn(),snapshot=JSON.stringify({cameras,points});
  const view=render(<RouteGeometryMap cameras={cameras} points={points} selectedTicks={0} validTicks={new Set([0,9000])} onSeekCamera={seek}/>);
  const surface=mapSurface(),angle=screen.getByLabelText('Поворот схемы').getAttribute('data-angle-radians');
  pointer(surface,'pointerdown',200,200);pointer(surface,'pointermove',280,250);pointer(surface,'pointerup',280,250);
  expect(currentViewport()).toEqual({zoom:1,panX:80,panY:50});
  fireEvent.click(screen.getByRole('button',{name:'Показать исходный кадр 1 · 0.00 с'}));expect(seek).not.toHaveBeenCalled();
  fireEvent.keyDown(surface,{key:'+'});fireEvent.keyDown(surface,{key:'ArrowUp'});expect(currentViewport().zoom).toBe(1.25);
  fireEvent.click(screen.getByRole('button',{name:'Вписать весь маршрут'}));expect(currentViewport()).toEqual({zoom:1,panX:0,panY:0});
  expect(screen.getByLabelText('Поворот схемы')).toHaveAttribute('data-angle-radians',angle);
  fireEvent.click(screen.getByRole('button',{name:'Маршрут'}));expect(screen.getByLabelText('Облако восстановленных ориентиров')).toHaveAttribute('data-point-count','0');
  fireEvent.click(screen.getByRole('button',{name:'Исходные цвета'}));expect(screen.getByLabelText('Цвет опорных точек')).toHaveValue('rgb');
  expect(fills).toContain('rgb(255,20,10)');expect(JSON.stringify({cameras,points})).toBe(snapshot);
  fireEvent.keyDown(surface,{key:'+'});view.rerender(<RouteGeometryMap cameras={cameras} points={points} selectedTicks={9000} validTicks={new Set([0,9000])} onSeekCamera={seek}/>);
  expect(currentViewport().zoom).toBe(1.25);expect(screen.getByLabelText('Цвет опорных точек')).toHaveValue('rgb');
  view.rerender(<RouteGeometryMap cameras={cameras.map(camera=>({...camera,center:[...camera.center]}))} points={points} selectedTicks={0} validTicks={new Set([0,9000])} onSeekCamera={seek}/>);
  expect(currentViewport()).toEqual({zoom:1,panX:0,panY:0});expect(screen.getByLabelText('Цвет опорных точек')).not.toHaveValue('rgb');
});

test('wheel zoom is bounded, prevents page scroll and keeps its pointer anchor fixed; Home fits',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:9000}];render(<RouteGeometryMap cameras={cameras} points={[]}/>);
  const surface=mapSurface(),anchor={x:160,y:220},wheel=new WheelEvent('wheel',{clientX:anchor.x,clientY:anchor.y,deltaY:-300,bubbles:true,cancelable:true});
  fireEvent(surface,wheel);expect(wheel.defaultPrevented).toBe(true);expect(currentViewport().zoom).toBeGreaterThan(1);
  const displayed=routeDisplayPoint(anchor,currentViewport(),0);expect(displayed.x).toBeCloseTo(anchor.x);expect(displayed.y).toBeCloseTo(anchor.y);
  for(let n=0;n<10;n++)fireEvent.wheel(surface,{clientX:300,clientY:270,deltaY:-10000});
  expect(currentViewport().zoom).toBe(8);expect(screen.getByRole('button',{name:'Приблизить схему'})).toBeDisabled();
  fireEvent.keyDown(surface,{key:'Home'});expect(currentViewport()).toEqual({zoom:1,panX:0,panY:0});expect(screen.getByRole('button',{name:'Отдалить схему'})).toBeDisabled();
});

test('a pointer gesture begun on an old result cannot select a camera after source geometry changes',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:9000}],seek=jest.fn();
  const view=render(<RouteGeometryMap cameras={cameras} points={[]} validTicks={new Set([0,9000])} onSeekCamera={seek}/>),surface=mapSurface();
  pointer(surface,'pointerdown',200,200);
  view.rerender(<RouteGeometryMap cameras={cameras.map(camera=>({...camera,center:[...camera.center]}))} points={[]} validTicks={new Set([0,9000])} onSeekCamera={seek}/>);
  pointer(surface,'pointerup',200,200);fireEvent.click(screen.getByRole('button',{name:'Показать исходный кадр 1 · 0.00 с'}));expect(seek).not.toHaveBeenCalled();
  pointer(surface,'pointerdown',200,200);pointer(surface,'pointerup',200,200);
  fireEvent.click(screen.getByRole('button',{name:'Показать исходный кадр 1 · 0.00 с'}));expect(seek).toHaveBeenLastCalledWith(0);
});
