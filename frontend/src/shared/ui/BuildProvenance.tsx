'use client';

import { useQuery } from '@tanstack/react-query';
import { GitCommitHorizontal } from 'lucide-react';
import { FRONTEND_BUILD_REVISION, FRONTEND_BUILD_SHA, formatBuildRevision, hasBuildRevisionMismatch } from '@/src/shared/buildInfo';

interface BackendBuildInfo {
  revision?: string;
  metadataSupported: boolean;
}

async function fetchBackendBuildInfo(): Promise<BackendBuildInfo> {
  const response = await fetch('/api/v1/health/build', {
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  });
  if (response.status === 404) return { metadataSupported: false };
  if (!response.ok) throw new Error(`Build info request failed (${response.status})`);

  const body: unknown = await response.json();
  if (!body || typeof body !== 'object' || !('revision' in body)) {
    throw new Error('Build info response is invalid');
  }
  const revision = (body as { revision?: unknown }).revision;
  return { revision: typeof revision === 'string' ? revision : undefined, metadataSupported: true };
}

export function BuildProvenance() {
  const backend = useQuery({
    queryKey: ['system', 'build-provenance'],
    queryFn: fetchBackendBuildInfo,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: false,
    refetchOnWindowFocus: true,
  });

  const backendRevision = backend.isSuccess
    ? backend.data.metadataSupported ? formatBuildRevision(backend.data.revision) : 'no metadata'
    : backend.isError
      ? 'unavailable'
      : 'checking';
  const revisionsMismatch = backend.isSuccess && hasBuildRevisionMismatch(FRONTEND_BUILD_SHA, backend.data.revision);
  const lookupNote = backend.data?.metadataSupported === false
    ? 'Endpoint версии сборки отсутствует (HTTP 404). Это не проверка работоспособности API.'
    : backend.isError ? 'Не удалось прочитать версию сборки. Это не проверка работоспособности API.' : 'Версия сборки API; обновление раз в минуту. Это не проверка работоспособности API.';

  return (
    <span
      role="status"
      aria-label={`Build revisions. Frontend ${FRONTEND_BUILD_REVISION}; backend ${backendRevision}${revisionsMismatch ? '; revisions mismatch' : ''}`}
      title={`Frontend commit: ${FRONTEND_BUILD_REVISION}\nBackend commit: ${backendRevision}\n${lookupNote}${revisionsMismatch ? '\nThe frontend and backend are from different commits.' : ''}`}
      className={`flex h-8 min-w-0 max-w-[9rem] shrink items-center gap-1.5 rounded-md border px-2 font-mono text-[10px] tracking-tight lg:max-w-none ${revisionsMismatch ? 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300' : 'border-border/70 bg-muted/40 text-muted-foreground'}`}
    >
      <GitCommitHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
      <span className="hidden whitespace-nowrap lg:inline">WEB {FRONTEND_BUILD_REVISION} <span aria-hidden="true" className="text-muted-foreground/60">·</span> API {backendRevision}</span>
      <span className="min-w-0 truncate lg:hidden">W:{FRONTEND_BUILD_REVISION} A:{backendRevision}</span>
      {revisionsMismatch && <><span className="hidden font-sans font-semibold text-amber-700 dark:text-amber-300 lg:inline">MISMATCH</span><span aria-hidden="true" className="font-sans font-semibold text-amber-700 dark:text-amber-300 lg:hidden">!</span></>}
    </span>
  );
}
