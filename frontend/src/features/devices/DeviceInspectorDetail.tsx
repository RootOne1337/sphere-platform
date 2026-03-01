"use client";

import { useState, useCallback } from "react";
import { Device } from "@/lib/hooks/useDevices";
import { Button } from "@/src/shared/ui/button";
import { Badge } from "@/src/shared/ui/badge";
import { DeviceStatusBadge } from "@/components/sphere/DeviceStatusBadge";
import { WebTerminal } from "./WebTerminal";
import { LogcatViewer } from "./LogcatViewer";
import { RunScriptTab } from "./RunScriptTab";
import { DeviceStream } from "@/src/components/streaming/DeviceStream";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
    Terminal,
    MonitorPlay,
    Code2,
    RefreshCcw,
    Cpu,
    Smartphone,
    Shield,
    Wifi,
    Battery,
    Clock,
    ArrowLeft,
    FileText,
    Loader2,
    AlertTriangle,
    Camera,
    Power,
} from "lucide-react";

interface DeviceInspectorDetailProps {
    device: Device;
}

type InspectorTab = "info" | "terminal" | "logcat" | "script" | "stream";

export function DeviceInspectorDetail({ device }: DeviceInspectorDetailProps) {
    const [activeTab, setActiveTab] = useState<InspectorTab>("info");
    const [isRebooting, setIsRebooting] = useState(false);
    const [isScreenshotting, setIsScreenshotting] = useState(false);
    const { accessToken } = useAuthStore();

    const isOnline = device.status === "online";

    // ── Обработчик перезагрузки ──────────────────────────────────────────────
    const handleReboot = useCallback(async () => {
        if (!isOnline || isRebooting) return;

        // Подтверждение перед перезагрузкой
        const confirmed = window.confirm(
            `Перезагрузить устройство ${device.name}?\nУстройство будет недоступно на время перезагрузки.`
        );
        if (!confirmed) return;

        setIsRebooting(true);
        try {
            const { data } = await api.post(`/devices/${device.id}/reboot`);
            if (data.error) {
                toast.error("Ошибка перезагрузки", { description: data.error });
            } else {
                toast.success("Команда перезагрузки отправлена", {
                    description: data.note || `Устройство ${device.name} перезагружается...`,
                });
            }
        } catch (err: any) {
            const errMsg = err.response?.data?.detail || err.message || "Ошибка связи с устройством";
            toast.error("Ошибка перезагрузки", { description: errMsg });
        } finally {
            setIsRebooting(false);
        }
    }, [device.id, device.name, isOnline, isRebooting]);

    // ── Обработчик скриншота ─────────────────────────────────────────────────
    const handleScreenshot = useCallback(async () => {
        if (!isOnline || isScreenshotting) return;

        setIsScreenshotting(true);
        try {
            const { data } = await api.get(`/devices/${device.id}/screenshot`);
            if (data.status === "screenshot_requested") {
                toast.success("Скриншот запрошен", {
                    description: "Скриншот сохранён на устройстве",
                });
            } else if (data.error) {
                toast.error("Ошибка скриншота", { description: data.error });
            }
        } catch (err: any) {
            const errMsg = err.response?.data?.detail || err.message || "Не удалось запросить скриншот";
            toast.error("Ошибка скриншота", { description: errMsg });
        } finally {
            setIsScreenshotting(false);
        }
    }, [device.id, isOnline, isScreenshotting]);

    // ── Обработчик стриминга ─────────────────────────────────────────────────
    const handleStream = useCallback(() => {
        if (!isOnline) {
            toast.error("Устройство оффлайн", { description: "Стриминг недоступен" });
            return;
        }
        setActiveTab("stream");
    }, [isOnline]);

    // ── Вкладка Terminal ─────────────────────────────────────────────────────
    if (activeTab === "terminal") {
        return (
            <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-2 duration-200">
                <div className="flex items-center gap-2 mb-4 shrink-0">
                    <Button variant="ghost" size="sm" onClick={() => setActiveTab("info")} className="px-2 hover:bg-border">
                        <ArrowLeft className="w-4 h-4 mr-2" /> назад
                    </Button>
                    <div className="flex-1">
                        <h3 className="text-sm font-bold text-foreground font-mono truncate">{device.name} / shell</h3>
                    </div>
                </div>
                <div className="flex-1 relative">
                    <WebTerminal deviceId={device.id} />
                </div>
            </div>
        );
    }

    // ── Вкладка Logcat ───────────────────────────────────────────────────────
    if (activeTab === "logcat") {
        return (
            <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-2 duration-200">
                <div className="flex items-center gap-2 mb-4 shrink-0">
                    <Button variant="ghost" size="sm" onClick={() => setActiveTab("info")} className="px-2 hover:bg-border">
                        <ArrowLeft className="w-4 h-4 mr-2" /> назад
                    </Button>
                    <div className="flex-1">
                        <h3 className="text-sm font-bold text-foreground font-mono truncate">{device.name} / logcat</h3>
                    </div>
                </div>
                <div className="flex-1 relative">
                    <LogcatViewer deviceId={device.id} />
                </div>
            </div>
        );
    }

    // ── Вкладка Run Script ───────────────────────────────────────────────────
    if (activeTab === "script") {
        return (
            <RunScriptTab
                deviceId={device.id}
                deviceName={device.name}
                isOnline={isOnline}
                onBack={() => setActiveTab("info")}
            />
        );
    }

    // ── Вкладка Stream ───────────────────────────────────────────────────────
    if (activeTab === "stream") {
        return (
            <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-2 duration-200">
                <div className="flex items-center gap-2 mb-4 shrink-0">
                    <Button variant="ghost" size="sm" onClick={() => setActiveTab("info")} className="px-2 hover:bg-border">
                        <ArrowLeft className="w-4 h-4 mr-2" /> назад
                    </Button>
                    <div className="flex-1">
                        <h3 className="text-sm font-bold text-foreground font-mono truncate">{device.name} / stream</h3>
                    </div>
                </div>
                <div className="flex-1 relative border border-border rounded-sm overflow-hidden bg-black">
                    {accessToken ? (
                        <DeviceStream
                            deviceId={device.id}
                            authToken={accessToken}
                            className="w-full h-full"
                        />
                    ) : (
                        <div className="flex items-center justify-center h-full text-destructive text-xs font-mono">
                            <AlertTriangle className="w-4 h-4 mr-2" />
                            Ошибка авторизации — токен недоступен
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // ── Основная вкладка Info ─────────────────────────────────────────────────
    return (
        <div className="flex flex-col h-full space-y-6 animate-in fade-in slide-in-from-left-2 duration-200">
            {/* Заголовок */}
            <div className="space-y-4 shrink-0">
                <div className="flex items-start justify-between">
                    <div>
                        <h3 className="text-lg font-bold text-primary font-mono tracking-wider">{device.name}</h3>
                        <p className="text-[11px] text-muted-foreground font-mono mt-1">ID: {device.id}</p>
                    </div>
                    <DeviceStatusBadge status={device.status} />
                </div>

                <div className="flex flex-wrap gap-2">
                    {device.tags.map((tag) => (
                        <Badge key={tag} variant="outline" className="bg-muted px-2 py-0.5" title={tag}>
                            {tag}
                        </Badge>
                    ))}
                    {device.tags.length === 0 && <span className="text-[10px] text-muted-foreground font-mono">NO TAGS DETECTED</span>}
                </div>
            </div>

            {/* Сетка быстрых действий */}
            <div className="grid grid-cols-2 gap-2 shrink-0">
                {/* Стриминг */}
                <Button
                    variant="outline"
                    onClick={handleStream}
                    disabled={!isOnline}
                    className="h-10 border-border hover:border-primary hover:text-primary justify-start px-3 bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    <MonitorPlay className="w-4 h-4 mr-2" />
                    Stream
                </Button>

                {/* Терминал */}
                <Button
                    variant="outline"
                    onClick={() => isOnline ? setActiveTab("terminal") : toast.error("Устройство оффлайн")}
                    disabled={!isOnline}
                    className="h-10 border-border hover:border-success hover:text-success justify-start px-3 bg-muted text-success/80 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    <Terminal className="w-4 h-4 mr-2" />
                    Terminal
                </Button>

                {/* Logcat */}
                <Button
                    variant="outline"
                    onClick={() => isOnline ? setActiveTab("logcat") : toast.error("Устройство оффлайн")}
                    disabled={!isOnline}
                    className="h-10 border-border hover:border-primary hover:text-primary justify-start px-3 bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    <FileText className="w-4 h-4 mr-2" />
                    Logcat
                </Button>

                {/* Перезагрузка */}
                <Button
                    variant="outline"
                    onClick={handleReboot}
                    disabled={!isOnline || isRebooting}
                    className="h-10 border-border hover:border-warning hover:text-warning justify-start px-3 bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    {isRebooting ? (
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                        <RefreshCcw className="w-4 h-4 mr-2" />
                    )}
                    {isRebooting ? "Rebooting..." : "Reboot"}
                </Button>

                {/* Запуск скрипта */}
                <Button
                    variant="outline"
                    onClick={() => isOnline ? setActiveTab("script") : toast.error("Устройство оффлайн")}
                    disabled={!isOnline}
                    className="h-10 border-border hover:border-primary hover:text-primary justify-start px-3 bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    <Code2 className="w-4 h-4 mr-2" />
                    Run Script
                </Button>

                {/* Скриншот */}
                <Button
                    variant="outline"
                    onClick={handleScreenshot}
                    disabled={!isOnline || isScreenshotting}
                    className="h-10 border-border hover:border-primary hover:text-primary justify-start px-3 bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    {isScreenshotting ? (
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                        <Camera className="w-4 h-4 mr-2" />
                    )}
                    {isScreenshotting ? "Capturing..." : "Screenshot"}
                </Button>
            </div>

            {/* Оффлайн-предупреждение */}
            {!isOnline && (
                <div className="flex items-center gap-2 p-2.5 bg-destructive/5 border border-destructive/20 rounded-sm shrink-0 animate-in fade-in duration-300">
                    <Power className="w-4 h-4 text-destructive shrink-0" />
                    <span className="text-[11px] font-mono text-destructive">
                        Устройство оффлайн — управление недоступно
                    </span>
                </div>
            )}

            {/* Прокручиваемая область: Телеметрия */}
            <div className="flex-1 overflow-y-auto custom-scrollbar space-y-6 pr-2">
                {/* Телеметрия и система */}
                <div className="space-y-3">
                    <h4 className="text-[10px] uppercase font-bold tracking-widest text-[#555] font-mono border-b border-border pb-1">Telemetry & System</h4>

                    <div className="grid grid-cols-2 gap-4">
                        {/* Модель */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Smartphone className="w-3 h-3" /> Model</span>
                            <span className="text-xs font-mono font-bold mt-1 text-foreground truncate">{device.device_model || device.model}</span>
                        </div>

                        {/* Версия Android */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Smartphone className="w-3 h-3" /> Android</span>
                            <span className="text-xs font-mono font-bold mt-1 text-foreground">{device.android_version}</span>
                        </div>

                        {/* Батарея */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Battery className="w-3 h-3" /> Power</span>
                            <span className={`text-xs font-mono font-bold mt-1 ${device.battery_level !== null && device.battery_level < 20 ? 'text-destructive' : 'text-success'}`}>
                                {device.battery_level !== null ? `${device.battery_level}%` : 'UNKNOWN'}
                            </span>
                        </div>

                        {/* CPU */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Cpu className="w-3 h-3" /> CPU</span>
                            <span className={`text-xs font-mono font-bold mt-1 ${device.cpu_usage !== null && device.cpu_usage !== undefined && device.cpu_usage > 80 ? 'text-warning' : 'text-foreground'}`}>
                                {device.cpu_usage !== null && device.cpu_usage !== undefined ? `${device.cpu_usage.toFixed(1)}%` : 'N/A'}
                            </span>
                        </div>

                        {/* RAM */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Cpu className="w-3 h-3" /> RAM</span>
                            <span className="text-xs font-mono font-bold mt-1 text-foreground">
                                {device.ram_usage_mb !== null && device.ram_usage_mb !== undefined ? `${device.ram_usage_mb} MB` : 'N/A'}
                            </span>
                        </div>

                        {/* Последняя активность */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Clock className="w-3 h-3" /> Last Seen</span>
                            <span className="text-[11px] font-mono font-bold mt-1 text-foreground">
                                {device.last_heartbeat ? new Date(device.last_heartbeat).toLocaleString() : device.last_seen ? new Date(device.last_seen).toLocaleString() : 'NEVER'}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Сеть */}
                <div className="space-y-3">
                    <h4 className="text-[10px] uppercase font-bold tracking-widest text-[#555] font-mono border-b border-border pb-1">Networking</h4>

                    <div className="space-y-2">
                        <div className="flex items-center justify-between bg-muted p-2 rounded-sm border border-border">
                            <div className="flex items-center gap-2">
                                <Wifi className={`w-4 h-4 ${device.adb_connected ? 'text-success' : 'text-muted-foreground'}`} />
                                <span className="text-xs font-mono text-muted-foreground uppercase">ADB Daemon</span>
                            </div>
                            <Badge variant="outline" className={`text-[9px] ${device.adb_connected ? 'border-success text-success bg-success/10' : 'border-[#444] text-muted-foreground'}`}>
                                {device.adb_connected ? "CONNECTED" : "OFFLINE"}
                            </Badge>
                        </div>

                        <div className="flex items-center justify-between bg-muted p-2 rounded-sm border border-border">
                            <div className="flex items-center gap-2">
                                <Shield className={`w-4 h-4 ${device.vpn_active || device.vpn_assigned ? 'text-primary' : 'text-muted-foreground'}`} />
                                <span className="text-xs font-mono text-muted-foreground uppercase">VPN Tunneling</span>
                            </div>
                            <Badge variant="outline" className={`text-[9px] ${device.vpn_active || device.vpn_assigned ? 'border-primary text-primary bg-primary/10' : 'border-[#444] text-muted-foreground'}`}>
                                {device.vpn_active ? "ACTIVE" : device.vpn_assigned ? "ASSIGNED" : "UNASSIGNED"}
                            </Badge>
                        </div>

                        {/* Экран */}
                        <div className="flex items-center justify-between bg-muted p-2 rounded-sm border border-border">
                            <div className="flex items-center gap-2">
                                <Smartphone className={`w-4 h-4 ${device.screen_on ? 'text-success' : 'text-muted-foreground'}`} />
                                <span className="text-xs font-mono text-muted-foreground uppercase">Screen</span>
                            </div>
                            <Badge variant="outline" className={`text-[9px] ${device.screen_on ? 'border-success text-success bg-success/10' : 'border-[#444] text-muted-foreground'}`}>
                                {device.screen_on === null || device.screen_on === undefined ? 'N/A' : device.screen_on ? "ON" : "OFF"}
                            </Badge>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
