"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { signOut } from "@/lib/store";
import { useEffect, useRef, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@/src/shared/lib/utils";
import { useUIStore } from "@/src/shared/store/useUIStore";
import { Button } from "@/src/shared/ui/button";
import { ChevronsLeft, ChevronsRight, LogOut, Pin, Settings, X } from "lucide-react";
import { SphereMark } from '@/src/shared/ui/SphereMark';
import { SPHERE_NAV_GROUPS } from "./navigationCatalog";
import { useCapabilities } from '@/src/features/access/Capabilities';
import { navigateFromWorkspace } from './workspaceNavigationGuard';



interface NOCSidebarProps {
    onOpenAppearance?: () => void;
    isMobileOpen?: boolean;
    onMobileClose?: () => void;
}

export function NOCSidebar({ onOpenAppearance, isMobileOpen = false, onMobileClose }: NOCSidebarProps) {
    const access = useCapabilities();
    const groups = SPHERE_NAV_GROUPS.map(group => ({ ...group, items: group.items.filter(item => access.canAccessRoute(item.href)) })).filter(group => group.items.length > 0);
    const pathname = usePathname();
    const router = useRouter();
    const [isDesktop, setIsDesktop] = useState(false);
    const [hoverExpanded, setHoverExpanded] = useState(false);
    const [focusWithin, setFocusWithin] = useState(false);
    const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const returnFocusRef = useRef<HTMLElement | null>(null);
    const swipe = useRef<{ x: number; y: number; id: number } | null>(null);
    const sidebarMode = useUIStore((state) => state.sidebarMode);
    const setSidebarMode = useUIStore((state) => state.setSidebarMode);
    const clearHoverTimer = () => { if (hoverTimer.current !== null) clearTimeout(hoverTimer.current); hoverTimer.current = null; };
    useEffect(() => {
        setHoverExpanded(false);
        return () => { if (hoverTimer.current !== null) clearTimeout(hoverTimer.current); };
    }, [sidebarMode, isDesktop]);

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

    const showLabels = !isDesktop || sidebarMode === 'pinned' || (sidebarMode === 'auto' && (hoverExpanded || focusWithin));

    const handleNavClick = () => {
        if (isMobileOpen) onMobileClose?.();
    };

    const toggleExpanded = () => {
        setSidebarMode(sidebarMode === 'auto' ? 'pinned' : showLabels ? 'rail' : 'pinned');
    };

    const panel = (
            <aside
                aria-label="Боковая панель Sphere"
                data-sidebar-mode={sidebarMode}
                data-expanded={showLabels}
                onPointerDown={event => { if (!isDesktop && event.isPrimary && event.pointerType === 'touch' && event.target instanceof Element && !event.target.closest('button,input,textarea,select,a')) swipe.current = { x: event.clientX, y: event.clientY, id: event.pointerId }; }}
                onPointerCancel={() => { swipe.current = null; }}
                onPointerUp={event => { const start = swipe.current; swipe.current = null; if (start && event.pointerId === start.id && start.x - event.clientX > 72 && Math.abs(start.y - event.clientY) < 40) onMobileClose?.(); }}
                onPointerEnter={(event) => {
                    if (!isDesktop || sidebarMode !== 'auto' || event.pointerType !== 'mouse' || !window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;
                    clearHoverTimer();
                    hoverTimer.current = setTimeout(() => setHoverExpanded(true), 160);
                }}
                onPointerLeave={() => {
                    clearHoverTimer();
                    if (sidebarMode === 'auto') hoverTimer.current = setTimeout(() => setHoverExpanded(false), 220);
                }}
                onFocusCapture={(event) => { if (isDesktop) { clearHoverTimer(); setFocusWithin(event.target instanceof HTMLElement && event.target.matches(':focus-visible')); } }}
                onBlurCapture={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) { setFocusWithin(false); setHoverExpanded(false); }
                }}
                className={cn(
                    "sphere-chrome fixed inset-y-0 left-0 z-50 flex w-[min(288px,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden border-r border-border text-card-foreground shadow-xl transition-[width,transform] duration-200 ease-out lg:relative lg:translate-x-0 lg:shadow-none motion-reduce:transition-none",
                    isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
                    showLabels ? "lg:w-[248px]" : "lg:w-[72px]",
                )}
            >
                {!isDesktop && <DialogPrimitive.Title className="sr-only">Меню навигации Sphere</DialogPrimitive.Title>}
                <div className={cn("flex h-16 shrink-0 items-center border-b border-border", showLabels ? "justify-between px-4" : "justify-center px-3")}>
                    <Link href={access.canAccessRoute('/dashboard') ? '/dashboard' : '/settings'} onClick={handleNavClick} aria-label="Sphere — главная" className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary"><SphereMark className="h-8 w-8" /></span>
                        {showLabels && (
                            <span className="min-w-0">
                                <span className="block text-[15px] font-semibold leading-5 tracking-tight text-foreground">Sphere</span>
                                <span className="mt-0.5 block truncate text-xs text-muted-foreground">Управление устройствами</span>
                            </span>
                        )}
                    </Link>
                    {isMobileOpen && (
                        <Button aria-label="Закрыть меню навигации" variant="ghost" size="icon" className="h-11 w-11 shrink-0 lg:hidden" onClick={onMobileClose}>
                            <X className="h-4 w-4" aria-hidden="true" />
                        </Button>
                    )}
                </div>

                <nav aria-label="Основная навигация" className="custom-scrollbar min-h-0 flex-1 space-y-4 overflow-x-hidden overflow-y-auto px-3 py-4">
                    {groups.map(({ label: groupLabel, items }) => (
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
                                            "sphere-nav-link group relative flex min-h-[var(--nav-height)] items-center gap-3 rounded-lg border px-3 text-[13px] transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none",
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
                        onClick={() => navigateFromWorkspace(() => { void signOut(); router.replace('/login'); })}
                    >
                        <LogOut className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
                        {showLabels && <span>Выйти</span>}
                    </Button>
                    {isDesktop && <button
                        type="button"
                        aria-label={sidebarMode === 'auto' ? 'Закрепить меню' : showLabels ? "Свернуть меню" : "Развернуть меню"}
                        aria-expanded={showLabels}
                        onClick={toggleExpanded}
                        title={sidebarMode === 'auto' ? 'Закрепить меню' : showLabels ? 'Свернуть меню' : 'Развернуть меню'}
                        className="mt-2 hidden h-9 w-full items-center justify-center gap-2 rounded-lg text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:flex"
                    >
                        {sidebarMode === 'auto' ? <Pin className="h-4 w-4" aria-hidden /> : showLabels ? <ChevronsLeft className="h-4 w-4" aria-hidden /> : <ChevronsRight className="h-4 w-4" aria-hidden />}
                        {showLabels && (sidebarMode === 'auto' ? 'Закрепить меню' : 'Свернуть меню')}
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
