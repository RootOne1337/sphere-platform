'use client';

import { useState } from 'react';
import { ArrowRight, Cable, FileKey2, Import, Layers3, Network, ShieldCheck, Smartphone, Waypoints } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAuthStore } from '@/lib/store';
import { AppVpnRuntimePanel } from '@/src/features/vpn/AppVpnRuntimePanel';
import { VpnProfileCatalog } from '@/src/features/vpn/VpnProfileCatalog';
import { VpnProfileInspector } from '@/src/features/vpn/VpnProfileInspector';
import { VpnRouterInfrastructure } from '@/src/features/vpn/VpnRouterInfrastructure';

export default function VPNManagerPage() {
  const actor = useAuthStore(s => s.user); const session = useAuthStore(s => s.sessionVersion);
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  const canWrite = Boolean(actor && ['org_admin', 'org_owner', 'super_admin'].includes(actor.role));
  const [importing, setImporting] = useState(false); const [checking, setChecking] = useState(false); const [revision, setRevision] = useState(0);
  return <div className="sphere-workspace min-h-full min-w-0 px-4 py-5 sm:px-6 sm:py-7 lg:px-8">
    <div className="mx-auto max-w-[1600px]">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-5">
        <div className="flex min-w-0 items-start gap-3 sm:gap-4"><div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary"><Network className="h-6 w-6" strokeWidth={1.6} /></div>
          <div><p className="mb-1 text-xs font-medium tracking-wide text-muted-foreground">СЕТЬ И ДОСТУП</p><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">VPN и маршрутизация</h1><p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">Устройства, профили и сетевые выходы — в одном рабочем пространстве.</p></div>
        </div>
        {canWrite && <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:pt-2"><Button variant="outline" aria-label="Проверить профиль" className="min-w-0 px-2 sm:px-4" onClick={() => setChecking(true)}><ShieldCheck className="mr-2 h-4 w-4 shrink-0" /><span>Проверить<span className="hidden sm:inline"> профиль</span></span></Button><Button className="min-w-0 px-2 shadow-sm sm:px-4" onClick={() => setImporting(true)}><Import className="mr-2 h-4 w-4 shrink-0" />Импорт .conf</Button></div>}
      </header>
      <Tabs defaultValue="devices" className="min-w-0">
        <div className="mb-5 overflow-x-auto border-b"><TabsList aria-label="Разделы VPN" className="h-12 w-max justify-start gap-2 rounded-none border-0 bg-transparent p-0"><TabsTrigger value="devices" className="h-12 gap-2 rounded-none border-b-2 border-transparent px-3 data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"><Smartphone className="h-4 w-4" />Подключения</TabsTrigger><TabsTrigger value="profiles" className="h-12 gap-2 rounded-none border-b-2 border-transparent px-3 data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"><FileKey2 className="h-4 w-4" />Профили</TabsTrigger><TabsTrigger value="infrastructure" className="h-12 gap-2 rounded-none border-b-2 border-transparent px-3 data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"><Waypoints className="h-4 w-4" />Инфраструктура</TabsTrigger><TabsTrigger value="policy" className="h-12 gap-2 rounded-none border-b-2 border-transparent px-3 data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"><ShieldCheck className="h-4 w-4" />Политика трафика</TabsTrigger></TabsList></div>
        <TabsContent value="devices" className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1 motion-safe:duration-200"><AppVpnRuntimePanel key={scope} /></TabsContent>
        <TabsContent value="profiles" className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1 motion-safe:duration-200"><VpnProfileCatalog key={`${scope}:${revision}`} canWrite={canWrite} /></TabsContent>
        <TabsContent value="infrastructure" className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1 motion-safe:duration-200"><VpnRouterInfrastructure key={scope} /></TabsContent>
        <TabsContent value="policy" className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1 motion-safe:duration-200">      <section aria-label="Принцип маршрутизации VPN" className="sphere-panel mb-6 grid overflow-hidden rounded-2xl border bg-card/60 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="p-5 sm:p-6"><div className="mb-3 inline-flex items-center gap-2 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary"><ShieldCheck className="h-3.5 w-3.5" />Изоляция приложений</div><h2 className="text-lg font-semibold tracking-tight">Трафик приложений — отдельно от управления</h2><p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">Профиль задаёт приложения для туннеля. Пауза, восстановление и смена выхода должны сохранять независимый канал Sphere.</p><div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground"><span className="flex items-center gap-1.5"><FileKey2 className="h-3.5 w-3.5" />WireGuard / AmneziaWG</span><span className="flex items-center gap-1.5"><Layers3 className="h-3.5 w-3.5" />Версии конфигураций</span></div></div>
        <div className="flex flex-col justify-center gap-4 border-t bg-muted/15 p-5 sm:p-6 lg:border-l lg:border-t-0">
          <div className="flex items-center gap-2 text-xs"><span className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border bg-background/50 px-3 py-3"><Smartphone className="h-4 w-4 shrink-0 text-muted-foreground" /><span>Приложения</span></span><ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground/60" /><span className="flex items-center gap-2 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 font-medium"><ShieldCheck className="h-4 w-4 text-primary" />VPN</span><ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground/60" /><span className="flex-1 rounded-xl border bg-background/50 px-3 py-3 text-center">Внешняя сеть</span></div>
          <div className="flex items-center gap-2 rounded-xl border border-dashed px-3 py-3 text-xs text-muted-foreground"><Cable className="h-4 w-4 shrink-0" /><span className="font-medium text-foreground">Sphere</span><span className="h-px min-w-3 flex-1 bg-border" /><span>Управление · видео · команды</span></div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">Схема политики. Фактическое состояние каждого устройства отображается в подключениях.</p>
        </div>
      </section>
        </TabsContent>
      </Tabs>
      {importing && canWrite && <VpnProfileInspector key={`import:${scope}`} purpose="save" onSaved={() => setRevision(v => v + 1)} onClose={() => setImporting(false)} />}
      {checking && canWrite && <VpnProfileInspector key={`inspect:${scope}`} onClose={() => setChecking(false)} />}
    </div>
  </div>;
}
