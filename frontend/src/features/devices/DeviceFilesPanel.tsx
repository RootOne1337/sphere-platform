'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Download, File, FolderOpen, Loader2, RefreshCw, Upload } from 'lucide-react';
import { api } from '@/lib/api';
import { assertSession, useAuthStore } from '@/lib/store';
import { Button } from '@/src/shared/ui/button';
import { utcTime } from './DeviceOperationsPanels';

const MAX_FILE_BYTES = 256 * 1024;
const MAX_FILE_COUNT = 100;
const FILE_TIMEOUT = 25_000;
const FILE_NAME = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$/;
const SHA256 = /^[a-f0-9]{64}$/;

type FileEntry = { name: string; size: number; modified_at_ms: number };
type FileDirectory = { version: 1; max_bytes: number; files: FileEntry[] };
type Receipt = { name: string; size: number; sha256: string };
type Transfer =
  | { action: 'upload'; receipt: Receipt }
  | { action: 'download'; receipt: Receipt; url: string };
type Failure = { message: string; reconcile: boolean };

const PROBLEMS = {
  file_exchange_unsupported: 'Установленная версия Sphere Agent не поддерживает обмен файлами.',
  file_exchange_offline: 'Android-агент сейчас недоступен. Проверьте связь с устройством.',
  file_exchange_busy: 'Файловая операция на устройстве ещё выполняется. Повторите запрос после её завершения.',
  file_exists: 'В папке уже есть файл с таким именем. Выберите файл с другим именем.',
  file_not_found: 'Файл больше не находится в папке. Обновите список.',
  file_quota_exceeded: 'В рабочей папке устройства закончилась квота.',
  file_too_large: 'Файл превышает допустимый размер.',
  file_invalid_name: 'Используйте до 120 латинских букв, цифр, пробелов, точек, дефисов или подчёркиваний. Начните с буквы или цифры и уберите точку или пробел в конце.',
  file_integrity_failed: 'Контрольная сумма не совпала. Проверьте исходный файл.',
  file_exchange_failed: 'Устройство не подтвердило файловую операцию.',
  file_exchange_unknown: 'Результат загрузки неизвестен. Обновите список и проверьте, появился ли файл.',
} as const;

type ProblemCode = keyof typeof PROBLEMS;

class FileTransferError extends Error {
  constructor(readonly code: ProblemCode | 'browser_integrity_unavailable' | 'invalid_file_response') {
    super(code);
  }
}

function isFileName(value: unknown): value is string {
  return typeof value === 'string' && FILE_NAME.test(value) && !/[.\s]$/.test(value);
}

function validFileSize(value: unknown, max: number): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max;
}

function parseFileList(data: unknown): FileDirectory {
  if (!data || typeof data !== 'object') throw new FileTransferError('invalid_file_response');
  const list = data as Partial<FileDirectory>;
  if (list.version !== 1 || !validFileSize(list.max_bytes, MAX_FILE_BYTES) || list.max_bytes === 0
    || !Array.isArray(list.files) || list.files.length > MAX_FILE_COUNT) {
    throw new FileTransferError('invalid_file_response');
  }
  const names = new Set<string>();
  for (const item of list.files) {
    if (!item || !isFileName(item.name) || names.has(item.name) || !validFileSize(item.size, list.max_bytes)
      || !Number.isSafeInteger(item.modified_at_ms) || item.modified_at_ms < 0 || item.modified_at_ms > 8.64e15) {
      throw new FileTransferError('invalid_file_response');
    }
    names.add(item.name);
  }
  return { version: list.version, max_bytes: list.max_bytes, files: list.files };
}

function problemCode(error: unknown): ProblemCode | null {
  let data = (error as { response?: { data?: unknown } } | null)?.response?.data;
  if (data instanceof ArrayBuffer && data.byteLength <= 4096) {
    try { data = JSON.parse(new TextDecoder().decode(data)); }
    catch { return null; }
  }
  const detail = (data as { detail?: unknown } | null)?.detail;
  const code = error instanceof FileTransferError ? error.code : detail;
  return typeof code === 'string' && Object.hasOwn(PROBLEMS, code) ? code as ProblemCode : null;
}

function describeFailure(error: unknown, writeSubmitted = false): Failure {
  const code = problemCode(error);
  if (code) {
    return {
      message: PROBLEMS[code],
      reconcile: code === 'file_exchange_unknown'
        || (writeSubmitted && (code === 'file_integrity_failed' || code === 'file_exchange_failed')),
    };
  }
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  if (status === 401 || status === 403) return { message: 'Для файловой операции требуется доступ к управлению устройством.', reconcile: false };
  if (status === 429) return { message: 'Слишком много файловых запросов. Повторите позже.', reconcile: false };
  if (error instanceof FileTransferError && error.code === 'browser_integrity_unavailable') {
    return { message: 'Проверка целостности доступна в защищённом контексте браузера. Откройте Sphere по HTTPS или через localhost.', reconcile: false };
  }
  if (writeSubmitted) return { message: PROBLEMS.file_exchange_unknown, reconcile: true };
  return { message: 'Не удалось получить подтверждённые данные от устройства.', reconcile: false };
}

async function fileDigest(data: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new FileTransferError('browser_integrity_unavailable');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}

async function verifyDownload(data: ArrayBuffer, headers: Record<string, unknown>, limit: number): Promise<string> {
  if (!(data instanceof ArrayBuffer) || !validFileSize(data.byteLength, limit)
    || String(headers['content-type']).split(';')[0] !== 'application/octet-stream'
    || headers['content-length'] !== String(data.byteLength)) {
    throw new FileTransferError('invalid_file_response');
  }
  const sha256 = headers['x-content-sha256'];
  if (typeof sha256 !== 'string' || !SHA256.test(sha256) || await fileDigest(data) !== sha256) {
    throw new FileTransferError('file_integrity_failed');
  }
  return sha256;
}

function fileSize(size: number): string {
  if (size < 1024) return size.toLocaleString('ru-RU') + ' Б';
  return (size / 1024).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' КиБ';
}

export function DeviceFilesPanel({ deviceId, enabled }: { deviceId: string; enabled: boolean }) {
  const session = useAuthStore(state => state.sessionVersion);
  return <DeviceFileWorkspace key={JSON.stringify([deviceId, session])} deviceId={deviceId} enabled={enabled} session={session} />;
}

function DeviceFileWorkspace({ deviceId, enabled, session }: { deviceId: string; enabled: boolean; session: number }) {
  const basePath = '/devices/' + encodeURIComponent(deviceId) + '/files';
  const input = useRef<HTMLInputElement>(null);
  const active = useRef<AbortController | null>(null);
  const objectUrl = useRef<string | null>(null);
  const [selected, setSelected] = useState<globalThis.File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pending, setPending] = useState<'upload' | 'download' | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [needsReview, setNeedsReview] = useState(false);
  const [transfer, setTransfer] = useState<Transfer | null>(null);
  const query = useQuery({
    queryKey: ['device-files', session, deviceId],
    queryFn: async ({ signal }) => {
      const { data } = await api.get<unknown>(basePath, { signal, timeout: FILE_TIMEOUT });
      return parseFileList(data);
    },
    enabled, retry: false, refetchOnWindowFocus: false, gcTime: 0,
  });
  const listing = enabled && query.isSuccess ? query.data : undefined;
  const canTransfer = Boolean(listing) && !query.isFetching && !pending && !needsReview;
  const limit = listing?.max_bytes ?? MAX_FILE_BYTES;
  const listFailure = enabled && query.isError ? describeFailure(query.error) : null;

  useEffect(() => () => {
    active.current?.abort();
    active.current = null;
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
  }, []);

  const choose = (files: FileList | null) => {
    if (!canTransfer || !files?.length) return;
    setFailure(null);
    if (files.length !== 1) {
      setSelected(null);
      setFailure({ message: 'Выберите один файл для передачи.', reconcile: false });
      return;
    }
    const file = files[0];
    const code = !isFileName(file.name) ? 'file_invalid_name'
      : file.size > limit ? 'file_too_large'
      : listing?.files.some(entry => entry.name === file.name) ? 'file_exists' : null;
    if (code) {
      setSelected(null);
      setFailure(describeFailure(new FileTransferError(code)));
      return;
    }
    setSelected(file);
  };

  const refresh = async () => {
    if (!enabled || query.isFetching || active.current) return;
    const result = await query.refetch();
    if (result.isSuccess && needsReview) {
      setNeedsReview(false);
      setFailure(null);
      setSelected(null);
    }
  };

  const run = async (transfer: { action: 'upload'; file: globalThis.File } | { action: 'download'; file: FileEntry }) => {
    const { action, file } = transfer;
    if (!canTransfer || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setPending(action);
    setFailure(null);
    setTransfer(null);
    if (objectUrl.current) {
      URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    }
    const options = { signal: controller.signal, timeout: FILE_TIMEOUT };
    const path = basePath + '/' + encodeURIComponent(file.name);
    let writeSubmitted = false;
    try {
      assertSession(session);
      if (action === 'upload') {
        const bytes = await file.arrayBuffer();
        const sha256 = await fileDigest(bytes);
        assertSession(session);
        if (controller.signal.aborted) return;
        writeSubmitted = true;
        const { data } = await api.post<Receipt>(path, bytes, {
          ...options, headers: { 'Content-Type': 'application/octet-stream', 'X-Content-SHA256': sha256 },
        });
        if (!data || data.name !== file.name || data.size !== bytes.byteLength || data.sha256 !== sha256) {
          throw new FileTransferError('invalid_file_response');
        }
        assertSession(session);
        if (controller.signal.aborted) return;
        setTransfer({ action, receipt: data });
        setSelected(null);
        await query.refetch();
      } else {
        const { data, headers } = await api.get<ArrayBuffer>(path, { ...options, responseType: 'arraybuffer' });
        const sha256 = await verifyDownload(data, headers as Record<string, unknown>, limit);
        if (data.byteLength !== file.size) throw new FileTransferError('file_integrity_failed');
        assertSession(session);
        if (controller.signal.aborted) return;
        const url = URL.createObjectURL(new Blob([data], { type: 'application/octet-stream' }));
        objectUrl.current = url;
        setTransfer({ action: 'download', url, receipt: { name: file.name, size: data.byteLength, sha256 } });
      }
    } catch (error) {
      if (!controller.signal.aborted && useAuthStore.getState().sessionVersion === session) {
        const problem = describeFailure(error, writeSubmitted);
        setFailure(problem);
        if (problem.reconcile) setNeedsReview(true);
      }
    } finally {
      if (active.current === controller) {
        active.current = null;
        setPending(null);
      }
    }
  };

  return <section aria-labelledby="device-files-title" className="min-w-0 overflow-hidden rounded-2xl border border-border bg-card">
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border p-4 sm:p-5">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><FolderOpen className="size-5" aria-hidden /></span>
        <div className="min-w-0">
          <h4 id="device-files-title" className="font-semibold">Рабочая папка Android</h4>
          <p className="mt-0.5 text-xs text-muted-foreground">Sphere Agent · до {fileSize(limit)} на файл</p>
        </div>
      </div>
      <Button type="button" variant="outline" size="sm" disabled={!enabled || query.isFetching || Boolean(pending)} onClick={() => { void refresh(); }}>
        <RefreshCw className={query.isFetching ? 'size-4 animate-spin motion-reduce:animate-none' : 'size-4'} aria-hidden />Обновить
      </Button>
    </header>
    <div className="space-y-4 p-4 sm:p-5">
      {!enabled && <p role="status" className="rounded-xl border border-border bg-muted/30 p-3 text-sm text-muted-foreground">Обмен файлами доступен, когда Android-агент на связи.</p>}
      {enabled && query.isPending && <p role="status" className="text-sm text-muted-foreground">Читаем рабочую папку Android…</p>}
      {listFailure && <p role="alert" className="rounded-xl border border-border bg-muted/30 p-3 text-sm">{listFailure.message}</p>}
      {listing && <>
        <div className={'rounded-xl border border-dashed p-4 transition-colors motion-reduce:transition-none ' + (dragging ? 'border-primary bg-primary/10' : 'border-border bg-muted/20')}
          onDragOver={event => { event.preventDefault(); if (canTransfer) setDragging(true); }}
          onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
          onDrop={event => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files); }}>
          <input ref={input} type="file" aria-label="Файл с компьютера" className="hidden" onChange={event => {
            choose(event.target.files); event.target.value = '';
          }} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="break-all text-sm font-medium">{selected?.name ?? 'Добавить файл с компьютера'}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{selected ? fileSize(selected.size) : 'Перетащите файл сюда или выберите его на компьютере.'}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" disabled={!canTransfer} onClick={() => input.current?.click()}>
                <File className="size-4" aria-hidden />{selected ? 'Заменить выбор' : 'Выбрать файл'}
              </Button>
              {selected && <Button type="button" size="sm" disabled={!canTransfer} onClick={() => { void run({ action: 'upload', file: selected }); }}>
                <Upload className="size-4" aria-hidden />На устройство
              </Button>}
            </div>
          </div>
        </div>
        {listing.files.length ? <ul aria-label="Файлы на устройстве" className="divide-y divide-border rounded-xl border border-border">
          {listing.files.map(file => <li key={file.name} className="flex items-center gap-3 px-3 py-3 sm:px-4">
            <File className="hidden size-5 shrink-0 text-muted-foreground sm:block" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="break-all text-sm font-medium">{file.name}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{fileSize(file.size)} · {utcTime(new Date(file.modified_at_ms).toISOString())}</p>
            </div>
            <Button type="button" variant="outline" size="sm" aria-label={'Скачать ' + file.name} disabled={!canTransfer}
              onClick={() => { void run({ action: 'download', file }); }}><Download className="size-4" aria-hidden /><span className="hidden sm:inline">Скачать</span></Button>
          </li>)}
        </ul> : <p className="rounded-xl border border-border px-4 py-5 text-sm text-muted-foreground">Рабочая папка пока пуста.</p>}
      </>}
      {pending && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        {pending === 'upload' ? 'Передаём файл и ждём подтверждение Android…' : 'Получаем файл и проверяем SHA-256…'}
      </p>}
      {failure && <p role="alert" className="break-words rounded-xl border border-destructive/30 p-3 text-sm text-destructive">{failure.message}</p>}
      {transfer && <div role="status" className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-border bg-muted/30 p-3 text-sm">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-medium"><CheckCircle2 className="size-4 shrink-0 text-primary" aria-hidden />
            {transfer.action === 'upload' ? 'Android подтвердил запись файла' : 'Файл готов к сохранению'}
          </p>
          <p className="mt-1 break-all text-xs text-muted-foreground">{transfer.receipt.name} · {fileSize(transfer.receipt.size)}</p>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">SHA-256 {transfer.receipt.sha256}</p>
        </div>
        {transfer.action === 'download' && <Button asChild size="sm"><a href={transfer.url} download={transfer.receipt.name}>
          <Download className="size-4" aria-hidden />Сохранить
        </a></Button>}
      </div>}
    </div>
  </section>;
}
