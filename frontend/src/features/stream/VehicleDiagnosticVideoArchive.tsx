'use client';
import {useEffect, useState} from 'react';
import {downloadVehicleDiagnosticVideo, listVehicleDiagnosticVideos} from './vehicleDiagnosticVideo';

export function VehicleDiagnosticVideoArchive({scope, refresh}: {scope: string; refresh: number}) {
  const [entries, setEntries] = useState<Awaited<ReturnType<typeof listVehicleDiagnosticVideos>>>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    let retired = false;
    setEntries([]);
    setError(false);
    void listVehicleDiagnosticVideos(scope).then(items => {
      if (!retired) setEntries(items);
    }).catch(() => { if (!retired) setError(true); });
    return () => { retired = true; };
  }, [scope, refresh]);
  return <details className="rounded-lg border p-3 text-xs">
    <summary className="cursor-pointer font-medium">Видео последних запусков транспорта · {entries.length}</summary>
    <p className="mt-2 text-muted-foreground">Архив аккаунта в этом браузере. Запись начинается с первого доступного ключевого кадра. Для анализа скачайте все три файла запуска.</p>
    {error && <p role="alert" className="mt-1">Не удалось открыть сохранённый файл.</p>}
    {entries.map(entry => <div key={entry.runId} className="mt-2 flex flex-wrap items-center gap-2">
      <span>{new Date(entry.beganAtMs).toLocaleString('ru-RU')} · маршрут {entry.clip.slice(0, 8)} · {(entry.durationTicks90k / 90000).toFixed(1)} с · {(entry.videoBytes / 1024 ** 2).toFixed(1)} МиБ{entry.endedEarly ? ' · запись закончилась до остановки транспорта' : ''}</span>
      <button type="button" className="rounded-md border px-2 py-1" onClick={() => { void downloadVehicleDiagnosticVideo(entry, 'video').catch(() => setError(true)); }}>Скачать H.264</button>
      <button type="button" className="rounded-md border px-2 py-1" onClick={() => { void downloadVehicleDiagnosticVideo(entry, 'index').catch(() => setError(true)); }}>Скачать индекс кадров</button>
      <button type="button" className="rounded-md border px-2 py-1" onClick={() => { void downloadVehicleDiagnosticVideo(entry, 'metadata').catch(() => setError(true)); }}>Скачать данные запуска</button>
    </div>)}
  </details>;
}
