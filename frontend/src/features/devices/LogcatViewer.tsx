"use client";

import React, { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Button } from "@/src/shared/ui/button";
import { RefreshCcw, FileText, AlertCircle } from "lucide-react";
import { Badge } from "@/src/shared/ui/badge";

interface LogcatViewerProps {
    deviceId: string;
}

export function LogcatViewer({ deviceId }: LogcatViewerProps) {
    const [logcat, setLogcat] = useState<string>("");
    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [error, setError] = useState<string | null>(null);

    const fetchLogcat = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const { data } = await api.post(`/devices/${deviceId}/logcat`, {
                lines: 500,
                mode: "sphere",
            });
            if (data.logcat) {
                setLogcat(data.logcat);
            } else if (data.error) {
                setError(data.error);
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || err.message || "Failed to fetch logcat");
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchLogcat();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [deviceId]);

    return (
        <div className="flex flex-col h-full border border-[#222] rounded-sm overflow-hidden bg-[#050505] animate-in fade-in zoom-in-95 duration-200">
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-1.5 bg-[#111] border-b border-[#333]">
                <div className="flex items-center gap-2">
                    <FileText className="w-3.5 h-3.5 text-primary" />
                    <span className="text-[10px] font-mono font-bold tracking-widest uppercase text-primary">System Logcat</span>
                    <Badge variant="outline" className="text-[8px] px-1 py-0 h-3 border-[#444] text-muted-foreground ml-2">500 LINES</Badge>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 hover:bg-[#222] text-muted-foreground hover:text-white"
                        onClick={fetchLogcat}
                        disabled={isLoading}
                        title="Refresh Logs"
                    >
                        <RefreshCcw className={`w-3 h-3 ${isLoading ? "animate-spin text-primary" : ""}`} />
                    </Button>
                </div>
            </div>

            {/* Content Container */}
            <div className="flex-1 relative overflow-auto custom-scrollbar p-2">
                {error ? (
                    <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-3">
                        <AlertCircle className="w-8 h-8 text-destructive opacity-80" />
                        <span className="text-sm font-mono text-destructive">{error}</span>
                        <Button variant="outline" size="sm" onClick={fetchLogcat} className="mt-2 bg-[#111] border-[#333]">
                            Retry
                        </Button>
                    </div>
                ) : (
                    <pre className="text-[11px] font-mono leading-tight text-gray-300 whitespace-pre-wrap break-all">
                        {isLoading && !logcat ? (
                            <span className="text-[#666] animate-pulse">Requesting logs from agent...</span>
                        ) : logcat ? (
                            logcat
                        ) : (
                            <span className="text-[#666]">No logs available.</span>
                        )}
                    </pre>
                )}
            </div>
        </div>
    );
}
