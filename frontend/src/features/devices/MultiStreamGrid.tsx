'use client';

import React, { useState } from 'react';
import { Play, Pause, X, MonitorPlay, Activity, Cpu, Maximize2, Minimize2 } from 'lucide-react';
import { Device } from '@/lib/hooks/useDevices';
import { isDeviceReachable } from '@/src/features/devices/deviceListFilters';
import { getReportedDeviceModel } from './devicePresentation';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { useStreamStore, GRID_SIZE_OPTIONS, gridColumns, gridLabel } from '@/src/shared/store/useStreamStore';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { useStreamFullscreen } from '@/src/features/stream/useStreamFullscreen';

interface MultiStreamGridProps {
    devices: Device[];
    selectedIds?: string[];
    onClose?: () => void;
}

/**
 * MultiStreamGrid — отображение сетки видеопотоков с эмуляторов.
 *
 * Ключевое изменение: добавлена кнопка START/STOP BROADCAST,
 * которая управляет подключением реальных WS-стримов через DeviceStream.
 * Стримы НЕ подключаются автоматически — это экономит ресурсы при 1К+ устройствах.
 */
export function MultiStreamGrid({ devices, selectedIds, onClose }: MultiStreamGridProps) {
    const { gridSize, objectFit, showHUD, showStats, setGridSize, setObjectFit, toggleHUD, toggleStats } = useStreamStore();

    // Глобальный стейт вещания: стримы включаются только по кнопке
    const [broadcastActive, setBroadcastActive] = useState(false);
    const fullscreen = useStreamFullscreen();

    // Если оператор выделил устройства в таблице, стримим именно их. Без
    // выделения сетка показывает начало текущего отфильтрованного списка.
    const selectedSet = new Set(selectedIds ?? []);
    const streamCandidates = selectedSet.size > 0
        ? devices.filter((device) => selectedSet.has(device.id))
        : devices;
    const visibleDevices = streamCandidates.slice(0, gridSize);
    const columns = Math.min(gridColumns(gridSize), Math.max(1, visibleDevices.length));

    const formatCpu = (value: number | null) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%` : '—';
    const formatHeartbeatAge = (timestamp: string | null) => {
        if (!timestamp) return 'нет данных';
        const seenAt = Date.parse(timestamp);
        if (!Number.isFinite(seenAt)) return 'время неизвестно';
        const seconds = Math.max(0, Math.floor((Date.now() - seenAt) / 1000));
        if (seconds < 60) return `${seconds} сек назад`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes} мин назад`;
        const hours = Math.floor(minutes / 60);
        return `${hours} ч назад`;
    };

    return (
        <div ref={fullscreen.ref} className={`stream-wall flex min-h-0 min-w-0 flex-col border border-border bg-card ${fullscreen.active ? 'h-[100dvh] w-full' : 'h-full rounded-xl'}`}>
            <header className="shrink-0 space-y-3 border-b border-border bg-card p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                        <MonitorPlay className="h-4 w-4 shrink-0 text-primary" aria-hidden />
                        <h2 className="text-sm font-semibold">Видеостена</h2>
                        <Badge variant="outline" className={broadcastActive ? 'border-primary/20 bg-primary/10 text-primary' : 'text-muted-foreground'}>
                            {broadcastActive ? 'В эфире' : 'Ожидание'}
                        </Badge>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {fullscreen.available && <Button variant="ghost" size="sm" aria-label={fullscreen.active ? 'Свернуть видеостену' : 'Развернуть видеостену'} aria-pressed={fullscreen.active} onClick={() => void fullscreen.toggle()}>
                            {fullscreen.active ? <Minimize2 className="size-3.5" aria-hidden /> : <Maximize2 className="size-3.5" aria-hidden />}<span className="hidden sm:inline">{fullscreen.active ? 'Свернуть' : 'Развернуть'}</span>
                        </Button>}
                        <Button variant={broadcastActive ? 'secondary' : 'default'} size="sm"
                            onClick={() => setBroadcastActive(!broadcastActive)}
                            aria-label={broadcastActive ? 'Остановить вещание' : 'Запустить вещание'}>
                            {broadcastActive ? <><Pause className="h-3.5 w-3.5" aria-hidden />Приостановить</> : <><Play className="h-3.5 w-3.5" aria-hidden />Запустить</>}
                        </Button>
                        {onClose && <Button variant="ghost" size="sm" aria-label="Остановить потоки" onClick={() => { setBroadcastActive(false); onClose(); }}>
                            <X className="h-3.5 w-3.5" aria-hidden />Закрыть
                        </Button>}
                    </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <label className="flex items-center gap-2 text-xs text-muted-foreground">Сетка
                        <select data-ui="select" aria-label="Размер сетки потоков" value={gridSize} onChange={event => { const size = GRID_SIZE_OPTIONS.find(item => item === Number(event.target.value)); if (size !== undefined) setGridSize(size); }}
                            className="h-[var(--control-sm-height)] rounded-md border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                            {GRID_SIZE_OPTIONS.map(size => <option key={size} value={size}>{gridLabel(size)}</option>)}
                        </select>
                    </label>
                    <Button variant={showHUD ? 'secondary' : 'ghost'} size="sm" aria-pressed={showHUD} onClick={toggleHUD}>Метки</Button>
                    <Button variant={showStats ? 'secondary' : 'ghost'} size="sm" aria-pressed={showStats} onClick={toggleStats}>Статистика</Button>
                    <Button variant="ghost" size="sm" aria-label="Изменить масштаб видео" aria-pressed={objectFit === 'cover'} onClick={() => setObjectFit(objectFit === 'contain' ? 'cover' : 'contain')}>
                        {objectFit === 'contain' ? 'Вписать' : 'Заполнить'}
                    </Button>
                </div>
            </header>
            {fullscreen.error && <p role="status" className="px-3 py-2 text-xs text-amber-600 dark:text-amber-400">{fullscreen.error}</p>}
            {streamCandidates.length > visibleDevices.length && (
                <p role="status" className="shrink-0 border-b border-border bg-card px-3 py-2 text-xs text-muted-foreground">
                    Показаны первые {visibleDevices.length} из {streamCandidates.length} устройств. Увеличьте размер сетки или сузьте выбор, чтобы открыть остальные потоки.
                </p>
            )}

            {/* Matrix Grid */}
            <div
                className="stream-wall-cells custom-scrollbar grid min-h-0 flex-1 gap-3 overflow-x-hidden overflow-y-auto bg-background p-3"
                style={{ '--stream-columns': columns, '--stream-narrow-columns': Math.min(columns, 2) } as React.CSSProperties}
            >
                {visibleDevices.map((device) => {
                    const reachable = isDeviceReachable(device);
                    return (
                    <div key={device.id} className="stream-wall-tile relative flex min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-card" aria-label={`Поток ${device.name}`}>
                        {/* Video Layer */}
                        <div
                            className="stream-wall-stage relative flex aspect-video min-h-0 w-full flex-col items-center justify-center overflow-hidden bg-black"
                        >
                            {broadcastActive && reachable ? (
                                /* Реальный видео-стрим через WebSocket H.264 */
                                <DeviceStream compact readOnly showOverlayTools={false} deviceId={device.id} fit={objectFit} />
                            ) : reachable ? (
                                /* Онлайн, но стрим не включён — показываем готовность */
                                <div className="stream-wall-placeholder flex h-full w-full flex-col items-center justify-center gap-2 bg-background text-muted-foreground">
                                    <Play className="w-6 h-6 opacity-30" />
                                    <span className="text-xs font-medium">Готов к просмотру</span>
                                    <span className="stream-wall-help text-xs text-muted-foreground">Нажмите «Запустить»</span>
                                </div>
                            ) : (
                                /* Оффлайн */
                                <div className="stream-wall-placeholder flex h-full w-full flex-col items-center justify-center gap-2 bg-background text-muted-foreground">
                                    <X className="w-6 h-6 opacity-30" />
                                    <span className="text-xs font-medium">Устройство не в сети</span>
                                    <span className="stream-wall-help text-xs text-muted-foreground">Проверьте heartbeat и доступность устройства</span>
                                </div>
                            )}

                            {/* HUD Overlays */}
                            {reachable && showHUD && (
                                <div className="absolute top-2 left-2 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity bg-black/40 backdrop-blur-md px-1.5 py-0.5 rounded-sm border border-white/5">
                                    <div className={`w-1.5 h-1.5 rounded-full ${broadcastActive ? 'bg-success animate-pulse' : 'bg-warning'}`} />
                                    <span className="text-[9px] font-mono font-bold text-white shadow-black drop-shadow-md tracking-wider">{device.id.slice(0, 8)}</span>
                                </div>
                            )}
                        </div>

                        <footer className="shrink-0 space-y-1 border-t border-border bg-card px-2 py-2">
                            <div className="flex min-w-0 items-center justify-between gap-2"><span className="min-w-0 truncate text-xs font-semibold" title={device.name}>{device.name}</span>
                                {showStats && reachable && <span className="inline-flex shrink-0 items-center gap-1 text-[10px] tabular-nums text-muted-foreground" title="Загрузка CPU по отчёту APK"><Cpu className="h-2.5 w-2.5" aria-hidden />{formatCpu(device.cpu_usage)}</span>}
                            </div>
                            <div className="flex min-w-0 items-center justify-between gap-2"><span className="min-w-0 truncate text-[10px] text-muted-foreground" title={getReportedDeviceModel(device) ?? undefined}>{getReportedDeviceModel(device) ?? 'Модель не сообщена'}</span>
                                {showStats && reachable && <span className="inline-flex shrink-0 items-center gap-1 text-[10px] text-muted-foreground" title={`Heartbeat · ${formatHeartbeatAge(device.last_heartbeat)}`} aria-label={`Heartbeat · ${formatHeartbeatAge(device.last_heartbeat)}`}><Activity className="h-2.5 w-2.5" aria-hidden />{formatHeartbeatAge(device.last_heartbeat).replace(' сек назад', 'с').replace(' мин назад', 'м').replace(' ч назад', 'ч')}</span>}
                            </div>
                        </footer>

                    </div>
                    );
                })}

                {!visibleDevices.length && <p className="col-span-full p-6 text-center text-sm text-muted-foreground">В выбранной области нет устройств. Измените фильтры или выбор.</p>}

            </div>
        </div>
    );
}
