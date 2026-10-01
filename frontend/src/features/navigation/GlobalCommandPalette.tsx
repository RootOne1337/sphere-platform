"use client";

import * as React from "react";
import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { ArrowLeft, Code2, PaintBucket, Search, Wifi } from "lucide-react";
import { useCommandPaletteStore } from "./commandPaletteStore";
import { ThemeSwitcherModal } from "@/src/features/settings/ThemeSwitcherModal";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { SPHERE_NAV_GROUPS } from "./navigationCatalog";

const ITEM_CLASS = "mb-1 flex min-h-10 cursor-pointer items-center rounded-lg px-3 text-sm text-foreground transition-colors hover:bg-muted aria-selected:bg-primary/10 aria-selected:text-primary motion-reduce:transition-none";
const GROUP_CLASS = "px-2 py-1 text-xs font-medium text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:font-semibold";

export function GlobalCommandPalette() {
    const router = useRouter();
    const { isOpen, toggle, close } = useCommandPaletteStore();
    const [activeMenu, setActiveMenu] = React.useState<"main" | "themes">("main");
    const mainPanelRef = React.useRef<HTMLDivElement>(null);
    const themesPanelRef = React.useRef<HTMLDivElement>(null);
    const returnFocusRef = React.useRef<HTMLElement | null>(null);

    React.useEffect(() => {
        if (!isOpen) return;
        const activePanel = activeMenu === "main" ? mainPanelRef.current : themesPanelRef.current;
        const frame = window.requestAnimationFrame(() => {
            activePanel?.querySelector<HTMLElement>("input:not([disabled]), button:not([disabled]), [role='option']")?.focus();
        });
        return () => window.cancelAnimationFrame(frame);
    }, [activeMenu, isOpen]);

    const handleDialogKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
        if (event.key !== "Tab") return;
        const panel = activeMenu === "main" ? mainPanelRef.current : themesPanelRef.current;
        const focusable = panel?.querySelectorAll<HTMLElement>("input:not([disabled]), button:not([disabled]), [role='option']:not([aria-disabled='true'])");
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    };

    React.useEffect(() => {
        const down = (e: KeyboardEvent) => {
            if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                toggle();
            }
        };

        document.addEventListener("keydown", down);
        return () => document.removeEventListener("keydown", down);
    }, [toggle]);

    React.useEffect(() => {
        if (!isOpen) {
            const timeout = window.setTimeout(() => setActiveMenu("main"), 200);
            return () => window.clearTimeout(timeout);
        }
    }, [isOpen]);

    if (!isOpen) return null;

    return (
      <DialogPrimitive.Root open={isOpen} onOpenChange={(open) => { if (!open) close(); }}>
       <DialogPrimitive.Portal>
        <div className="fixed inset-0 z-[100] flex items-start justify-center px-3 pt-[min(16vh,160px)] sm:px-6" data-testid="command-palette-overlay">
            <button type="button" aria-label="Закрыть поиск" className="absolute inset-0 cursor-default bg-slate-950/35 backdrop-blur-sm" onClick={close} />
            <DialogPrimitive.Content
                asChild
                aria-modal="true"
                aria-describedby={undefined}
                onEscapeKeyDown={(event) => {
                    event.preventDefault();
                    if (activeMenu === 'themes') setActiveMenu('main');
                    else close();
                }}
                onOpenAutoFocus={() => {
                    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
                }}
                onCloseAutoFocus={(event) => {
                    event.preventDefault();
                    if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
                }}
            >
            <div role="dialog" aria-modal="true" aria-label="Поиск и команды Sphere" onKeyDown={handleDialogKeyDown} className="relative z-10 h-[min(520px,75dvh)] min-h-0 w-full max-w-2xl overflow-hidden rounded-2xl border border-border bg-card shadow-2xl shadow-slate-950/20">
                <DialogPrimitive.Title className="sr-only">Поиск и команды Sphere</DialogPrimitive.Title>
                <div ref={mainPanelRef} aria-hidden={activeMenu !== "main"} inert={activeMenu !== "main"} className={`absolute inset-0 transition-transform duration-200 motion-reduce:transition-none ${activeMenu === "main" ? "translate-x-0" : "-translate-x-full"}`}>
                    <Command
                        label="Поиск по разделам и командам"
                        className="flex h-full w-full flex-col"
                    >
                        <div className="flex h-14 shrink-0 items-center border-b border-border px-4">
                            <Search className="mr-3 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                            <Command.Input
                                aria-label="Поиск по разделам и командам"
                                className="h-full w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
                                placeholder="Перейти к разделу или найти действие…"
                            />
                            <kbd className="ml-3 shrink-0 rounded-md border border-border bg-muted px-2 py-1 font-mono text-[10px] text-muted-foreground">ESC</kbd>
                        </div>

                        <Command.List className="custom-scrollbar flex-1 overflow-y-auto p-2">
                            <Command.Empty className="p-8 text-center text-sm text-muted-foreground">
                                Ничего не найдено. Попробуйте изменить запрос.
                            </Command.Empty>

                            {SPHERE_NAV_GROUPS.map((group) => (
                                <Command.Group key={group.label} heading={group.label} className={GROUP_CLASS}>
                                    {group.items.map(({ href, label, icon: Icon }) => (
                                        <Command.Item key={href} value={href} keywords={[label, group.label, href, href === '/devices' ? 'Реестр устройств' : href === '/dashboard' ? 'Обзор парка' : '']} onSelect={() => { router.push(href); close(); }} className={ITEM_CLASS}>
                                            <Icon className="mr-3 h-4 w-4" aria-hidden="true" />{href === '/devices' ? 'Реестр устройств' : href === '/dashboard' ? 'Обзор парка' : label}
                                        </Command.Item>
                                    ))}
                                </Command.Group>
                            ))}

                            <Command.Group heading="Настройки интерфейса" className={`${GROUP_CLASS} mt-2`}>
                                <Command.Item onSelect={() => setActiveMenu("themes")} className={ITEM_CLASS}>
                                    <PaintBucket className="mr-3 h-4 w-4" aria-hidden="true" />Тема и плотность интерфейса
                                </Command.Item>
                            </Command.Group>

                            <Command.Group heading="Быстрые действия" className={`${GROUP_CLASS} mt-2`}>
                                <Command.Item onSelect={() => { router.push("/vpn"); close(); }} className={ITEM_CLASS}>
                                    <Wifi className="mr-3 h-4 w-4" aria-hidden="true" />Открыть мониторинг VPN
                                </Command.Item>
                                <Command.Item onSelect={() => { router.push("/scripts/builder"); close(); }} className={ITEM_CLASS}>
                                    <Code2 className="mr-3 h-4 w-4" aria-hidden="true" />Открыть конструктор скриптов
                                </Command.Item>
                            </Command.Group>
                        </Command.List>
                        <div className="flex h-10 shrink-0 items-center justify-between border-t border-border px-4 text-[11px] text-muted-foreground">
                            <span>Sphere · быстрый переход и действия</span><span>↑ ↓ выбрать · Enter открыть</span>
                        </div>
                    </Command>
                </div>

                <div ref={themesPanelRef} aria-hidden={activeMenu !== "themes"} inert={activeMenu !== "themes"} className={`absolute inset-0 overflow-y-auto bg-card transition-transform duration-200 motion-reduce:transition-none ${activeMenu === "themes" ? "translate-x-0" : "translate-x-full"}`}>
                    <button type="button" className="sticky top-0 z-10 flex min-h-12 w-full items-center border-b border-border bg-card/95 px-4 text-sm font-medium text-muted-foreground backdrop-blur transition-colors hover:text-foreground" onClick={() => setActiveMenu("main")}>
                        <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />Назад к поиску
                    </button>
                    <ThemeSwitcherModal onClose={close} />
                </div>
            </div>
            </DialogPrimitive.Content>
        </div>
       </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    );
}
