'use client';

import React, { useState } from 'react';
import { Play, Pause, X, MonitorPlay, Activity, Cpu } from 'lucide-react';
import { Device } from '@/lib/hooks/useDevices';
import { isDeviceReachable } from '@/src/features/devices/deviceListFilters';
import { getReportedDeviceModel } from './devicePresentation';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { useStreamStore, GRID_SIZE_OPTIONS, gridColumns, gridLabel } from '@/src/shared/store/useStreamStore';
import { DeviceStream } from '@/components/sphere/DeviceStream';

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

    // Количество колонок по таблице gridColumns из стора
    const columns = gridColumns(gridSize);

    // Если оператор выделил устройства в таблице, стримим именно их. Без
    // выделения сетка показывает начало текущего отфильтрованного списка.
    const selectedSet = new Set(selectedIds ?? []);
    const streamCandidates = selectedSet.size > 0
        ? devices.filter((device) => selectedSet.has(device.id))
        : devices;
    const visibleDevices = streamCandidates.slice(0, gridSize);

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
        <div className="stream-wall flex h-full min-h-0 min-w-0 flex-col rounded-xl border border-border bg-card">
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
                    <div key={device.id} className="relative bg-muted border border-border rounded-lg overflow-hidden group flex min-w-0 flex-col aspect-video">
                        {/* Video Layer */}
                        <div
                            className="flex-1 relative bg-background flex flex-col items-center justify-center overflow-hidden"
                        >
                            {broadcastActive && reachable ? (
                                /* Реальный видео-стрим через WebSocket H.264 */
                                <DeviceStream readOnly deviceId={device.id} fit={objectFit} />
                            ) : reachable ? (
                                /* Онлайн, но стрим не включён — показываем готовность */
                                <div className="flex flex-col items-center justify-center text-muted-foreground gap-2">
                                    <Play className="w-6 h-6 opacity-30" />
                                    <span className="text-xs font-medium">Готов к просмотру</span>
                                    <span className="text-xs text-muted-foreground">Нажмите «Запустить»</span>
                                </div>
                            ) : (
                                /* Оффлайн */
                                <div className="flex flex-col items-center justify-center text-muted-foreground gap-2">
                                    <X className="w-6 h-6 opacity-30" />
                                    <span className="text-xs font-medium">Устройство не в сети</span>
                                    <span className="text-xs text-muted-foreground">Проверьте heartbeat и доступность устройства</span>
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

                        {/* Bottom Telemetry Bar */}
                        <div className="min-h-8 shrink-0 bg-card border-t border-border px-2 flex items-center justify-between">
                            <span className="text-xs text-muted-foreground truncate">{getReportedDeviceModel(device) ?? 'Модель не сообщена'}</span>

                            {showStats && reachable && (
                                <div className="flex items-center gap-3">
                                    <div className="flex items-center gap-1 text-[11px] font-mono text-warning">
                                        <Activity className="w-2.5 h-2.5" /> {formatHeartbeatAge(device.last_heartbeat)}
                                    </div>
                                    <div className="flex items-center gap-1 text-[11px] font-mono text-muted-foreground">
                                        <Cpu className="w-2.5 h-2.5" /> {device.cpu_usage != null ? `${device.cpu_usage}%` : '—'}
                                    </div>
                                </div>
                            )}
                        </div>

                    </div>
                    );
                })}

                {/* Пустые слоты если устройств меньше чем ячеек сетки */}
                {Array.from({ length: Math.max(0, gridSize - Math.min(visibleDevices.length, gridSize)) }).map((_, i) => (
                    <div key={`empty-${i}`} className="bg-muted/30 border border-border border-dashed rounded-lg aspect-video flex items-center justify-center">
                        <span className="text-xs text-muted-foreground">Свободный слот</span>
                    </div>
                ))}

            </div>
        </div>
    );
}
