"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
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
    MapPin
} from "lucide-react";

const NAV_ITEMS = [
    { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
    { href: "/monitoring", label: "Infrastructure", icon: Activity },
    { href: "/devices", label: "Fleet Matrix", icon: Monitor },
    { href: "/stream", label: "Device Stream", icon: Monitor },
    { href: "/tasks", label: "Task Engine", icon: ListTodo },
    { href: "/orchestration", label: "Orchestration", icon: GitBranch },
    { href: "/vpn", label: "Tunneling", icon: Wifi },
    { href: "/scripts", label: "Scripts", icon: Code2 },
    { href: "/groups", label: "Groups", icon: FolderOpen },
    { href: "/locations", label: "Locations", icon: MapPin },
    { href: "/discovery", label: "Discovery", icon: Radar },
    { href: "/users", label: "Users", icon: Users },
    { href: "/audit", label: "Audit Log", icon: ScrollText },
    { href: "/logs", label: "Sys Logs", icon: FileText },
    { href: "/updates", label: "Updates", icon: RefreshCw },
    { href: "/webhooks", label: "Webhooks", icon: Webhook },
    { href: "/settings", label: "Sys Config", icon: UserCog },
];

interface NOCSidebarProps {
    onOpenAppearance?: () => void;
    isMobileOpen?: boolean;
    onMobileClose?: () => void;
}

export function NOCSidebar({ onOpenAppearance, isMobileOpen, onMobileClose }: NOCSidebarProps) {
    const pathname = usePathname();
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
                <div
                    className="fixed inset-0 bg-foreground/30 z-40 lg:hidden backdrop-blur-sm"
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
                <div className="flex h-12 shrink-0 items-center justify-between lg:justify-center px-4 lg:px-0 border-b border-border">
                    {isCollapsed && !isMobileOpen ? (
                        <div className="w-6 h-6 bg-primary rounded-sm flex items-center justify-center font-bold text-primary-foreground text-xs">
                            S
                        </div>
                    ) : (
                        <div className="flex items-center gap-2 w-full px-4 text-primary font-mono font-bold tracking-wider">
                            <div className="w-5 h-5 bg-primary rounded-sm text-black flex items-center justify-center">S</div>
                            SPHERE<span className="text-muted-foreground font-normal text-xs">NOC</span>
                        </div>
                    )}
                    {/* Кнопка закрытия на мобилках */}
                    {isMobileOpen && (
                        <Button variant="ghost" size="icon" className="h-8 w-8 lg:hidden -mr-2 text-muted-foreground hover:text-foreground" onClick={onMobileClose}>
                            <X className="w-4 h-4" />
                        </Button>
                    )}
                </div>

                <nav className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-1 custom-scrollbar">
                    {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
                        const isActive = pathname.startsWith(href);
                        return (
                            <Link
                                key={href}
                                href={href}
                                onClick={handleNavClick}
                                className={cn(
                                    "flex items-center gap-3 rounded-sm text-sm transition-colors relative group h-9",
                                    isCollapsed && !isMobileOpen ? "lg:justify-center lg:px-0" : "px-3",
                                    isActive
                                        ? "bg-primary/10 text-primary border border-primary/20"
                                        : "text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent"
                                )}
                                title={(isCollapsed && !isMobileOpen) ? label : undefined}
                            >
                                <Icon className="w-4 h-4 shrink-0" />
                                {(!isCollapsed || isMobileOpen) && (
                                    <span className="truncate font-medium">{label}</span>
                                )}

                                {isActive && isCollapsed && !isMobileOpen && (
                                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-primary rounded-r-md" />
                                )}
                            </Link>
                        );
                    })}
                </nav>

                <div className="p-2 border-t border-border space-y-1">
                    <Button
                        variant="ghost"
                        size={(isCollapsed && !isMobileOpen) ? "icon" : "default"}
                        className={cn(
                            "w-full text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors",
                            (isCollapsed && !isMobileOpen) ? "lg:justify-center lg:px-0" : "justify-start gap-3"
                        )}
                        title={(isCollapsed && !isMobileOpen) ? "Appearance Settings" : undefined}
                        onClick={() => {
                            handleNavClick();
                            onOpenAppearance?.();
                        }}
                    >
                        <Settings className="w-4 h-4 shrink-0" />
                        {(!isCollapsed || isMobileOpen) && <span>Preferences</span>}
                    </Button>

                    <Button
                        variant="ghost"
                        size={(isCollapsed && !isMobileOpen) ? "icon" : "default"}
                        className={cn(
                            "w-full text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors",
                            (isCollapsed && !isMobileOpen) ? "lg:justify-center lg:px-0" : "justify-start gap-3"
                        )}
                        title={(isCollapsed && !isMobileOpen) ? "Sign out" : undefined}
                    // onClick={() => { logout logic }}
                    >
                        <LogOut className="w-4 h-4 shrink-0" />
                        {(!isCollapsed || isMobileOpen) && <span>Sign Out</span>}
                    </Button>
                </div>

                {/* Collapse Toggle Handle - только для Desktop */}
                <button
                    onClick={() => setIsCollapsed(!isCollapsed)}
                    className="hidden lg:flex absolute -right-3 top-12 h-6 w-6 items-center justify-center rounded-full border border-border bg-card text-muted-foreground hover:text-foreground hover:border-primary z-50 transition-colors focus:outline-none"
                >
                    {isCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
                </button>
            </aside>
        </>
    );
}
