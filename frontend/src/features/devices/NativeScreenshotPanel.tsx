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
  useEffect(() => {
    const session = { disposed: false, controller: null as AbortController | null, url: null as string | null };
    sessionRef.current = session;
    setImage(null); setError(null); setPending(false);
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
      if (!session.disposed && sessionRef.current === session) setError(getApiErrorMessage(failure,
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
    {image && <><div className="overflow-hidden rounded-xl border border-border bg-muted/30"><img src={image.url} width={image.width} height={image.height} alt="Исходный снимок выбранного Android-устройства" className="mx-auto max-h-[72vh] max-w-full object-contain" /></div><dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2"><div><dt className="text-muted-foreground">Файл</dt><dd>{image.width} × {image.height} · {image.bytes.toLocaleString('ru-RU')} байт</dd></div><div><dt className="text-muted-foreground">Завершение запроса</dt><dd>{utcTime(image.capturedAt)}</dd></div><div className="min-w-0 sm:col-span-2"><dt className="text-muted-foreground">SHA-256 совпал: Android → сервер → браузер</dt><dd className="break-all font-mono text-xs">{image.sha256}</dd></div></dl>{!image.cleanupConfirmed && <p role="alert" className="text-sm text-amber-700 dark:text-amber-400">PNG получен, но удаление временных файлов на Android не подтверждено.</p>}<Button asChild variant="outline"><a href={image.url} download={image.filename}><Download className="mr-2 h-4 w-4" aria-hidden />Скачать исходный PNG</a></Button></>}
  </section>;
}
