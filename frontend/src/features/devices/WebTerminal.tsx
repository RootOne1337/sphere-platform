'use client';

import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { DEVICE_COMMAND_TIMEOUT, interactiveResult } from './interactiveResult';

export function WebTerminal({ deviceId, enabled = true }: { deviceId: string; enabled?: boolean }) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  useEffect(() => {
    if (!terminalRef.current) return;
    const term = new Terminal({
      theme: { background: '#0c1017', foreground: '#d9e2ed', cursor: '#8cbff7', selectionBackground: '#2a3b52' },
      fontFamily: '"JetBrains Mono", monospace', fontSize: 12, cursorBlink: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(terminalRef.current);
    fit.fit();
    term.writeln('[Sphere] HTTP shell через Android-агент. Это не постоянная SSH-сессия.');
    term.writeln(`Устройство: ${deviceId}`);
    term.writeln('Связь и результат проверяются для каждой команды. Автоповтора нет.');
    const prompt = () => term.write('\r\nshell > ');
    prompt();
    let commandBuffer = '';
    let processing = false;
    let disposed = false;
    let commandController: AbortController | null = null;
    const subscription = term.onData(async (input) => {
      if (processing || disposed) return;
      if (input === '\r') {
        const command = commandBuffer.trim(); commandBuffer = '';
        term.writeln('');
        if (!command) { prompt(); return; }
        if (!enabledRef.current) { term.writeln('Нет свежего подтверждения доступности. Обновите карточку.'); prompt(); return; }
        processing = true;
        commandController = new AbortController();
        try {
          const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/shell`, { command }, { signal: commandController.signal, timeout: DEVICE_COMMAND_TIMEOUT.shell });
          const output = interactiveResult(data, 'output');
          if (!disposed) {
            // Render output as text; remote ANSI/OSC sequences must not spoof
            // the terminal prompt or create links/control the local emulator.
            Array.from(output).filter((char) => char === '\n' || char === '\t' || (char.charCodeAt(0) >= 32 && (char.charCodeAt(0) < 127 || char.charCodeAt(0) >= 160))).join('').split('\n').forEach((line) => term.writeln(line));
            term.writeln('[Результат получен от API]');
          }
        } catch (error) {
          if (!disposed) term.writeln(`Результат не подтверждён: ${getApiErrorMessage(error, error instanceof Error ? error.message : 'Ошибка запроса')}. Автоповтора нет.`);
        } finally {
          processing = false; commandController = null;
          if (!disposed) prompt();
        }
      } else if (input === '\x7f' || input === '\b') {
        if (commandBuffer.length) { commandBuffer = commandBuffer.slice(0, -1); term.write('\b \b'); }
      } else if (!Array.from(input).some((char) => char.charCodeAt(0) < 32 || (char.charCodeAt(0) >= 127 && char.charCodeAt(0) < 160)) && commandBuffer.length + input.length <= 4096) {
        commandBuffer += input; term.write(input);
      }
    });
    const handleResize = () => { if (!disposed) fit.fit(); };
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(handleResize);
    observer?.observe(terminalRef.current);
    window.addEventListener('resize', handleResize);
    return () => {
      disposed = true;
      commandController?.abort();
      observer?.disconnect();
      window.removeEventListener('resize', handleResize);
      subscription.dispose(); term.dispose();
    };
  }, [deviceId]);

  return <section aria-label="HTTP shell Android" className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card">
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/30 px-3 py-2 text-xs"><span className="font-medium">Android shell · результат по запросу</span><span className="text-muted-foreground">{enabled ? 'Ожидает команды' : 'Управление недоступно'}</span></header>
    <div className="relative min-h-0 flex-1 bg-[#0c1017]"><div ref={terminalRef} className="absolute inset-2" /></div>
  </section>;
}
