"use client";

import React, { useState, useRef } from "react";
import { api } from "@/lib/api";
import { Button } from "@/src/shared/ui/button";
import { Badge } from "@/src/shared/ui/badge";
import { Play, Loader2, Copy, Trash2, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

interface RunScriptTabProps {
    deviceId: string;
    deviceName: string;
    isOnline: boolean;
    onBack: () => void;
}

interface ScriptResult {
    output?: string;
    error?: string;
    timestamp: Date;
    command: string;
    duration: number;
}

export function RunScriptTab({ deviceId, deviceName, isOnline, onBack }: RunScriptTabProps) {
    const [script, setScript] = useState<string>("");
    const [isRunning, setIsRunning] = useState(false);
    const [results, setResults] = useState<ScriptResult[]>([]);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    const executeScript = async () => {
        if (!script.trim() || isRunning || !isOnline) return;

        setIsRunning(true);
        const startTime = Date.now();

        try {
            // Разбиваем многострочный скрипт на команды и выполняем последовательно
            const commands = script.split("\n").filter((line) => line.trim() !== "" && !line.trim().startsWith("#"));

            let fullOutput = "";
            let hasError = false;

            for (const cmd of commands) {
                try {
                    const { data } = await api.post(`/devices/${deviceId}/shell`, {
                        command: cmd.trim(),
                    });

                    if (data.output) {
                        fullOutput += `$ ${cmd.trim()}\n${data.output}\n`;
                    } else if (data.error) {
                        fullOutput += `$ ${cmd.trim()}\nERROR: ${data.error}\n`;
                        hasError = true;
                    }
                } catch (err: any) {
                    const errMsg = err.response?.data?.detail || err.message || "Неизвестная ошибка";
                    fullOutput += `$ ${cmd.trim()}\nFATAL: ${errMsg}\n`;
                    hasError = true;
                    break;
                }
            }

            const duration = Date.now() - startTime;

            const result: ScriptResult = {
                output: hasError ? undefined : fullOutput,
                error: hasError ? fullOutput : undefined,
                timestamp: new Date(),
                command: script,
                duration,
            };

            setResults((prev) => [result, ...prev]);

            if (hasError) {
                toast.error("Скрипт завершился с ошибкой", {
                    description: `Время выполнения: ${duration}ms`,
                });
            } else {
                toast.success("Скрипт выполнен успешно", {
                    description: `${commands.length} команд за ${duration}ms`,
                });
            }
        } finally {
            setIsRunning(false);
        }
    };

    const copyOutput = (text: string) => {
        navigator.clipboard.writeText(text);
        toast.success("Скопировано в буфер обмена");
    };

    const clearResults = () => {
        setResults([]);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        // Ctrl+Enter / Cmd+Enter для запуска скрипта
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            executeScript();
        }
        // Tab для вставки отступа
        if (e.key === "Tab") {
            e.preventDefault();
            const start = e.currentTarget.selectionStart;
            const end = e.currentTarget.selectionEnd;
            const value = e.currentTarget.value;
            setScript(value.substring(0, start) + "  " + value.substring(end));
            // Устанавливаем курсор после вставленного таба
            setTimeout(() => {
                if (textareaRef.current) {
                    textareaRef.current.selectionStart = textareaRef.current.selectionEnd = start + 2;
                }
            }, 0);
        }
    };

    return (
        <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-2 duration-200">
            {/* Заголовок */}
            <div className="flex items-center gap-2 mb-4 shrink-0">
                <Button variant="ghost" size="sm" onClick={onBack} className="px-2 hover:bg-border">
                    <ArrowLeft className="w-4 h-4 mr-2" /> назад
                </Button>
                <div className="flex-1">
                    <h3 className="text-sm font-bold text-foreground font-mono truncate">{deviceName} / script</h3>
                </div>
            </div>

            {/* Редактор скрипта */}
            <div className="shrink-0 border border-border rounded-sm overflow-hidden bg-background">
                <div className="flex items-center justify-between px-3 py-1.5 bg-muted border-b border-border">
                    <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${isOnline ? "bg-success animate-pulse" : "bg-muted-foreground"}`} />
                        <span className="text-[10px] font-mono font-bold tracking-widest uppercase text-foreground">
                            Script Editor
                        </span>
                    </div>
                    <Badge variant="outline" className="text-[8px] px-1 py-0 h-3 border-[#444] text-muted-foreground">
                        Ctrl+Enter — запуск
                    </Badge>
                </div>
                <textarea
                    ref={textareaRef}
                    value={script}
                    onChange={(e) => setScript(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={"# Введите команды (по одной на строку)\nls -la /sdcard/\ngetprop ro.build.version.release\ndf -h"}
                    className="w-full h-32 bg-[#0a0a0a] text-green-400 font-mono text-xs p-3 resize-none outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground/30"
                    disabled={isRunning || !isOnline}
                    spellCheck={false}
                />
                <div className="flex items-center justify-between px-3 py-1.5 bg-muted border-t border-border">
                    <span className="text-[9px] text-muted-foreground font-mono">
                        {script.split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length} команд
                    </span>
                    <div className="flex items-center gap-2">
                        {results.length > 0 && (
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={clearResults}
                                className="h-6 px-2 text-[10px] text-muted-foreground hover:text-destructive"
                            >
                                <Trash2 className="w-3 h-3 mr-1" /> Очистить
                            </Button>
                        )}
                        <Button
                            size="sm"
                            onClick={executeScript}
                            disabled={!script.trim() || isRunning || !isOnline}
                            className="h-6 px-3 text-[10px] font-mono bg-success/20 text-success border border-success/30 hover:bg-success/30 disabled:opacity-40"
                        >
                            {isRunning ? (
                                <>
                                    <Loader2 className="w-3 h-3 mr-1 animate-spin" /> Выполняется...
                                </>
                            ) : (
                                <>
                                    <Play className="w-3 h-3 mr-1" /> Execute
                                </>
                            )}
                        </Button>
                    </div>
                </div>
            </div>

            {/* Результаты выполнения */}
            <div className="flex-1 overflow-y-auto custom-scrollbar mt-3 space-y-2">
                {!isOnline && (
                    <div className="flex items-center justify-center p-4 text-destructive text-xs font-mono bg-destructive/5 rounded-sm border border-destructive/20">
                        Устройство оффлайн — выполнение команд невозможно
                    </div>
                )}

                {results.length === 0 && isOnline && (
                    <div className="flex flex-col items-center justify-center py-8 text-muted-foreground/50">
                        <Play className="w-6 h-6 mb-2" />
                        <span className="text-xs font-mono">Введите скрипт и нажмите Execute</span>
                    </div>
                )}

                {results.map((result, idx) => (
                    <div
                        key={idx}
                        className={`border rounded-sm overflow-hidden ${result.error ? "border-destructive/30 bg-destructive/5" : "border-border bg-muted/30"
                            }`}
                    >
                        <div className="flex items-center justify-between px-2 py-1 bg-muted/50 border-b border-border">
                            <div className="flex items-center gap-2">
                                <div className={`w-1.5 h-1.5 rounded-full ${result.error ? "bg-destructive" : "bg-success"}`} />
                                <span className="text-[9px] font-mono text-muted-foreground">
                                    {result.timestamp.toLocaleTimeString()} • {result.duration}ms
                                </span>
                            </div>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-5 w-5 hover:bg-border"
                                onClick={() => copyOutput(result.output || result.error || "")}
                                title="Копировать вывод"
                            >
                                <Copy className="w-3 h-3" />
                            </Button>
                        </div>
                        <pre className="px-2 py-1.5 text-[10px] font-mono leading-tight text-gray-300 whitespace-pre-wrap break-all max-h-48 overflow-y-auto custom-scrollbar">
                            {result.output || result.error}
                        </pre>
                    </div>
                ))}
            </div>
        </div>
    );
}
