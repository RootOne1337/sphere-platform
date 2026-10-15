'use client';
import { useEffect, useRef, useState } from 'react';
import { SlidersHorizontal, Loader2, RefreshCw } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { parseStreamQuality, qualityDraft, type StreamQualitySettings, type StreamQualitySnapshot } from './streamQuality';

export function StreamQualityControl({ deviceId, readOnly, compact = false }: { deviceId: string; readOnly: boolean; compact?: boolean }) {
  const version = useAuthStore(state => state.sessionVersion);
  return <QualityPanel key={`${deviceId}:${version}`} deviceId={deviceId} readOnly={readOnly} compact={compact} />;
}

function QualityPanel({ deviceId, readOnly, compact = false }: { deviceId: string; readOnly: boolean; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<StreamQualitySnapshot | null>(null);
  const [profile, setProfile] = useState<StreamQualitySettings['profile']>('auto');
  const [fps, setFps] = useState('');
  const [mbps, setMbps] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const path = `/streaming/${encodeURIComponent(deviceId)}/quality`;
  const accept = (value: unknown) => {
    const parsed = parseStreamQuality(value);
    if (!parsed) throw new Error('invalid_quality_receipt');
    setSnapshot(parsed); setProfile(parsed.settings.profile);
    setFps(parsed.settings.max_fps?.toString() ?? '');
    setMbps(parsed.settings.max_bitrate_bps == null ? '' : String(parsed.settings.max_bitrate_bps / 1_000_000));
    return parsed;
  };
  const read = async () => {
    if (request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(null); setNotice(null);
    try {
      const { data } = await api.get(path, { signal: controller.signal, timeout: 12_000 });
      if (!controller.signal.aborted) accept(data);
    } catch {
      if (!controller.signal.aborted) setError('Не удалось прочитать настройки Android. Проверьте связь и версию APK.');
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  };
  useEffect(() => { if (open) void read(); return () => { request.current?.abort(); request.current = null; }; }, [open, path]); // eslint-disable-line react-hooks/exhaustive-deps
  const draft = qualityDraft(profile, fps, mbps);
  const changed = draft && snapshot && JSON.stringify(draft) !== JSON.stringify(snapshot.settings);
  const save = async () => {
    if (!draft || !changed || readOnly || request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(null); setNotice(null);
    try {
      const { data } = await api.post(path, draft, { signal: controller.signal, timeout: 12_000 });
      if (!controller.signal.aborted) {
        accept(data); setNotice('Android сохранил настройки. Захват и управление продолжаются.');
      }
    } catch {
      if (!controller.signal.aborted) setError('Подтверждение Android не получено. Настройки могли примениться — обновите их перед следующей попыткой.');
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  };
  const field = 'mt-1 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60';
  const active = snapshot?.active;
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><button type="button" aria-label="Качество видеопотока"
      title="Качество видеопотока" className={compact ? 'stream-tool-button' : 'inline-flex items-center gap-1.5 rounded border border-white/20 bg-black/80 px-2 py-1 text-xs text-white'}>
      <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden="true" />{!compact && 'Качество'}
    </button></DialogTrigger>
    <DialogContent className="max-h-[90dvh] max-w-lg overflow-y-auto rounded-2xl">
      <DialogHeader><DialogTitle>Качество видеопотока</DialogTitle>
        <DialogDescription>Исходное разрешение и ориентация устройства. Настройки сохраняются на Android и действуют для всех зрителей.</DialogDescription></DialogHeader>
      {busy && !snapshot && <p role="status" className="flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />Читаем настройки Android…</p>}
      {snapshot?.supported === false && <p className="text-sm text-muted-foreground">Для настройки качества обновите APK.</p>}
      {snapshot?.supported && <form className="space-y-4" onSubmit={event => { event.preventDefault(); void save(); }}>
        <div aria-label="Быстрые настройки качества" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: 'Авто', profile: 'auto' as const, fps: '', mbps: '' },
            { label: 'Текст', profile: 'detail' as const, fps: '30', mbps: '8' },
            { label: 'LAN · 60 FPS', profile: 'detail' as const, fps: '60', mbps: '24' },
            { label: 'Экономия', profile: 'economy' as const, fps: '30', mbps: '1' },
          ].map(preset => <button key={preset.label} type="button" disabled={busy || readOnly}
            className="min-h-11 rounded-lg border border-border px-2 py-2 text-xs font-medium hover:bg-muted disabled:opacity-50"
            onClick={() => { setProfile(preset.profile); setFps(preset.fps); setMbps(preset.mbps); }}>{preset.label}</button>)}
        </div>
        <label className="block text-sm font-medium">Профиль
          <select className={field} value={profile} disabled={busy || readOnly} onChange={e => setProfile(e.target.value as StreamQualitySettings['profile'])}>
            <option value="auto">Авто · по возможностям канала</option><option value="detail">Высокая детализация</option><option value="economy">Экономия трафика</option>
          </select>
        </label>
        <p className="text-xs leading-5 text-muted-foreground">{profile === 'detail' ? 'Повышенный битрейт для текста и движения. LAN · 60 FPS задаёт до 24 Мбит/с; возможности кодека и сети могут снизить этот предел. При перегрузке поток адаптируется.'
          : profile === 'economy' ? 'До 30 FPS и 2 Мбит/с, с сохранением исходного размера кадра.'
          : 'Поток увеличивает детализацию на быстром канале и снижает нагрузку при перегрузке. Быстрый прямой путь не ограничивается низким стартовым битрейтом.'}</p>
        <div className="grid grid-cols-1 gap-4 min-[360px]:grid-cols-2">
          <label className="block text-sm font-medium">Лимит FPS
            <input aria-label="Лимит FPS" className={field} type="number" inputMode="numeric" min="1" max="60" step="1" placeholder="Как на устройстве" value={fps} disabled={busy || readOnly} onChange={e => setFps(e.target.value)} />
            <span className="mt-1 block text-xs font-normal text-muted-foreground">Пусто — частота экрана, до 60 FPS</span>
          </label>
          <label className="block text-sm font-medium">Лимит битрейта, Мбит/с
            <input aria-label="Лимит битрейта, Мбит/с" className={field} type="number" inputMode="decimal" min="0.1" max="32" step="0.1" placeholder="Автоматически" value={mbps} disabled={busy || readOnly} onChange={e => setMbps(e.target.value)} />
            <span className="mt-1 block text-xs font-normal text-muted-foreground">Пусто — по размеру кадра и FPS</span>
          </label>
        </div>
        {!draft && <p role="alert" className="text-sm text-destructive">Укажите FPS от 1 до 60 и битрейт от 0,1 до 32 Мбит/с.</p>}
        {active && <div className="rounded-xl border border-border bg-muted/40 p-3 text-sm leading-6" aria-label="Текущие параметры Android">
          <p className="font-medium">{active.width} × {active.height} · цель {active.target_fps} FPS · {(active.target_bitrate_bps / 1_000_000).toFixed(1)} Мбит/с</p>
          <p className="text-xs text-muted-foreground">Экран {active.source_fps} Гц · кодек до {active.codec_max_fps} FPS · {active.adaptation === 'webrtc' ? 'адаптация WebRTC' : active.adaptation === 'legacy_queue' ? 'защита очереди сервера' : 'профиль источника'}</p>
          <p className="mt-1 text-xs text-muted-foreground">Это целевые параметры кодека. Фактический FPS зависит от захвата, нагрузки эмулятора и сети.</p>
        </div>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" disabled={busy} onClick={() => void read()} className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50"><RefreshCw className="h-3.5 w-3.5" />Обновить</button>
          <button type="submit" disabled={busy || readOnly || !draft || !changed} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">{busy ? 'Применяем…' : 'Применить'}</button>
        </div>
      </form>}
      {error && <p role="alert" className="text-sm leading-5 text-destructive">{error}</p>}
      {notice && <p role="status" className="text-sm leading-5 text-muted-foreground">{notice}</p>}
      {!snapshot && !busy && <button type="button" onClick={() => void read()} className="rounded-lg border border-border px-3 py-2 text-sm">Повторить чтение</button>}
    </DialogContent>
  </Dialog>;
}
