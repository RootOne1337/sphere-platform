'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Radar, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

interface DiscoveredDevice {
  ip: string;
  port: number;
  serial: string | null;
  model: string | null;
  registered: boolean;
}

interface DiscoverResponse {
  found: number;
  registered: number;
  devices: DiscoveredDevice[];
}

export default function DiscoveryPage() {
  const [subnet, setSubnet] = useState('192.168.1.0/24');
  const [ports, setPorts] = useState('5555,5037');
  const [autoRegister, setAutoRegister] = useState(true);
  const parsedPorts = ports.split(',').map((port) => Number.parseInt(port.trim(), 10)).filter((port) => Number.isInteger(port) && port > 0 && port <= 65535);

  const scan = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/discovery/scan', {
        subnet,
        ports: parsedPorts,
        auto_register: autoRegister,
      });
      return data as DiscoverResponse;
    },
  });

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    scan.mutate();
  };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Подключение устройств"
        title="Обнаружение"
        description="Найдите Android-устройства в доступной подсети и проверьте, какие из них уже зарегистрированы в Sphere."
      />

      <Card className="overflow-hidden shadow-soft">
        <CardHeader className="border-b border-border/70 bg-muted/30 p-5 sm:p-6">
          <CardTitle className="flex items-center gap-3 font-sans text-base font-semibold tracking-tight sm:text-lg">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Radar className="h-5 w-5" aria-hidden="true" />
            </span>
            Сканирование подсети
          </CardTitle>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            Укажите CIDR и ADB-порты. Результаты сканирования не меняют состояние устройств, если включена автоматическая регистрация.
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
                <Input id="discovery-ports" value={ports} onChange={(event) => setPorts(event.target.value)} placeholder="5555,5037" inputMode="numeric" autoComplete="off" />
                <p className="text-xs text-muted-foreground">Несколько портов вводите через запятую. Допустимый диапазон: 1–65535.</p>
              </div>
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
              <p className="text-xs leading-5 text-muted-foreground">Сканирование выполняется сервером в рамках доступных ему сетевых маршрутов.</p>
              <Button type="submit" disabled={scan.isPending || !subnet.trim() || parsedPorts.length === 0} className="min-w-40">
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
            <p className="mt-1 text-xs text-muted-foreground">Проверьте сетевую доступность и параметры запроса, затем повторите попытку.</p>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={() => scan.mutate()} disabled={scan.isPending}>Повторить</Button>
        </div>
      )}

      {scan.data && (
        <Card className="overflow-hidden shadow-soft">
          <CardHeader className="flex flex-col gap-3 border-b border-border/70 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
            <div>
              <CardTitle className="font-sans text-base font-semibold tracking-tight">Результаты поиска</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Подсеть <span className="font-mono text-foreground">{subnet}</span></p>
            </div>
            <div className="flex flex-wrap gap-2" aria-label="Сводка результатов">
              <Badge variant="outline" className="rounded-full px-3 py-1">Найдено: {scan.data.found}</Badge>
              <Badge variant="success" className="rounded-full px-3 py-1">Зарегистрировано: {scan.data.registered}</Badge>
            </div>
          </CardHeader>
          {scan.data.devices.length === 0 ? (
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
                  {scan.data.devices.map((device) => (
                    <tr key={`${device.ip}:${device.port}:${device.serial ?? ''}`} className="transition-colors hover:bg-muted/30 motion-reduce:transition-none">
                      <td className="px-5 py-3.5 font-mono text-xs">{device.ip}</td>
                      <td className="px-5 py-3.5 tabular-nums">{device.port}</td>
                      <td className="max-w-64 truncate px-5 py-3.5 font-mono text-xs text-muted-foreground">{device.serial ?? '—'}</td>
                      <td className="px-5 py-3.5">{device.model ?? '—'}</td>
                      <td className="px-5 py-3.5">
                        <Badge variant={device.registered ? 'success' : 'outline'} className="rounded-full">
                          {device.registered ? <><CheckCircle2 className="mr-1 h-3 w-3" aria-hidden="true" />Есть в Sphere</> : 'Не зарегистрировано'}
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
