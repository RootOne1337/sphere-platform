"use client";

import React, { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api";
import { Button } from "@/src/shared/ui/button";
import { Badge } from "@/src/shared/ui/badge";
import { Play, Loader2, Copy, Trash2, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { DEVICE_COMMAND_TIMEOUT, interactiveResult } from './interactiveResult';
import { getApiErrorMessage } from '@/lib/apiError';

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
    const commandLock = useRef(false);
    const mounted = useRef(true);
    const available = useRef(isOnline);
    const activeRequest = useRef<AbortController | null>(null);
    available.current = isOnline;
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; activeRequest.current?.abort(); };
    }, []);

    const executeScript = async () => {
        if (!script.trim() || commandLock.current || !isOnline) return;
        const commands = script.split("\n").filter((line) => line.trim() !== "" && !line.trim().startsWith("#"));
        if (!commands.length) { toast.error('Нет команд для исполнения'); return; }
        commandLock.current = true;

        setIsRunning(true);
        const startTime = Date.now();

        try {
            // Разбиваем многострочный скрипт на команды и выполняем последовательно

            let fullOutput = "";
            let hasError = false;

            for (const cmd of commands) {
                try {
                    if (!mounted.current || !available.current) throw new Error('Исполнение остановлено: устройство недоступно или панель закрыта.');
                    const controller = new AbortController();
                    activeRequest.current = controller;
                    const { data } = await api.post(`/devices/${deviceId}/shell`, {
                        command: cmd.trim(),
                    }, { signal: controller.signal, timeout: DEVICE_COMMAND_TIMEOUT.shell });

                    const output = interactiveResult(data, 'output');
                    fullOutput += `$ ${cmd.trim()}\n${output}\n`;
                } catch (err) {
                    const errMsg = getApiErrorMessage(err, err instanceof Error ? err.message : 'Результат не подтверждён');
                    fullOutput += `$ ${cmd.trim()}\nFATAL: ${errMsg}\n`;
                    hasError = true;
                    break;
                }
            }

            if (!mounted.current) return;

            const duration = Date.now() - startTime;

            const result: ScriptResult = {
                output: hasError ? undefined : fullOutput,
                error: hasError ? fullOutput : undefined,
                timestamp: new Date(),
                command: script,
                duration,
            };

            setResults((prev) => [result, ...prev].slice(0, 20));

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
            commandLock.current = false;
            activeRequest.current = null;
            if (mounted.current) setIsRunning(false);
        }
    };

    const copyOutput = async (text: string) => {
        try { await navigator.clipboard.writeText(text); toast.success("Скопировано в буфер обмена"); }
        catch { toast.error('Не удалось скопировать результат'); }
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
        <div className="flex h-full min-h-0 flex-col animate-in fade-in duration-200 motion-reduce:animate-none">
            {/* Заголовок */}
            <div className="flex items-center gap-2 mb-4 shrink-0">
                <Button variant="ghost" size="sm" onClick={onBack} className="px-2 hover:bg-border">
                    <ArrowLeft className="w-4 h-4 mr-2" /> назад
                </Button>
                <div className="min-w-0 flex-1">
                    <h3 className="truncate text-sm font-semibold">{deviceName} · команды Android</h3>
                </div>
            </div>

            {/* Редактор скрипта */}
            <p className="mb-3 text-xs leading-relaxed text-muted-foreground">Команды выполняются по одной через APK, до 30 секунд на ответ. При ошибке следующие команды не отправляются. Закрытие панели отменяет ожидание, но не отменяет уже полученную Android команду.</p>
            <div className="shrink-0 overflow-hidden rounded-xl border border-border bg-card">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/30 px-3 py-2">
                    <div className="flex items-center gap-2">
                        <div className={`h-2 w-2 rounded-full ${isOnline ? "bg-success" : "bg-muted-foreground"}`} />
                        <span className="text-xs font-medium">
                            Редактор shell-команд
                        </span>
                    </div>
                    <Badge variant="outline" className="text-xs font-normal text-muted-foreground">
                        Ctrl+Enter — запуск
                    </Badge>
                </div>
                <textarea
                    aria-label="Команды shell: по одной на строку"
                    ref={textareaRef}
                    value={script}
                    onChange={(e) => setScript(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={"# Введите команды (по одной на строку)\nls -la /sdcard/\ngetprop ro.build.version.release\ndf -h"}
                    className="h-40 w-full resize-y bg-background p-3 font-mono text-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-60"
                    disabled={isRunning || !isOnline}
                    spellCheck={false}
                />
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border bg-muted/30 px-3 py-2">
                    <span className="text-xs text-muted-foreground">
                        {script.split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length} команд
                    </span>
                    <div className="flex items-center gap-2">
                        {results.length > 0 && (
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={clearResults}
                                className="text-muted-foreground hover:text-destructive"
                            >
                                <Trash2 className="w-3 h-3 mr-1" /> Очистить
                            </Button>
                        )}
                        <Button
                            size="sm"
                            onClick={executeScript}
                            disabled={!script.trim() || isRunning || !isOnline}
                        >
                            {isRunning ? (
                                <>
                                    <Loader2 className="w-3 h-3 mr-1 animate-spin" /> Выполняется...
                                </>
                            ) : (
                                <>
                                    <Play className="mr-2 h-4 w-4" /> Выполнить
                                </>
                            )}
                        </Button>
                    </div>
                </div>
            </div>

            {/* Результаты выполнения */}
            <div aria-live="polite" className="mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto">
                {!isOnline && (
                    <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">
                        Нет свежего подтверждения доступности — команды заблокированы.
                    </div>
                )}

                {results.length === 0 && isOnline && (
                    <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                        <Play className="w-6 h-6 mb-2" />
                        <span className="text-sm">Введите команды и нажмите «Выполнить»</span>
                    </div>
                )}

                {results.map((result, idx) => (
                    <div
                        key={idx}
                        className={`overflow-hidden rounded-xl border ${result.error ? "border-destructive/30 bg-destructive/5" : "border-border bg-card"
                            }`}
                    >
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/30 px-3 py-2">
                            <div className="flex items-center gap-2">
                                <div className={`w-1.5 h-1.5 rounded-full ${result.error ? "bg-destructive" : "bg-success"}`} />
                                <span className="text-xs text-muted-foreground">
                                    {result.error ? 'Результат не подтверждён' : 'Получен результат'} · {result.timestamp.toISOString().slice(11, 19)} UTC · {result.duration} ms
                                </span>
                            </div>
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => copyOutput(result.output || result.error || "")}
                                title="Копировать вывод"
                            >
                                <Copy className="w-3 h-3" />
                            </Button>
                        </div>
                        <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-all p-3 font-mono text-xs leading-relaxed text-foreground">
                            {result.output || result.error}
                        </pre>
                    </div>
                ))}
            </div>
        </div>
    );
}
