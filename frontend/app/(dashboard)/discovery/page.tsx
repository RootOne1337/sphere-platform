'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Radar, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

interface DiscoveredDevice {
  ip: string;
  port: number;
  serial: string;
  model: string | null;
  already_registered: boolean;
  registered_id: string | null;
}

interface DiscoverResponse {
  scanned: number;
  found: number;
  registered: number;
  devices: DiscoveredDevice[];
  duration_ms: number;
}

interface ScanRequest {
  subnet: string;
  port_range: [number, number];
  timeout_ms: number;
  workstation_id: string;
  auto_register: boolean;
}

function isDiscoverResponse(value: unknown): value is DiscoverResponse {
  if (!value || typeof value !== 'object') return false;
  const data = value as DiscoverResponse;
  return [data.scanned, data.found, data.registered].every(count => Number.isInteger(count) && count >= 0)
    && Number.isFinite(data.duration_ms) && data.duration_ms >= 0
    && Array.isArray(data.devices) && data.found === data.devices.length && data.registered <= data.found
    && data.devices.every(device => device && typeof device.ip === 'string' && typeof device.serial === 'string'
      && Number.isInteger(device.port) && device.port >= 1 && device.port <= 65535
      && (device.model === null || typeof device.model === 'string')
      && typeof device.already_registered === 'boolean'
      && (device.registered_id === null || typeof device.registered_id === 'string'));
}

export default function DiscoveryPage() {
  const [subnet, setSubnet] = useState('192.168.1.0/24');
  const [ports, setPorts] = useState('5554,5584');
  const [workstation, setWorkstation] = useState('');
  const [timeout, setTimeout] = useState('500');
  const [autoRegister, setAutoRegister] = useState(false);
  const portParts = ports.split(',').map(port => port.trim());
  const parsedPorts = portParts.map(Number);
  const validPorts = portParts.length === 2 && portParts.every(port => /^\d+$/.test(port))
    && parsedPorts.every(port => Number.isInteger(port) && port >= 1 && port <= 65535)
    && parsedPorts[0] <= parsedPorts[1];
  const validWorkstation = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(workstation.trim());
  const validTimeout = /^\d+$/.test(timeout) && Number(timeout) >= 100 && Number(timeout) <= 5000;
  const canScan = Boolean(subnet.trim()) && validPorts && validWorkstation && validTimeout;

  const scan = useMutation({
    retry: false,
    mutationFn: async (request: ScanRequest) => {
      const { data } = await api.post('/discovery/scan', request);
      if (!isDiscoverResponse(data)) throw new Error('Некорректный ответ обнаружения');
      return { request, result: data, receivedAt: new Date().toISOString() };
    },
  });

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canScan || scan.isPending) return;
    scan.mutate({ subnet: subnet.trim(), port_range: [parsedPorts[0], parsedPorts[1]],
      timeout_ms: Number(timeout), workstation_id: workstation.trim(), auto_register: autoRegister });
  };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Подключение устройств"
        title="Обнаружение"
        description="Android APK подключается к Sphere самостоятельно. Дополнительный ADB-поиск доступен только через уже настроенный PC Agent."
      />

      <Card><CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div><p className="text-sm font-medium">Подключение через Android APK</p>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">Телефону или эмулятору не нужны ADB, сканирование подсети или программа на ПК. После настройки APK устройство появится в парке.</p></div>
        <Button asChild variant="outline"><Link href="/devices">Открыть парк устройств</Link></Button>
      </CardContent></Card>

      <Card className="overflow-hidden shadow-soft">
        <CardHeader className="border-b border-border/70 bg-muted/30 p-5 sm:p-6">
          <CardTitle className="flex items-center gap-3 font-sans text-base font-semibold tracking-tight sm:text-lg">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Radar className="h-5 w-5" aria-hidden="true" />
            </span>
            Дополнительный ADB-поиск
          </CardTitle>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            {autoRegister ? 'Поиск добавит новые найденные устройства в каталог Sphere.' : 'Регистрация выключена: поиск не добавляет устройства в каталог Sphere.'}
            {' '}Сеть проверяет выбранный PC Agent; доступность этой сети из backend не определяет результат.
          </p>
        </CardHeader>
        <CardContent className="p-5 sm:p-6">
          <form className="space-y-5" onSubmit={handleSubmit}>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(16rem,0.8fr)]">
              <div className="space-y-2">
                <Label htmlFor="discovery-subnet">Подсеть · CIDR</Label>
                <Input id="discovery-subnet" value={subnet} onChange={(event) => setSubnet(event.target.value)} placeholder="192.168.1.0/24" autoComplete="off" />
                <p className="text-xs text-muted-foreground">Например, `192.168.1.0/24` для локального сегмента.</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="discovery-ports">Порты ADB</Label>
                <Input id="discovery-ports" value={ports} onChange={(event) => setPorts(event.target.value)} placeholder="5554,5584" inputMode="numeric" autoComplete="off" aria-invalid={!validPorts} />
                <p className="text-xs text-muted-foreground">Две границы через запятую: от меньшего порта до большего включительно, 1–65535.</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
              <div className="space-y-2"><Label htmlFor="discovery-workstation">ID существующего PC Agent · UUID</Label>
                <Input id="discovery-workstation" value={workstation} onChange={event => setWorkstation(event.target.value)} autoComplete="off" aria-invalid={Boolean(workstation) && !validWorkstation} />
                <p className="text-xs text-muted-foreground">Нужен только для этого ADB-режима. Без настроенного PC Agent не запускайте поиск; используйте Android APK.</p></div>
              <div className="space-y-2"><Label htmlFor="discovery-timeout">Таймаут порта · мс</Label>
                <Input id="discovery-timeout" value={timeout} onChange={event => setTimeout(event.target.value)} inputMode="numeric" aria-invalid={!validTimeout} />
                <p className="text-xs text-muted-foreground">100–5000 мс на проверку порта.</p></div>
            </div>

            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-border/80 bg-background p-4 transition-colors hover:bg-muted/40 motion-reduce:transition-none">
              <input
                type="checkbox"
                checked={autoRegister}
                onChange={(event) => setAutoRegister(event.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
              />
              <span className="min-w-0">
                <span className="flex items-center gap-2 text-sm font-medium text-foreground"><ShieldCheck className="h-4 w-4 text-primary" aria-hidden="true" />Регистрировать найденные устройства</span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">При выключенном параметре сканирование только покажет найденные адреса и модели.</span>
              </span>
            </label>

            <div className="flex flex-col gap-3 border-t border-border/70 pt-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-muted-foreground">Новый запрос использует текущую форму. Параметры завершённого поиска сохраняются в его результате.</p>
              <Button type="submit" disabled={scan.isPending || !canScan} className="min-w-40">
                {scan.isPending ? <RefreshCw className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Search className="mr-2 h-4 w-4" aria-hidden="true" />}
                {scan.isPending ? 'Сканируем…' : 'Начать поиск'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {scan.isError && (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="font-medium">Не удалось выполнить сканирование.</p>
            <p className="mt-1 text-xs text-muted-foreground">{getApiErrorMessage(scan.error, 'Результат не подтверждён. Проверьте PC Agent и параметры запроса.')}</p>
            <p className="mt-1 text-xs text-muted-foreground">Повтор отправляет исходные параметры; при включённой регистрации запрос может добавить устройства. Автоматического повтора нет.</p>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={() => { if (scan.variables) scan.mutate(scan.variables); }} disabled={scan.isPending || !scan.variables}>Повторить исходный поиск</Button>
        </div>
      )}

      {scan.data && (
        <Card className="overflow-hidden shadow-soft">
          <CardHeader className="flex flex-col gap-3 border-b border-border/70 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
            <div>
              <CardTitle className="font-sans text-base font-semibold tracking-tight">Результаты поиска</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Подсеть <span className="font-mono text-foreground">{scan.data.request.subnet}</span></p>
              <p className="mt-1 break-all text-xs text-muted-foreground">PC Agent: {scan.data.request.workstation_id} · порты {scan.data.request.port_range.join('–')} · {scan.data.request.auto_register ? 'с регистрацией' : 'без регистрации'}</p>
              <p className="mt-1 text-xs text-muted-foreground">Ответ получен: {scan.data.receivedAt} · объём запроса {scan.data.result.scanned} адресов/портов · {Math.round(scan.data.result.duration_ms)} мс</p>
            </div>
            <div className="flex flex-wrap gap-2" aria-label="Сводка результатов">
              <Badge variant="outline" className="rounded-full px-3 py-1">Найдено: {scan.data.result.found}</Badge>
              <Badge variant="success" className="rounded-full px-3 py-1">Добавлено: {scan.data.result.registered}</Badge>
            </div>
          </CardHeader>
          {scan.data.result.devices.length === 0 ? (
            <CardContent className="p-10 text-center">
              <Radar className="mx-auto h-8 w-8 text-muted-foreground/60" aria-hidden="true" />
              <p className="mt-3 text-sm font-medium">Устройства не найдены</p>
              <p className="mt-1 text-xs text-muted-foreground">Проверьте CIDR, порты и доступность сети со стороны сервера.</p>
            </CardContent>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] text-sm">
                <thead className="bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th scope="col" className="px-5 py-3">IP-адрес</th>
                    <th scope="col" className="px-5 py-3">Порт</th>
                    <th scope="col" className="px-5 py-3">Серийный номер</th>
                    <th scope="col" className="px-5 py-3">Модель</th>
                    <th scope="col" className="px-5 py-3">Регистрация</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/70">
                  {scan.data.result.devices.map((device) => (
                    <tr key={`${device.ip}:${device.port}:${device.serial ?? ''}`} className="transition-colors hover:bg-muted/30 motion-reduce:transition-none">
                      <td className="px-5 py-3.5 font-mono text-xs">{device.ip}</td>
                      <td className="px-5 py-3.5 tabular-nums">{device.port}</td>
                      <td className="max-w-64 truncate px-5 py-3.5 font-mono text-xs text-muted-foreground">{device.serial ?? '—'}</td>
                      <td className="px-5 py-3.5">{device.model ?? '—'}</td>
                      <td className="px-5 py-3.5">
                        <Badge variant={device.already_registered || device.registered_id ? 'success' : 'outline'} className="rounded-full">
                          {device.already_registered ? <><CheckCircle2 className="mr-1 h-3 w-3" aria-hidden="true" />Уже было в Sphere</> : device.registered_id ? 'Добавлено в Sphere' : 'Не зарегистрировано'}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </PageFrame>
  );
}
