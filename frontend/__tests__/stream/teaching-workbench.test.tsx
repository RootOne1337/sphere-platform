import React from 'react';
import { render, screen } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import fs from 'node:fs';
import path from 'node:path';
import { TeachingWorkbench } from '@/src/features/stream/TeachingWorkbench';
import { connectTeaching } from '@/src/features/stream/teachingConnection';
jest.mock('@/src/features/stream/teachingConnection',()=>({connectTeaching:jest.fn()}));
jest.mock('@/lib/store',()=>({useAuthStore:(select:(s:unknown)=>unknown)=>select({accessToken:null,sessionVersion:1})}));
test('read-only workbench exposes setup and emergency stop without opening media or native input',()=>{
  render(<TeachingWorkbench deviceId="test-device" readOnly />);
  expect(screen.getByRole('button',{name:'Подключить поток'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Записать маршрут'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Остановить · Esc'})).toBeDisabled();
  expect(screen.getByLabelText('Игровой экран: WASD, мышь, пробел, Shift; Escape — остановить запись')).toBeInTheDocument();
  expect(screen.getByText('Для записи требуется право stream:control.')).toBeInTheDocument();
  expect(connectTeaching).not.toHaveBeenCalled();
});
test('initial operator view does not record until explicit authenticated connection and start',()=>{
  render(<TeachingWorkbench deviceId="test-device" readOnly={false} />);
  expect(screen.getByRole('button',{name:'Записать маршрут'})).toBeDisabled();
  expect(screen.getByText('WASD · стик')).toBeInTheDocument();
  expect(connectTeaching).not.toHaveBeenCalled();
});
test('produce static layout fixture for browser review without impersonating a live device',()=>{
  const directory=path.resolve(process.cwd(),'../.local-pilot/teaching-ui-preview');fs.mkdirSync(directory,{recursive:true});
  const markup=renderToStaticMarkup(<TeachingWorkbench deviceId="layout-fixture" readOnly={false} />);
  fs.writeFileSync(path.join(directory,'index.html'),'<!doctype html><html class="dark" lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="style.css"><title>Sphere — teaching layout fixture</title></head><body class="bg-background text-foreground"><main class="mx-auto max-w-[1800px] space-y-5 p-4 sm:p-8"><p class="text-sm text-muted-foreground">Проверка компоновки · статический макет реального компонента · устройство и запись не подключены</p>'+markup+'</main></body></html>');
  expect(markup).toContain('Покажите путь один раз');
});
