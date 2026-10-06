'use client';

import { useEffect, useRef, useState } from 'react';
import { Camera, Download, Loader2 } from 'lucide-react';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/src/shared/ui/button';
import { utcTime } from './DeviceOperationsPanels';

type Screenshot = { url: string; filename: string; width: number; height: number; bytes: number;
  sha256: string; capturedAt: string; cleanupConfirmed: boolean };

const capturePhases: Record<string, string> = {
  display_before: 'геометрия до съёмки', capture: 'съёмка Android', file_size: 'размер файла',
  android_digest: 'контрольная сумма Android', chunk_copy: 'подготовка блока', chunk_read: 'передача блока',
  display_after: 'геометрия после съёмки', validate_png: 'проверка PNG',
};

export function nativeCaptureError(failure: unknown): string {
  const fallback = 'Исходный снимок не получен.';
  if (typeof failure !== 'object' || failure === null) return fallback;
  const candidate = failure as { response?: { data?: unknown; headers?: Record<string, unknown> } };
  let data = candidate.response?.data;
  // Axios keeps error bodies as ArrayBuffer for this binary endpoint too.
  // Decode only a small JSON body; never show arbitrary binary/command data.
  if (data instanceof ArrayBuffer || Object.prototype.toString.call(data) === '[object ArrayBuffer]') {
    const binary = data as ArrayBuffer;
    if (!Number.isInteger(binary.byteLength) || binary.byteLength > 16 * 1024) data = undefined;
    else { try { data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(binary)); } catch { data = undefined; } }
  }
  const detail = typeof data === 'object' && data !== null ? (data as { detail?: unknown }).detail : undefined;
  const message = typeof detail === 'string' && detail.trim() && detail.length <= 512 ? detail : fallback;
  const headers = candidate.response?.headers;
  const id = headers?.['x-screenshot-id'], phase = headers?.['x-screenshot-failed-phase'];
  if (typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id)
    || typeof phase !== 'string' || !Object.hasOwn(capturePhases, phase)) return message;
  const elapsed = headers?.['x-screenshot-elapsed-ms'];
  const timing = typeof elapsed === 'string' && /^\d{1,6}$/.test(elapsed) ? ` · ${Number(elapsed).toLocaleString('ru-RU')} мс` : '';
  const cleanup = headers?.['x-screenshot-cleanup-confirmed'] === 'false' ? ' Удаление временных файлов не подтверждено.' : '';
  return `${message} Этап: ${capturePhases[phase]}${timing}. Запрос: ${id}.${cleanup}`;
}

export async function verifyNativeScreenshot(data: ArrayBuffer, headers: Record<string, unknown>, deviceId: string) {
  const bytes = new Uint8Array(data);
  if (bytes.length < 57 || bytes.length > 5 * 1024 * 1024
    || ![137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value)
    || String(headers['content-type']).split(';')[0] !== 'image/png'
    || headers['x-screenshot-device-id'] !== deviceId) throw new Error('API не вернул исходный PNG выбранного устройства.');
  const view = new DataView(data);
  const width = view.getUint32(16), height = view.getUint32(20);
  const id = headers['x-screenshot-id'], sha256 = headers['x-screenshot-sha256'];
  const capturedAt = headers['x-screenshot-completed-at'], requestedAt = headers['x-screenshot-requested-at'];
  if (!width || !height || width > 4096 || height > 4096
    || String(width) !== headers['x-screenshot-width'] || String(height) !== headers['x-screenshot-height']
    || typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id)
    || typeof sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(sha256)
    || headers['x-screenshot-android-sha256'] !== sha256
    || typeof capturedAt !== 'string' || !Number.isFinite(Date.parse(capturedAt))
    || typeof requestedAt !== 'string' || !Number.isFinite(Date.parse(requestedAt))
    || Date.parse(capturedAt) < Date.parse(requestedAt)
    || !['true', 'false'].includes(String(headers['x-screenshot-cleanup-confirmed']))) {
    throw new Error('API вернул неполные сведения об исходном PNG.');
  }
  if (!crypto.subtle) throw new Error('Браузер не позволяет проверить целостность PNG.');
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)), b => b.toString(16).padStart(2, '0')).join('');
  if (hash !== sha256) throw new Error('Контрольная сумма PNG не совпала; файл не сохраняется.');
  return { filename: `sphere-${deviceId}-${id}.png`, width, height, bytes: bytes.length, sha256, capturedAt,
    cleanupConfirmed: headers['x-screenshot-cleanup-confirmed'] === 'true' };
}

export function NativeScreenshotPanel({ deviceId, enabled }: { deviceId: string; enabled: boolean }) {
  const { accessToken } = useAuthStore();
  const sessionRef = useRef<{ disposed: boolean; controller: AbortController | null; url: string | null } | null>(null);
  const [image, setImage] = useState<Screenshot | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewScale, setPreviewScale] = useState<'fit' | 'native'>('fit');
  useEffect(() => {
    const session = { disposed: false, controller: null as AbortController | null, url: null as string | null };
    sessionRef.current = session;
    setImage(null); setError(null); setPending(false); setPreviewScale('fit');
    return () => {
      session.disposed = true;
      session.controller?.abort();
      if (session.url) URL.revokeObjectURL(session.url);
      if (sessionRef.current === session) sessionRef.current = null;
    };
  }, [deviceId, accessToken, enabled]);
  const capture = async () => {
    const session = sessionRef.current;
    if (!enabled || !session || session.disposed || session.controller) return;
    const controller = new AbortController(); session.controller = controller;
    setPending(true); setError(null);
    try {
      const response = await api.post<ArrayBuffer>(`/devices/${encodeURIComponent(deviceId)}/screenshot/native`, {}, {
        signal: controller.signal, timeout: 100_000, responseType: 'arraybuffer',
      });
      const metadata = await verifyNativeScreenshot(response.data, response.headers as Record<string, unknown>, deviceId);
      if (session.disposed || sessionRef.current !== session) return;
      const url = URL.createObjectURL(new Blob([response.data], { type: 'image/png' }));
      if (session.url) URL.revokeObjectURL(session.url);
      session.url = url; setImage({ ...metadata, url });
    } catch (failure) {
      if (!session.disposed && sessionRef.current === session) setError(
        candidateHasResponse(failure) ? nativeCaptureError(failure) : getApiErrorMessage(failure,
          failure instanceof Error ? failure.message : 'Исходный снимок не получен.'));
    } finally {
      if (!session.disposed && sessionRef.current === session) { session.controller = null; setPending(false); }
    }
  };
  return <section aria-label="Исходный снимок экрана Android" className="min-w-0 space-y-4 rounded-xl border border-border bg-card p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div className="space-y-1"><h4 className="font-semibold">Исходный снимок экрана</h4><p className="text-sm text-muted-foreground">PNG с Android · родное разрешение · без перекодирования и уменьшения.</p></div><Button disabled={!enabled || pending} onClick={() => { void capture(); }}>{pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden /> : <Camera className="mr-2 h-4 w-4" aria-hidden />}Получить снимок</Button></div>
    <p className="text-xs leading-relaxed text-muted-foreground">Разовый запрос через APK с root-доступом, до 5 MiB. PNG сохраняет пиксели без потерь. DPI в свойствах файла относится к физическому размеру изображения; плотность интерфейса Android — отдельная настройка. Автоматического опроса нет.</p>
    {pending && <p role="status" className="text-sm text-muted-foreground">Android делает снимок и передаёт файл. Ожидаем полный PNG и проверяем SHA-256…</p>}
    {error && <p role="alert" className="break-words rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error} Автоповтора нет.{image ? ' Ниже предыдущий успешно полученный снимок.' : ''}</p>}
    {image && <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Масштаб просмотра снимка" className="flex flex-wrap gap-1">
          <Button size="sm" variant={previewScale === 'fit' ? 'secondary' : 'outline'} aria-pressed={previewScale === 'fit'} onClick={() => setPreviewScale('fit')}>Вписать в панель</Button>
          <Button size="sm" variant={previewScale === 'native' ? 'secondary' : 'outline'} aria-pressed={previewScale === 'native'} onClick={() => setPreviewScale('native')}>100% · 1:1</Button>
        </div>
        <p className="text-xs text-muted-foreground">{previewScale === 'native' ? 'Один пиксель PNG на один CSS-пиксель; браузерный масштаб влияет на отображение.' : 'Предпросмотр уменьшен по размеру панели. Скачиваемый PNG остаётся исходным.'}</p>
      </div>
      <div aria-label="Предпросмотр исходного PNG" className="max-h-[72vh] overflow-auto rounded-xl border border-border bg-muted/30">
        <img src={image.url} width={image.width} height={image.height} alt="Исходный снимок выбранного Android-устройства" className={previewScale === 'native' ? 'mx-auto block max-w-none' : 'mx-auto block max-h-[72vh] max-w-full object-contain'} style={previewScale === 'native' ? { width: image.width, height: image.height } : undefined} />
      </div>
      <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2"><div><dt className="text-muted-foreground">Файл</dt><dd>{image.width} × {image.height} · {image.bytes.toLocaleString('ru-RU')} байт</dd></div><div><dt className="text-muted-foreground">Завершение запроса</dt><dd>{utcTime(image.capturedAt)}</dd></div><div className="min-w-0 sm:col-span-2"><dt className="text-muted-foreground">SHA-256 совпал: Android → сервер → браузер</dt><dd className="break-all font-mono text-xs">{image.sha256}</dd></div></dl>{!image.cleanupConfirmed && <p role="alert" className="text-sm text-amber-700 dark:text-amber-400">PNG получен, но удаление временных файлов на Android не подтверждено.</p>}<Button asChild variant="outline"><a href={image.url} download={image.filename}><Download className="mr-2 h-4 w-4" aria-hidden />Скачать исходный PNG</a></Button>
    </>}
  </section>;
}

function candidateHasResponse(value: unknown): boolean {
  return typeof value === 'object' && value !== null && 'response' in value;
}
