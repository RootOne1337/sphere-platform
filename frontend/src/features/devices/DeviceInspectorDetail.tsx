"use client";

import { useState } from "react";
import { Device } from "@/lib/hooks/useDevices";
import { Button } from "@/src/shared/ui/button";
import { Badge } from "@/src/shared/ui/badge";
import { DeviceStatusBadge } from "@/components/sphere/DeviceStatusBadge";
import { WebTerminal } from "./WebTerminal";
import { LogcatViewer } from "./LogcatViewer";
import { Terminal, MonitorPlay, Code2, RefreshCcw, Cpu, Smartphone, Shield, Wifi, Battery, Clock, ArrowLeft, FileText } from "lucide-react";

interface DeviceInspectorDetailProps {
    device: Device;
}

export function DeviceInspectorDetail({ device }: DeviceInspectorDetailProps) {
    const [activeTab, setActiveTab] = useState<"info" | "terminal" | "logcat">("info");

    if (activeTab === "terminal") {
        return (
            <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-2 duration-200">
                <div className="flex items-center gap-2 mb-4 shrink-0">
                    <Button variant="ghost" size="sm" onClick={() => setActiveTab("info")} className="px-2 hover:bg-[#222]">
                        <ArrowLeft className="w-4 h-4 mr-2" /> back
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

    if (activeTab === "logcat") {
        return (
            <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-2 duration-200">
                <div className="flex items-center gap-2 mb-4 shrink-0">
                    <Button variant="ghost" size="sm" onClick={() => setActiveTab("info")} className="px-2 hover:bg-[#222]">
                        <ArrowLeft className="w-4 h-4 mr-2" /> back
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

    return (
        <div className="flex flex-col h-full space-y-6 animate-in fade-in slide-in-from-left-2 duration-200">
            {/* Header Info */}
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
                        <Badge key={tag} variant="outline" className="bg-[#111] px-2 py-0.5" title={tag}>
                            {tag}
                        </Badge>
                    ))}
                    {device.tags.length === 0 && <span className="text-[10px] text-muted-foreground font-mono">NO TAGS DETECTED</span>}
                </div>
            </div>

            {/* Quick Actions Grid */}
            <div className="grid grid-cols-2 gap-2 shrink-0">
                <Button variant="outline" className="h-10 border-[#333] hover:border-primary hover:text-primary justify-start px-3 bg-[#111]">
                    <MonitorPlay className="w-4 h-4 mr-2" />
                    Stream
                </Button>
                <Button
                    variant="outline"
                    onClick={() => setActiveTab("terminal")}
                    className="h-10 border-[#333] hover:border-success hover:text-success justify-start px-3 bg-[#111] text-success/80"
                >
                    <Terminal className="w-4 h-4 mr-2" />
                    Terminal
                </Button>
                <Button
                    variant="outline"
                    onClick={() => setActiveTab("logcat")}
                    className="h-10 border-[#333] hover:border-primary hover:text-primary justify-start px-3 bg-[#111]"
                >
                    <FileText className="w-4 h-4 mr-2" />
                    Logcat
                </Button>
                <Button variant="outline" className="h-10 border-[#333] hover:border-warning hover:text-warning justify-start px-3 bg-[#111]">
                    <RefreshCcw className="w-4 h-4 mr-2" />
                    Reboot
                </Button>
                <Button variant="outline" className="col-span-2 h-10 border-[#333] hover:border-primary hover:text-primary justify-start px-3 bg-[#111]">
                    <Code2 className="w-4 h-4 mr-2" />
                    Run Script
                </Button>
            </div>

            {/* Scrollable Telemetry Data */}
            <div className="flex-1 overflow-y-auto custom-scrollbar space-y-6 pr-2">
                {/* Telemetry & System */}
                <div className="space-y-3">
                    <h4 className="text-[10px] uppercase font-bold tracking-widest text-[#555] font-mono border-b border-[#222] pb-1">Telemetry & System</h4>

                    <div className="grid grid-cols-2 gap-4">
                        {/* Model */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Smartphone className="w-3 h-3" /> Model</span>
                            <span className="text-xs font-mono font-bold mt-1 text-foreground truncate">{device.model}</span>
                        </div>

                        {/* Android Version */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Cpu className="w-3 h-3" /> Android</span>
                            <span className="text-xs font-mono font-bold mt-1 text-foreground">{device.android_version}</span>
                        </div>

                        {/* Battery */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Battery className="w-3 h-3" /> Power</span>
                            <span className={`text-xs font-mono font-bold mt-1 ${device.battery_level !== null && device.battery_level < 20 ? 'text-destructive' : 'text-success'}`}>
                                {device.battery_level !== null ? `${device.battery_level}%` : 'UNKNOWN'}
                            </span>
                        </div>

                        {/* Last Seen */}
                        <div className="flex flex-col">
                            <span className="text-[10px] text-muted-foreground uppercase flex items-center gap-1.5"><Clock className="w-3 h-3" /> Last Seen</span>
                            <span className="text-[11px] font-mono font-bold mt-1 text-foreground">
                                {device.last_seen ? new Date(device.last_seen).toLocaleString() : 'NEVER'}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Networking */}
                <div className="space-y-3">
                    <h4 className="text-[10px] uppercase font-bold tracking-widest text-[#555] font-mono border-b border-[#222] pb-1">Networking</h4>

                    <div className="space-y-2">
                        <div className="flex items-center justify-between bg-[#111] p-2 rounded-sm border border-[#222]">
                            <div className="flex items-center gap-2">
                                <Wifi className={`w-4 h-4 ${device.adb_connected ? 'text-success' : 'text-[#444]'}`} />
                                <span className="text-xs font-mono text-muted-foreground uppercase">ADB Daemon</span>
                            </div>
                            <Badge variant="outline" className={`text-[9px] ${device.adb_connected ? 'border-success text-success bg-success/10' : 'border-[#444] text-[#888]'}`}>
                                {device.adb_connected ? "CONNECTED" : "OFFLINE"}
                            </Badge>
                        </div>

                        <div className="flex items-center justify-between bg-[#111] p-2 rounded-sm border border-[#222]">
                            <div className="flex items-center gap-2">
                                <Shield className={`w-4 h-4 ${device.vpn_assigned ? 'text-primary' : 'text-[#444]'}`} />
                                <span className="text-xs font-mono text-muted-foreground uppercase">VPN Tunneling</span>
                            </div>
                            <Badge variant="outline" className={`text-[9px] ${device.vpn_assigned ? 'border-primary text-primary bg-primary/10' : 'border-[#444] text-[#888]'}`}>
                                {device.vpn_assigned ? "ACTIVE" : "UNASSIGNED"}
                            </Badge>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
