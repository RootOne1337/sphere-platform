"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { signOut } from "@/lib/store";
import { useState } from "react";
import { cn } from "@/src/shared/lib/utils";
import { Button } from "@/src/shared/ui/button";
import {
    Monitor,
    Wifi,
    Code2,
    LayoutDashboard,
    LogOut,
    Activity,
    Users,
    ListTodo,
    FolderOpen,
    ScrollText,
    Radar,
    Webhook,
    Settings,
    FileText,
    RefreshCw,
    ChevronRight,
    ChevronLeft,
    X,
    UserCog,
    GitBranch,
    MapPin,
    Gamepad2,
    Zap,
    History,
    ToggleRight,
    Settings2,
} from "lucide-react";

const NAV_GROUPS = [
    {
        label: "Обзор",
        items: [
            { href: "/dashboard", label: "Главная", icon: LayoutDashboard },
            { href: "/monitoring", label: "Инфраструктура", icon: Activity },
        ],
    },
    {
        label: "Устройства",
        items: [
            { href: "/devices", label: "Парк устройств", icon: Monitor },
            { href: "/stream", label: "Видеопоток", icon: Monitor },
            { href: "/discovery", label: "Обнаружение", icon: Radar },
            { href: "/groups", label: "Группы", icon: FolderOpen },
            { href: "/locations", label: "Локации", icon: MapPin },
        ],
    },
    {
        label: "Автоматизация",
        items: [
            { href: "/tasks", label: "Задания", icon: ListTodo },
            { href: "/orchestration", label: "Оркестрация", icon: GitBranch },
            { href: "/pipeline-settings", label: "Пайплайны", icon: Settings2 },
            { href: "/accounts", label: "Игровые аккаунты", icon: Gamepad2 },
            { href: "/scripts", label: "Скрипты", icon: Code2 },
        ],
    },
    {
        label: "События и сеть",
        items: [
            { href: "/events", label: "События устройств", icon: Zap },
            { href: "/event-triggers", label: "Триггеры событий", icon: ToggleRight },
            { href: "/sessions", label: "Сессии", icon: History },
            { href: "/vpn", label: "Туннели и VPN", icon: Wifi },
            { href: "/webhooks", label: "Вебхуки", icon: Webhook },
        ],
    },
    {
        label: "Администрирование",
        items: [
            { href: "/users", label: "Пользователи", icon: Users },
            { href: "/audit", label: "Журнал аудита", icon: ScrollText },
            { href: "/logs", label: "Системные логи", icon: FileText },
            { href: "/updates", label: "Обновления", icon: RefreshCw },
            { href: "/settings", label: "Конфигурация", icon: UserCog },
        ],
    },
];

interface NOCSidebarProps {
    onOpenAppearance?: () => void;
    isMobileOpen?: boolean;
    onMobileClose?: () => void;
}

export function NOCSidebar({ onOpenAppearance, isMobileOpen, onMobileClose }: NOCSidebarProps) {
    const pathname = usePathname();
    const router = useRouter();
    const [isCollapsed, setIsCollapsed] = useState(true);

    // Закрываем меню на мобилках при клике на линк
    const handleNavClick = () => {
        if (isMobileOpen && onMobileClose) {
            onMobileClose();
        }
    };

    return (
        <>
            {/* Overlay для мобильного меню */}
            {isMobileOpen && (
                <button
                    type="button"
                    aria-label="Закрыть меню навигации"
                    className="fixed inset-0 z-40 cursor-default border-0 bg-foreground/30 p-0 backdrop-blur-sm lg:hidden"
                    onClick={onMobileClose}
                />
            )}

            <aside
                className={cn(
                    "flex flex-col bg-card border-r border-border transition-all duration-300 z-50",
                    // На мобилках: fixed positioning, выезжает слева
                    "fixed inset-y-0 left-0 lg:relative lg:flex",
                    // Состояние для мобилок (открыто/закрыто)
                    isMobileOpen ? "translate-x-0 w-64 shadow-2xl" : "-translate-x-full lg:translate-x-0",
                    // Состояние для десктопов
                    !isMobileOpen && isCollapsed ? "lg:w-14" : "lg:w-56"
                )}
                onMouseEnter={() => !isMobileOpen && setIsCollapsed(false)}
                onMouseLeave={() => !isMobileOpen && setIsCollapsed(true)}
            >
                <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4 lg:justify-center lg:px-0">
                    {isCollapsed && !isMobileOpen ? (
                        <div className="w-6 h-6 bg-primary rounded-sm flex items-center justify-center font-bold text-primary-foreground text-xs">
                            S
                        </div>
                    ) : (
                        <div className="flex w-full items-center gap-2 px-4 font-mono font-bold tracking-wider text-foreground">
                            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-sm text-primary-foreground">S</div>
                            <span>SPHERE</span><span className="text-xs font-medium text-muted-foreground">OPS</span>
                        </div>
                    )}
                    {/* Кнопка закрытия на мобилках */}
                    {isMobileOpen && (
                        <Button aria-label="Закрыть меню навигации" variant="ghost" size="icon" className="h-8 w-8 lg:hidden -mr-2 text-muted-foreground hover:text-foreground" onClick={onMobileClose}>
                            <X className="w-4 h-4" />
                        </Button>
                    )}
                </div>

                <nav aria-label="Навигация Sphere" className="custom-scrollbar flex-1 space-y-3 overflow-x-hidden overflow-y-auto p-2">
                    {NAV_GROUPS.map(({ label: groupLabel, items }) => (
                        <div key={groupLabel} role="group" aria-label={groupLabel} className="space-y-1">
                            {(!isCollapsed || isMobileOpen) && (
                                <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">{groupLabel}</p>
                            )}
                            {items.map(({ href, label, icon: Icon }) => {
                                const isActive = pathname === href || pathname.startsWith(`${href}/`);
                                return (
                                    <Link
                                        key={href}
                                        href={href}
                                        onClick={handleNavClick}
                                        aria-label={label}
                                        aria-current={isActive ? "page" : undefined}
                                        className={cn(
                                            "group relative flex h-10 items-center gap-3 rounded-lg border text-sm transition-colors motion-reduce:transition-none",
                                            isCollapsed && !isMobileOpen ? "lg:justify-center lg:px-0" : "px-3",
                                            isActive
                                                ? "border-primary/20 bg-primary/10 text-primary"
                                                : "border-transparent text-muted-foreground hover:bg-secondary hover:text-foreground"
                                        )}
                                        title={isCollapsed && !isMobileOpen ? label : undefined}
                                    >
                                        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                                        {(!isCollapsed || isMobileOpen) && <span className="truncate font-medium">{label}</span>}
                                        {isActive && isCollapsed && !isMobileOpen && <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-md bg-primary" aria-hidden="true" />}
                                    </Link>
                                );
                            })}
                        </div>
                    ))}
                </nav>

                <div className="p-2 border-t border-border space-y-1">
                    <Button
                        variant="ghost"
                        size={(isCollapsed && !isMobileOpen) ? "icon" : "default"}
                        className={cn(
                            "w-full text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors",
                            (isCollapsed && !isMobileOpen) ? "lg:justify-center lg:px-0" : "justify-start gap-3"
                        )}
                        title={(isCollapsed && !isMobileOpen) ? "Настройки интерфейса" : undefined}
                        aria-label="Настройки интерфейса"
                        onClick={() => {
                            handleNavClick();
                            onOpenAppearance?.();
                        }}
                    >
                        <Settings className="w-4 h-4 shrink-0" />
                        {(!isCollapsed || isMobileOpen) && <span>Интерфейс</span>}
                    </Button>

                    <Button
                        variant="ghost"
                        size={(isCollapsed && !isMobileOpen) ? "icon" : "default"}
                        className={cn(
                            "w-full text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors",
                            (isCollapsed && !isMobileOpen) ? "lg:justify-center lg:px-0" : "justify-start gap-3"
                        )}
                        title={(isCollapsed && !isMobileOpen) ? "Выйти" : undefined}
                        aria-label="Выйти"
                        onClick={() => {
                            void signOut();
                            router.replace('/login');
                        }}
                    >
                        <LogOut className="w-4 h-4 shrink-0" />
                        {(!isCollapsed || isMobileOpen) && <span>Выйти</span>}
                    </Button>
                </div>

                {/* Collapse Toggle Handle - только для Desktop */}
                <button
                    type="button"
                    aria-label={isCollapsed ? "Развернуть навигацию" : "Свернуть навигацию"}
                    aria-expanded={!isCollapsed}
                    onClick={() => setIsCollapsed(!isCollapsed)}
                    className="absolute -right-3 top-14 z-50 hidden h-6 w-6 items-center justify-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:border-primary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:flex"
                >
                    {isCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
                </button>
            </aside>
        </>
    );
}
