'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowUpRight, Check, Download, Loader2, Monitor, Smartphone, X } from 'lucide-react';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { OtaRelease } from './recovery';

const CHANNELS = [
  { id: 'android-canary/dev', name: 'Android · пилот dev', platform: 'android-canary', flavor: 'dev' },
  { id: 'android/dev', name: 'Android · dev', platform: 'android', flavor: 'dev' },
  { id: 'android/enterprise', name: 'Android · enterprise', platform: 'android', flavor: 'enterprise' },
  { id: 'android-canary/enterprise', name: 'Android · пилот enterprise', platform: 'android-canary', flavor: 'enterprise' },
] as const;

const mib = (bytes: number) => (bytes / 1024 / 1024).toLocaleString('ru-RU', { maximumFractionDigits: 1 });

export function AgentDownloadPanel({ releases, available }: { releases: OtaRelease[]; available: boolean }) {
  const [channelId, setChannelId] = useState<string>(CHANNELS[0].id);
  const [progress, setProgress] = useState<{ loaded: number; total?: number } | null>(null);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const request = useRef<AbortController | null>(null);
  const active = useRef(true);
  const objectUrls = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const channel = CHANNELS.find(value => value.id === channelId) ?? CHANNELS[0];
  const latest = releases.filter(value => value.platform === channel.platform && value.flavor === channel.flavor)
    .sort((a, b) => b.version_code - a.version_code)[0];

  useEffect(() => {
    active.current = true;
    const urls = objectUrls.current;
    return () => {
      active.current = false;
      request.current?.abort();
      for (const [url, timer] of urls) { clearTimeout(timer); URL.revokeObjectURL(url); }
      urls.clear();
    };
  }, []);

  const download = async () => {
    if (request.current || !available) return;
    const controller = new AbortController();
    request.current = controller;
    setError(''); setSaved(''); setProgress({ loaded: 0 });
    try {
      const params = new URLSearchParams({ platform: channel.platform, flavor: channel.flavor });
      const response = await api.get<Blob>(`/updates/downloads/latest?${params}`, {
        responseType: 'blob', timeout: 120_000, signal: controller.signal,
        onDownloadProgress: event => {
          if (active.current && !controller.signal.aborted) setProgress({ loaded: event.loaded, total: event.total });
        },
      });
      if (!active.current || controller.signal.aborted) return;
      if (!(response.data instanceof Blob) || response.data.size === 0 || response.data.size > 200 * 1024 * 1024
        || !String(response.headers['content-type']).startsWith('application/vnd.android.package-archive')) {
        throw new Error('Invalid APK download');
      }
      const disposition = String(response.headers['content-disposition'] ?? '');
      const filename = disposition.match(/filename="?([a-zA-Z0-9_.-]+\.apk)"?(?:;|$)/i)?.[1]
        ?? `SphereAgent-${channel.platform}-${channel.flavor}.apk`;
      const url = URL.createObjectURL(response.data);
      const link = document.createElement('a');
      link.href = url; link.download = filename;
      document.body.appendChild(link); link.click(); link.remove();
      // Let the browser start its save before releasing the Blob. These URLs
      // are bounded to this mounted, account-scoped panel and never persisted.
      objectUrls.current.set(url, setTimeout(() => {
        URL.revokeObjectURL(url); objectUrls.current.delete(url);
      }, 60_000));
      setSaved('APK передан браузеру для сохранения.');
    } catch (failure: unknown) {
      if (!active.current) return;
      if (controller.signal.aborted) { setSaved('Скачивание отменено.'); return; }
      let explanation = getApiErrorMessage(failure, 'Не удалось скачать APK. Проверьте подключение и повторите.');
      const data = (failure as { response?: { data?: unknown } })?.response?.data;
      if (data instanceof Blob && data.size <= 16_384) {
        try { explanation = getApiErrorMessage({ response: { data: JSON.parse(await data.text()) } }, explanation); }
        catch { /* An ingress may return a non-JSON error page. */ }
      }
      if (active.current && !controller.signal.aborted) setError(explanation);
    } finally {
      if (request.current === controller) request.current = null;
      if (active.current) setProgress(null);
    }
  };

  return (
    <section aria-label="Скачать приложения" className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div className="relative overflow-hidden rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-emerald-500/[0.09] via-card to-card p-5 sm:p-6">
        <div className="flex items-start gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"><Smartphone className="h-5 w-5" aria-hidden="true" /></span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><h2 className="text-lg font-semibold tracking-tight">Sphere Agent</h2><span className="text-xs text-muted-foreground">Android · APK</span></div>
            <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">Установите агент на устройство или эмулятор. Кнопка всегда скачивает последний опубликованный APK выбранного канала.</p>
          </div>
        </div>
        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1 space-y-1.5">
            <label htmlFor="apk-download-channel" className="text-xs font-medium text-muted-foreground">Канал приложения</label>
            <select id="apk-download-channel" value={channelId} disabled={progress !== null}
              onChange={event => { setChannelId(event.target.value); setError(''); setSaved(''); }}
              className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
              {CHANNELS.map(value => <option key={value.id} value={value.id}>{value.name}</option>)}
            </select>
          </div>
          <Button className="h-11 shrink-0 gap-2 px-5" disabled={!available || progress !== null} onClick={() => { void download(); }}>
            {progress ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ArrowDownToLine className="h-4 w-4" aria-hidden="true" />}
            {progress ? 'Скачиваем APK…' : 'Скачать последний APK'}
          </Button>
        </div>
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          {channel.platform === 'android-canary' ? 'Пилотная сборка: отдельный канал обновлений. ' : ''}
          {available && latest ? `В каталоге ${latest.version_name} · код ${latest.version_code}.` : 'Актуальная версия определяется при скачивании.'}
        </p>
        {progress && <div className="mt-3 space-y-2" role="status" aria-live="polite">
          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>{progress.total ? `${mib(progress.loaded)} / ${mib(progress.total)} МБ` : `${mib(progress.loaded)} МБ получено`}</span>
            <button type="button" className="inline-flex min-h-8 items-center gap-1 rounded-md px-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => request.current?.abort()}><X className="h-3.5 w-3.5" aria-hidden="true" />Отменить</button>
          </div>
          {Boolean(progress.total) && <progress aria-label="Скачивание APK" className="h-1.5 w-full accent-emerald-500" value={Math.min(progress.loaded, progress.total!)} max={progress.total} />}
        </div>}
        {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
        {saved && <p role="status" className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"><Check className="h-3.5 w-3.5" aria-hidden="true" />{saved}</p>}
      </div>
      <div className="flex flex-col rounded-2xl border bg-card p-5 sm:p-6">
        <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl border bg-secondary/60 text-muted-foreground"><Monitor className="h-5 w-5" aria-hidden="true" /></span>
        <h2 className="text-lg font-semibold tracking-tight">Нужен эмулятор?</h2>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">LDPlayer для Windows. Скачайте эмулятор с официального сайта, затем установите в него APK Sphere Agent.</p>
        <a href="https://www.ldplayer.net/" target="_blank" rel="noopener noreferrer" className="mt-5 inline-flex min-h-11 w-fit items-center gap-2 rounded-lg border bg-background px-4 text-sm font-medium transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Download className="h-4 w-4" aria-hidden="true" />Скачать LDPlayer<ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          <span className="sr-only"> — официальный сайт, откроется в новой вкладке</span>
        </a>
      </div>
    </section>
  );
}
