"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { signOut } from "@/lib/store";
import { useEffect, useRef, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@/src/shared/lib/utils";
import { useUIStore } from "@/src/shared/store/useUIStore";
import { Button } from "@/src/shared/ui/button";
import { LogOut, Settings, X } from "lucide-react";
import { SPHERE_NAV_GROUPS } from "./navigationCatalog";



interface NOCSidebarProps {
    onOpenAppearance?: () => void;
    isMobileOpen?: boolean;
    onMobileClose?: () => void;
}

export function NOCSidebar({ onOpenAppearance, isMobileOpen = false, onMobileClose }: NOCSidebarProps) {
    const pathname = usePathname();
    const router = useRouter();
    const [isExpanded, setIsExpanded] = useState(true);
    const [isDesktop, setIsDesktop] = useState(false);
    const returnFocusRef = useRef<HTMLElement | null>(null);
    const storedExpanded = useUIStore((state) => state.sidebarExpanded);
    const setStoredExpanded = useUIStore.setState;

    // Read the persisted preference after mount so server and first client render match.
    useEffect(() => setIsExpanded(storedExpanded), [storedExpanded]);

    useEffect(() => {
        const breakpoint = window.matchMedia('(min-width: 1024px)');
        const reconcile = () => setIsDesktop(breakpoint.matches);
        reconcile();
        breakpoint.addEventListener('change', reconcile);
        return () => breakpoint.removeEventListener('change', reconcile);
    }, []);

    useEffect(() => {
        if (isDesktop && isMobileOpen) onMobileClose?.();
    }, [isDesktop, isMobileOpen, onMobileClose]);

    const showLabels = !isDesktop || isExpanded;

    const handleNavClick = () => {
        if (isMobileOpen) onMobileClose?.();
    };

    const toggleExpanded = () => {
        const next = !isExpanded;
        setIsExpanded(next);
        setStoredExpanded({ sidebarExpanded: next });
    };

    const panel = (
            <aside
                aria-label="Боковая панель Sphere"
                className={cn(
                    "fixed inset-y-0 left-0 z-50 flex w-[272px] flex-col border-r border-border bg-card text-card-foreground shadow-xl transition-[width,transform] duration-200 ease-out lg:relative lg:translate-x-0 lg:shadow-none motion-reduce:transition-none",
                    isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
                    showLabels ? "lg:w-[264px]" : "lg:w-[76px]",
                )}
            >
                {!isDesktop && <DialogPrimitive.Title className="sr-only">Меню навигации Sphere</DialogPrimitive.Title>}
                <div className={cn("flex h-[76px] shrink-0 items-center border-b border-border", showLabels ? "justify-between px-5" : "justify-center px-3")}>
                    <Link href="/dashboard" onClick={handleNavClick} aria-label="Sphere — главная" className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary text-base font-bold text-primary-foreground shadow-sm">S</span>
                        {showLabels && (
                            <span className="min-w-0">
                                <span className="block text-[15px] font-semibold leading-5 tracking-tight text-foreground">Sphere</span>
                                <span className="mt-0.5 block truncate text-xs text-muted-foreground">Управление устройствами</span>
                            </span>
                        )}
                    </Link>
                    {isMobileOpen && (
                        <Button aria-label="Закрыть меню навигации" variant="ghost" size="icon" className="h-9 w-9 shrink-0 lg:hidden" onClick={onMobileClose}>
                            <X className="h-4 w-4" aria-hidden="true" />
                        </Button>
                    )}
                </div>

                <nav aria-label="Основная навигация" className="custom-scrollbar flex-1 space-y-5 overflow-x-hidden overflow-y-auto px-3 py-5">
                    {SPHERE_NAV_GROUPS.map(({ label: groupLabel, items }) => (
                        <div key={groupLabel} role="group" aria-label={groupLabel} className="space-y-1">
                            {showLabels && <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{groupLabel}</p>}
                            {items.map(({ href, label, icon: Icon }) => {
                                const isActive = pathname === href || pathname.startsWith(`${href}/`);
                                return (
                                    <Link
                                        key={href}
                                        href={href}
                                        onClick={handleNavClick}
                                        aria-label={label}
                                        aria-current={isActive ? "page" : undefined}
                                        title={showLabels ? undefined : label}
                                        className={cn(
                                            "group relative flex min-h-10 items-center gap-3 rounded-lg border px-3 text-[13px] transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none",
                                            !showLabels && "justify-center px-0",
                                            isActive
                                                ? "border-primary/15 bg-primary/10 font-semibold text-primary"
                                                : "border-transparent text-muted-foreground hover:bg-muted/70 hover:text-foreground",
                                        )}
                                    >
                                        <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
                                        {showLabels && <span className="truncate">{label}</span>}
                                        {isActive && <span className={cn("absolute inset-y-2 left-0 w-0.5 rounded-r-full bg-primary", !showLabels && "left-0")} aria-hidden="true" />}
                                    </Link>
                                );
                            })}
                        </div>
                    ))}
                </nav>

                <div className="shrink-0 space-y-1 border-t border-border p-3">
                    <Button
                        variant="ghost"
                        size={showLabels ? "default" : "icon"}
                        className={cn("w-full text-muted-foreground hover:bg-primary/5 hover:text-primary", showLabels ? "justify-start gap-3 px-3" : "mx-auto")}
                        title={showLabels ? undefined : "Настройки интерфейса"}
                        aria-label="Настройки интерфейса"
                        onClick={() => { handleNavClick(); onOpenAppearance?.(); }}
                    >
                        <Settings className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
                        {showLabels && <span>Настройки интерфейса</span>}
                    </Button>
                    <Button
                        variant="ghost"
                        size={showLabels ? "default" : "icon"}
                        className={cn("w-full text-muted-foreground hover:bg-destructive/5 hover:text-destructive", showLabels ? "justify-start gap-3 px-3" : "mx-auto")}
                        title={showLabels ? undefined : "Выйти"}
                        aria-label="Выйти"
                        onClick={() => { void signOut(); router.replace('/login'); }}
                    >
                        <LogOut className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
                        {showLabels && <span>Выйти</span>}
                    </Button>
                    {isDesktop && <button
                        type="button"
                        aria-label={showLabels ? "Свернуть меню" : "Развернуть меню"}
                        aria-expanded={showLabels}
                        onClick={toggleExpanded}
                        className="mt-2 hidden h-9 w-full items-center justify-center rounded-lg text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:flex"
                    >
                        {showLabels ? "Свернуть меню" : "Развернуть меню"}
                    </button>}
                    {showLabels && <p className="px-3 pt-2 text-[11px] text-muted-foreground">Sphere Platform · Android Fleet</p>}
                </div>
            </aside>
    );

    if (isDesktop) return panel;

    return (
        <DialogPrimitive.Root open={isMobileOpen} onOpenChange={(open) => { if (!open) onMobileClose?.(); }}>
            <DialogPrimitive.Portal>
                <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-slate-950/30 backdrop-blur-sm" />
                <DialogPrimitive.Content
                    asChild
                    aria-modal="true"
                    aria-describedby={undefined}
                    onOpenAutoFocus={() => { returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; }}
                    onCloseAutoFocus={(event) => {
                        event.preventDefault();
                        if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
                    }}
                >
                    {panel}
                </DialogPrimitive.Content>
            </DialogPrimitive.Portal>
        </DialogPrimitive.Root>
    );
}
