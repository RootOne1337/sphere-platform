"use client";

import React, { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { Activity } from "lucide-react";
import { api } from '@/lib/api';

interface WebTerminalProps {
    deviceId: string;
}

export function WebTerminal({ deviceId }: WebTerminalProps) {
    const terminalRef = useRef<HTMLDivElement>(null);
    const termInstance = useRef<Terminal | null>(null);
    const fitAddon = useRef<FitAddon | null>(null);

    useEffect(() => {
        if (!terminalRef.current) return;

        // Инициализация терминала
        const term = new Terminal({
            theme: {
                background: "#050505",
                foreground: "#00FF00",
                cursor: "#00FF00",
                selectionBackground: "rgba(0, 255, 0, 0.3)",
            },
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: 12,
            cursorBlink: true,
            disableStdin: false,
        });

        const fit = new FitAddon();
        term.loadAddon(fit);

        term.open(terminalRef.current);
        fit.fit();

        termInstance.current = term;
        fitAddon.current = fit;

        term.writeln("\x1b[1;32m[SPHERE-ADB NOC]\x1b[0m Securing connection to target device...");
        term.writeln(`\x1b[1;34m[INFO]\x1b[0m Device ID: ${deviceId}`);

        setTimeout(() => {
            term.writeln("\x1b[1;34m[INFO]\x1b[0m Connected to remote Android Shell via Agent.");
            term.write("\r\n\x1b[1;32mshell@android:/\x1b[0m $ ");
        }, 500);

        let commandBuffer = "";
        let isProcessing = false;

        term.onData(async (data) => {
            if (isProcessing) return;

            const code = data.charCodeAt(0);

            if (code === 13) {
                // Enter
                term.writeln("");
                if (commandBuffer.trim()) {
                    isProcessing = true;
                    try {
                        const { data: resData } = await api.post(`/devices/${deviceId}/shell`, {
                            command: commandBuffer
                        });

                        if (resData.output) {
                            const lines = resData.output.split('\n');
                            lines.forEach((line: string) => term.writeln(line.replace(/\r/g, '')));
                        } else if (resData.error) {
                            term.writeln(`\x1b[1;31mError: ${resData.error}\x1b[0m`);
                        }
                    } catch (error: any) {
                        const errMsg = error.response?.data?.detail || error.message || "Unknown API error";
                        term.writeln(`\x1b[1;31mShell execution failed: ${errMsg}\x1b[0m`);
                    } finally {
                        isProcessing = false;
                    }
                }

                commandBuffer = "";
                term.write("\x1b[1;32mshell@android:/\x1b[0m $ ");
            } else if (code === 127) {
                // Backspace
                if (commandBuffer.length > 0) {
                    commandBuffer = commandBuffer.slice(0, -1);
                    term.write("\b \b");
                }
            } else if (code >= 32) {
                commandBuffer += data;
                term.write(data);
            }
        });

        const handleResize = () => fit.fit();
        window.addEventListener("resize", handleResize);

        return () => {
            window.removeEventListener("resize", handleResize);
            term.dispose();
        };
    }, [deviceId]);

    return (
        <div className="flex flex-col h-full border border-[#222] rounded-sm overflow-hidden bg-[#050505]">
            {/* Terminal Title Bar */}
            <div className="flex items-center justify-between px-3 py-1.5 bg-[#111] border-b border-[#333]">
                <div className="flex items-center gap-2">
                    <Activity className="w-3.5 h-3.5 text-success animate-pulse" />
                    <span className="text-[10px] font-mono font-bold tracking-widest uppercase text-success">Secure Shell Active</span>
                </div>
                <div className="text-[9px] font-mono text-muted-foreground">Session ID: {deviceId.substring(0, 8)}...</div>
            </div>

            {/* Terminal Container */}
            <div className="flex-1 p-2 relative">
                <div ref={terminalRef} className="absolute inset-2" />
            </div>
        </div>
    );
}
