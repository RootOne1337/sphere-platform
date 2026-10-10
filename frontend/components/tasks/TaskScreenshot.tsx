'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useTaskScreenshots } from '@/lib/hooks/useTasks';

export function TaskScreenshot({ taskId, screenshotKey, label = 'Снимок шага' }: {
  taskId: string; screenshotKey: string; label?: string;
}) {
  return <OwnedScreenshot key={`${taskId}:${screenshotKey}`} taskId={taskId} screenshotKey={screenshotKey} label={label} />;
}

function OwnedScreenshot({ taskId, screenshotKey, label }: {
  taskId: string; screenshotKey: string; label: string;
}) {
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [image, setImage] = useState<{ url: string; source: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const manifest = useTaskScreenshots(taskId, open);
  const entry = manifest.isSuccess ? manifest.data.screenshots.find(item => item.key === screenshotKey) : undefined;
  const contentUrl = open ? entry?.url : undefined;

  useEffect(() => {
    if (!contentUrl) { setImage(null); setLoading(false); return; }
    const controller = new AbortController();
    let disposed = false;
    let objectUrl: string | undefined;
    setImage(null); setError(null); setLoading(true);
    void api.get<Blob>(contentUrl, { responseType: 'blob', signal: controller.signal }).then(({ data }) => {
      if (disposed) return;
      if (!(data instanceof Blob) || !['image/jpeg', 'image/png'].includes(data.type) || data.size > 5 * 1024 * 1024) throw new Error('API вернул некорректный снимок');
      objectUrl = URL.createObjectURL(data);
      setImage({ url: objectUrl, source: contentUrl });
    }).catch(async failure => {
      if (disposed) return;
      // Axios retains JSON error bodies as Blob when responseType is blob.
      const response = failure?.response;
      let detail: string | undefined;
      if (response?.data instanceof Blob && response.data.size < 16_384) {
        try { const body = JSON.parse(await response.data.text()); if (typeof body?.detail === 'string') detail = body.detail; } catch { /* use status below */ }
      }
      if (disposed) return;
      const status = response?.status;
      setError(detail ?? (status === 404 ? 'Снимок отсутствует в хранилище или уже удалён.'
        : status === 503 ? 'Хранилище снимков недоступно или не настроено.'
          : getApiErrorMessage(failure, 'Не удалось загрузить снимок. Проверьте соединение и повторите.')));
    }).finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [contentUrl, attempt]);

  return <section aria-label={label} className="mt-3 min-w-0 space-y-3 rounded-lg border border-border bg-background p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-sm font-medium">{label}</span>
      <Button size="sm" variant="outline" onClick={() => setOpen(value => !value)}>{open ? 'Скрыть снимок' : 'Открыть снимок шага'}</Button>
    </div>
    <p className="break-all font-mono text-xs text-muted-foreground">{screenshotKey}</p>
    {open && <>
      {manifest.isPending && <p role="status" className="text-sm text-muted-foreground">Загрузка списка снимков…</p>}
      {manifest.isError && <div role="alert" className="space-y-2 text-sm">
        <p>{getApiErrorMessage(manifest.error, 'Не удалось получить список снимков.')}</p>
        <Button size="sm" variant="outline" onClick={() => void manifest.refetch()} disabled={manifest.isFetching}>Повторить загрузку списка снимков</Button>
      </div>}
      {manifest.isSuccess && !entry && <p role="alert" className="text-sm">Сервер не подтвердил этот снимок в результатах задания.</p>}
      {entry && !entry.url && <p role="alert" className="text-sm">Снимок недоступен: {entry.unavailable_reason ?? 'сервер не выдал ссылку'}.</p>}
      {contentUrl && loading && <p role="status" className="text-sm text-muted-foreground">Загрузка изображения…</p>}
      {contentUrl && error && <div role="alert" className="space-y-2 text-sm">
        <p>{error}</p>
        <Button size="sm" variant="outline" onClick={() => setAttempt(value => value + 1)}>Повторить загрузку снимка</Button>
      </div>}
      {contentUrl && !error && image?.source === contentUrl && <img src={image.url} alt={label}
        className="max-h-[65dvh] w-full rounded-md object-contain"
        onError={() => setError('Браузер не смог декодировать снимок. Повторите загрузку.')} />}
    </>}
  </section>;
}
