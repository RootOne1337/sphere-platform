import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import fs from 'node:fs';
import path from 'node:path';
import { TextEncoder } from 'node:util';
import { TeachingWorkbench } from '@/src/features/stream/TeachingWorkbench';
import { connectTeaching } from '@/src/features/stream/teachingConnection';
jest.mock('@/src/features/stream/teachingConnection',()=>({connectTeaching:jest.fn()}));
jest.mock('@/src/features/stream/TeachingLocalWorker',()=>({TeachingLocalWorker:()=>null}));
let mockAuth: Record<string,unknown> = {accessToken:null,sessionVersion:1};
const mockSet = jest.fn(), mockClose = jest.fn(async()=>true);
const mockControllers: unknown[]=[];
const mockStateCallbacks: Array<(state:string,reason?:string)=>void>=[];
jest.mock('@/lib/store',()=>({useAuthStore:(select:(s:unknown)=>unknown)=>select(mockAuth)}));
jest.mock('@/src/features/stream/teachingContacts',()=>({...jest.requireActual('@/src/features/stream/teachingContacts'),TeachingContacts:jest.fn().mockImplementation((_e,_b,_f,_j,state)=>{
  const controller={set:mockSet,close:mockClose,hasContact:()=>false,isNeutral:true};mockControllers.push(controller);
  mockStateCallbacks.push(state);
  queueMicrotask(()=>state('ready'));return controller;
})}));
beforeEach(()=>{mockAuth={accessToken:null,sessionVersion:1};mockSet.mockClear();mockClose.mockClear();mockControllers.length=0;mockStateCallbacks.length=0;jest.mocked(connectTeaching).mockClear();});
test('read-only workbench exposes setup and emergency stop without opening media or native input',()=>{
  render(<TeachingWorkbench deviceId="test-device" readOnly />);
  expect(screen.getByRole('button',{name:'Подключить поток'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Записать маршрут'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Остановить · Esc'})).toBeDisabled();
  expect(screen.getByLabelText('Игровой экран: назначенные клавиши и мышь; Escape — остановить запись')).toBeInTheDocument();
  expect(screen.getByText('Для записи требуется право stream:control.')).toBeInTheDocument();
  expect(connectTeaching).not.toHaveBeenCalled();
});
test('initial operator view does not record until explicit authenticated connection and start',()=>{
  render(<TeachingWorkbench deviceId="test-device" readOnly={false} />);
  expect(screen.getByRole('button',{name:'Записать маршрут'})).toBeDisabled();
  expect(screen.getByText('W/A/S/D · стик')).toBeInTheDocument();
  expect(connectTeaching).not.toHaveBeenCalled();
  expect(screen.getByRole('checkbox',{name:/Управляю в эмуляторе/})).toBeChecked();
});
test('produce static layout fixture for browser review without impersonating a live device',()=>{
  const directory=path.resolve(process.cwd(),'../.local-pilot/teaching-ui-preview');fs.mkdirSync(directory,{recursive:true});
  const markup=renderToStaticMarkup(<TeachingWorkbench deviceId="layout-fixture" readOnly={false} />);
  fs.writeFileSync(path.join(directory,'index.html'),'<!doctype html><html class="dark" lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="style.css"><title>Sphere — teaching layout fixture</title></head><body class="bg-background text-foreground"><main class="mx-auto max-w-[1800px] space-y-5 p-4 sm:p-8"><p class="text-sm text-muted-foreground">Проверка компоновки · статический макет реального компонента · устройство и запись не подключены</p>'+markup+'</main></body></html>');
  expect(markup).toContain('Покажите путь один раз');
});

test('operator can use held WASD before recording, then closes that owner before arming a fresh journal',async()=>{
  mockAuth={accessToken:'test',sessionVersion:1,user:{id:'user',org_id:'org'}};
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).buffer}});
  Object.defineProperty(navigator,'storage',{configurable:true,value:{estimate:async()=>({quota:4*1024**3,usage:0})}});
  const postMessage=jest.fn();let emit:(message:Record<string,unknown>)=>void=()=>{};
  jest.mocked(connectTeaching).mockImplementation(async(_d,_t,_v,_s,_r,_f,onMessage)=>{
    emit=onMessage;emit({type:'attached'});
    return {fresh:()=>true,binding:()=>({captureEpoch:'test',width:960,height:540}),endpoint:()=>({}),worker:{postMessage,terminate:jest.fn()},close:jest.fn()} as never;
  });
  render(<TeachingWorkbench deviceId="test-device" readOnly={false} />);
  fireEvent.click(screen.getByRole('checkbox',{name:/Управляю в эмуляторе/}));
  const connect=screen.getByRole('button',{name:'Подключить поток'});await waitFor(()=>expect(connect).toBeEnabled());fireEvent.click(connect);
  const control=screen.getByRole('button',{name:'Включить управление'});await waitFor(()=>expect(control).toBeEnabled());
  const forwardKey=screen.getByRole('button',{name:'Клавиша: Вперёд / газ'});fireEvent.click(forwardKey);
  expect(control).toBeDisabled();expect(screen.getByRole('button',{name:'Записать маршрут'})).toBeDisabled();
  fireEvent.keyDown(forwardKey,{code:'ArrowUp'});fireEvent.click(control);
  await screen.findByText('Управление включено · фокус на экране');
  expect(screen.getByRole('button',{name:'Подключить 3D-просмотр'})).toBeDisabled();
  const video=screen.getByLabelText('Игровой экран: назначенные клавиши и мышь; Escape — остановить запись');
  fireEvent.keyDown(video,{code:'KeyW'});expect(mockSet).not.toHaveBeenCalled();
  fireEvent.keyDown(video,{code:'ArrowUp'});fireEvent.keyUp(video,{code:'ArrowUp'});
  expect(mockSet).toHaveBeenCalledWith(0,{x:144,y:442});expect(mockSet).toHaveBeenCalledWith(0,null);
  expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({type:'arm'}));
  fireEvent.click(screen.getByRole('button',{name:'Записать маршрут'}));
  await waitFor(()=>expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'arm',config:expect.objectContaining({max_duration_ms:600000,profile:expect.objectContaining({keys:expect.objectContaining({forward:'ArrowUp'})})})})));
  expect(mockClose).toHaveBeenCalledTimes(1);expect(mockControllers).toHaveLength(2);
  act(()=>emit({type:'recording'}));fireEvent.keyDown(video,{code:'Space'});fireEvent.keyUp(video,{code:'Space'});
  expect(mockSet).toHaveBeenCalledWith(2,null);
  const scene=document.createElement('iframe');scene.title='3D-сцена маршрута Rerun';document.body.appendChild(scene);scene.focus();
  const focus=jest.spyOn(document,'hasFocus').mockReturnValue(true);
  await act(async()=>{fireEvent.blur(window);await Promise.resolve();});
  expect(mockClose).toHaveBeenCalledTimes(1);
  focus.mockReturnValue(false);await act(async()=>{fireEvent.blur(window);await Promise.resolve();});
  await waitFor(()=>expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'stop',confirmed:true})));
  act(()=>emit({type:'finalized',id:null,manifest:{complete:true,frames:0,media_duration_ticks_90k:0}}));
  await screen.findByText('Остановлено: окно потеряло фокус. Проверьте статус материала.');
  focus.mockRestore();scene.remove();
});

test('the operator sees the separate 3D section and a ten-minute recording option',()=>{
  render(<TeachingWorkbench deviceId="test-device" readOnly={false}/>);
  expect(screen.getByLabelText('Живая 3D-реконструкция')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Подключить 3D-просмотр'})).toBeDisabled();
  expect(screen.getByRole('combobox',{name:'Предел записи'})).toHaveValue('10');
});

test('workflow switches to a focused live view without losing capture setup',()=>{
  render(<TeachingWorkbench deviceId="test-device" readOnly={false}/>);
  fireEvent.change(screen.getByLabelText('Название'),{target:{value:'Ночной маршрут'}});
  const live=screen.getByRole('button',{name:/3 · Направление/});
  fireEvent.click(live);
  expect(live).toHaveAttribute('aria-current','step');
  expect(screen.getByRole('heading',{name:'Сверка с живым экраном'})).toBeInTheDocument();
  expect(screen.getByLabelText('Живая проверка направления')).toBeInTheDocument();
  expect(screen.queryByRole('heading',{name:'Подготовка маршрута'})).not.toBeInTheDocument();
  expect(screen.getByText('Наблюдение / пеший тест')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/1 · Запись/}));
  expect(screen.getByLabelText('Название')).toHaveValue('Ночной маршрут');
  expect(screen.getByRole('heading',{name:'Подготовка маршрута'})).toBeInTheDocument();
});

test('capture quality controls remain discoverable without occupying the main workspace',()=>{
  render(<TeachingWorkbench deviceId="test-device" readOnly={false}/>);
  const summary=screen.getByText('Качество исходной записи');
  const details=summary.closest('details');
  expect(details).not.toHaveAttribute('open');
  fireEvent.click(summary);
  expect(details).toHaveAttribute('open');
  expect(screen.getByRole('button',{name:'Съёмка · 30 FPS / 24 Мбит'})).toBeEnabled();
});

test('vehicle mode exposes four explicit calibration targets and never enables example coordinates',()=>{
  render(<TeachingWorkbench deviceId="test-device" readOnly={false}/>);
  fireEvent.change(screen.getByRole('combobox',{name:'Схема управления'}),{target:{value:'vehicle_buttons'}});
  expect(screen.getByRole('button',{name:/газ \/ вперёд/})).toBeDisabled();
  expect(screen.getByRole('button',{name:/тормоз \/ назад/})).toBeDisabled();
  expect(screen.getByRole('button',{name:/поворот влево/})).toBeDisabled();
  expect(screen.getByRole('button',{name:/поворот вправо/})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Включить управление'})).toBeDisabled();
  expect(screen.getByLabelText('Панель записи')).toHaveClass('sticky','top-16');
});

test('an unsolicited Android close ends control and stops a recording instead of leaving dead keys active',async()=>{
  mockAuth={accessToken:'test',sessionVersion:1,user:{id:'user',org_id:'org'}};
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).buffer}});
  Object.defineProperty(navigator,'storage',{configurable:true,value:{estimate:async()=>({quota:4*1024**3,usage:0})}});
  const postMessage=jest.fn();let emit:(message:Record<string,unknown>)=>void=()=>{};
  jest.mocked(connectTeaching).mockImplementation(async(_d,_t,_v,_s,_r,_f,onMessage)=>{
    emit=onMessage;emit({type:'attached'});
    return {fresh:()=>true,binding:()=>({captureEpoch:'test',width:960,height:540}),endpoint:()=>({}),worker:{postMessage,terminate:jest.fn()},close:jest.fn()} as never;
  });
  render(<TeachingWorkbench deviceId="test-device" readOnly={false}/>);
  fireEvent.click(screen.getByRole('checkbox',{name:/Управляю в эмуляторе/}));
  const connect=screen.getByRole('button',{name:'Подключить поток'});await waitFor(()=>expect(connect).toBeEnabled());fireEvent.click(connect);
  const control=screen.getByRole('button',{name:'Включить управление'});await waitFor(()=>expect(control).toBeEnabled());fireEvent.click(control);
  await screen.findByText('Управление включено · фокус на экране');
  act(()=>mockStateCallbacks.at(-1)!('closed'));
  await screen.findByText(/Android завершил сеанс ввода/);expect(control).toBeEnabled();
  expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({type:'arm'}));
  fireEvent.click(screen.getByRole('button',{name:'Записать маршрут'}));
  await waitFor(()=>expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'arm'})));
  act(()=>emit({type:'recording'}));act(()=>mockStateCallbacks.at(-1)!('closed'));
  await waitFor(()=>expect(postMessage).toHaveBeenCalledWith({type:'stop',confirmed:true,reason:'native_closed_unexpectedly'}));
  act(()=>emit({type:'finalized',id:null,manifest:{complete:false,failure:'native_closed_unexpectedly'}}));
  expect(screen.getByLabelText('Результат последней записи')).toHaveTextContent('native_closed_unexpectedly');
  await waitFor(()=>expect(screen.getByRole('button',{name:'Включить управление'})).toBeDisabled());
});

test('external recording survives focus loss, fences browser controls and marks input provenance',async()=>{
  mockAuth={accessToken:'test',sessionVersion:1,user:{id:'user',org_id:'org'}};
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).buffer}});
  Object.defineProperty(navigator,'storage',{configurable:true,value:{estimate:async()=>({quota:4*1024**3,usage:0})}});
  const postMessage=jest.fn(),setExternalCapture=jest.fn();let emit:(message:Record<string,unknown>)=>void=()=>{};
  jest.mocked(connectTeaching).mockImplementation(async(_d,_t,_v,_s,_r,_f,onMessage)=>{
    emit=onMessage;emit({type:'attached'});
    return {fresh:()=>true,binding:()=>({captureEpoch:'test',width:960,height:540}),endpoint:()=>({}),worker:{postMessage,terminate:jest.fn()},close:jest.fn(),setExternalCapture} as never;
  });
  render(<TeachingWorkbench deviceId="test-device" readOnly={false}/>);
  const connect=screen.getByRole('button',{name:'Подключить поток'});await waitFor(()=>expect(connect).toBeEnabled());fireEvent.click(connect);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Записать маршрут'})).toBeEnabled());
  expect(screen.getByRole('checkbox',{name:/Управляю в эмуляторе/})).toBeChecked();
  fireEvent.click(screen.getByRole('button',{name:'Записать маршрут'}));
  await waitFor(()=>expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'arm',config:expect.objectContaining({input_capture:'external_unobserved'})})));
  expect(setExternalCapture).toHaveBeenCalledWith(true);
  act(()=>emit({type:'armed'}));
  await waitFor(()=>expect(mockClose).toHaveBeenCalledTimes(1));
  act(()=>emit({type:'recording'}));
  expect(screen.getByText('Управление в эмуляторе · нажатия не записываются')).toBeInTheDocument();
  const video=screen.getByLabelText('Игровой экран: назначенные клавиши и мышь; Escape — остановить запись');
  fireEvent.keyDown(video,{code:'KeyW'});expect(mockSet).not.toHaveBeenCalled();
  fireEvent.pointerCancel(video,{pointerId:5});
  fireEvent.lostPointerCapture(video,{pointerId:5});
  fireEvent.blur(video);
  await act(async()=>{fireEvent.blur(window);await Promise.resolve();});
  Object.defineProperty(document,'hidden',{configurable:true,value:true});
  fireEvent(document,new Event('visibilitychange'));
  expect(mockClose).toHaveBeenCalledTimes(1);
  expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({type:'stop'}));
  Reflect.deleteProperty(document,'hidden');
  fireEvent.click(screen.getByRole('button',{name:'Остановить · Esc'}));
  await waitFor(()=>expect(postMessage).toHaveBeenCalledWith({type:'stop',confirmed:true,reason:null}));
  act(()=>emit({type:'finalized',id:null,manifest:{complete:true,frames:5,media_duration_ticks_90k:3000}}));
  await waitFor(()=>expect(setExternalCapture).toHaveBeenCalledWith(false));
});

test('switching to LDPlayer during the storage check does not cancel video-only startup',async()=>{
  mockAuth={accessToken:'test',sessionVersion:1,user:{id:'user',org_id:'org'}};
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).buffer}});
  let quota:((value:StorageEstimate)=>void)|undefined;
  Object.defineProperty(navigator,'storage',{configurable:true,value:{estimate:()=>new Promise<StorageEstimate>(resolve=>{quota=resolve;})}});
  const postMessage=jest.fn(),setExternalCapture=jest.fn();let emit:(message:Record<string,unknown>)=>void=()=>{};
  jest.mocked(connectTeaching).mockImplementation(async(_d,_t,_v,_s,_r,_f,onMessage)=>{
    emit=onMessage;emit({type:'attached'});
    return {fresh:()=>true,binding:()=>({captureEpoch:'test',width:960,height:540}),endpoint:()=>({}),worker:{postMessage,terminate:jest.fn()},close:jest.fn(),setExternalCapture} as never;
  });
  render(<TeachingWorkbench deviceId="test-device" readOnly={false}/>);
  const connect=screen.getByRole('button',{name:'Подключить поток'});await waitFor(()=>expect(connect).toBeEnabled());fireEvent.click(connect);
  const record=screen.getByRole('button',{name:'Записать маршрут'});await waitFor(()=>expect(record).toBeEnabled());fireEvent.click(record);
  await act(async()=>{fireEvent.blur(window);await Promise.resolve();});
  await act(async()=>{quota?.({quota:4*1024**3,usage:0});await Promise.resolve();});
  await waitFor(()=>expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({type:'arm',config:expect.objectContaining({input_capture:'external_unobserved'})})));
  expect(setExternalCapture).toHaveBeenCalledWith(true);
  act(()=>emit({type:'armed'}));await waitFor(()=>expect(mockClose).toHaveBeenCalledTimes(1));
  act(()=>emit({type:'recording'}));
  expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({type:'stop'}));
  fireEvent.click(screen.getByRole('button',{name:'Остановить · Esc'}));
  await waitFor(()=>expect(postMessage).toHaveBeenCalledWith({type:'stop',confirmed:true,reason:null}));
  act(()=>emit({type:'finalized',id:null,manifest:{complete:true,frames:6,media_duration_ticks_90k:15000}}));
});
