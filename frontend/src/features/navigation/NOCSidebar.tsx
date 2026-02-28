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
    ChevronLeft
} from "lucide-react";

const NAV_ITEMS = [
    { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
    { href: "/monitoring", label: "Infrastructure", icon: Activity },
    { href: "/devices", label: "Fleet Matrix", icon: Monitor },
    { href: "/stream", label: "Device Stream", icon: Monitor },
    { href: "/tasks", label: "Task Engine", icon: ListTodo },
    { href: "/vpn", label: "Tunneling", icon: Wifi },
    { href: "/scripts", label: "Scripts", icon: Code2 },
    { href: "/groups", label: "Groups", icon: FolderOpen },
    { href: "/discovery", label: "Discovery", icon: Radar },
    { href: "/users", label: "Users", icon: Users },
    { href: "/audit", label: "Audit Log", icon: ScrollText },
    { href: "/logs", label: "Sys Logs", icon: FileText },
    { href: "/updates", label: "Updates", icon: RefreshCw },
    { href: "/webhooks", label: "Webhooks", icon: Webhook },
];

interface NOCSidebarProps {
    onOpenAppearance?: () => void;
}

export function NOCSidebar({ onOpenAppearance }: NOCSidebarProps) {
    const pathname = usePathname();
    const [isCollapsed, setIsCollapsed] = useState(true);

    return (
        <aside
            className={cn(
                "relative flex flex-col h-full bg-[#0A0A0A] border-r border-[#222] transition-all duration-300 z-50",
                isCollapsed ? "w-14" : "w-56"
            )}
            onMouseEnter={() => setIsCollapsed(false)}
            onMouseLeave={() => setIsCollapsed(true)}
        >
            <div className="flex h-12 shrink-0 items-center justify-center border-b border-[#222]">
                {isCollapsed ? (
                    <div className="w-6 h-6 bg-primary rounded-sm flex items-center justify-center font-bold text-black text-xs">
                        S
                    </div>
                ) : (
                    <div className="flex items-center gap-2 w-full px-4 text-primary font-mono font-bold tracking-wider">
                        <div className="w-5 h-5 bg-primary rounded-sm text-black flex items-center justify-center">S</div>
                        SPHERE<span className="text-muted-foreground font-normal text-xs">NOC</span>
                    </div>
                )}
            </div>

            <nav className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-1 custom-scrollbar">
                {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
                    const isActive = pathname.startsWith(href);
                    return (
                        <Link
                            key={href}
                            href={href}
                            className={cn(
                                "flex items-center gap-3 rounded-sm text-sm transition-colors relative group h-9",
                                isCollapsed ? "justify-center px-0" : "px-3",
                                isActive
                                    ? "bg-primary/10 text-primary border border-primary/20"
                                    : "text-muted-foreground hover:bg-[#1A1A1A] hover:text-foreground border border-transparent"
                            )}
                            title={isCollapsed ? label : undefined}
                        >
                            <Icon className="w-4 h-4 shrink-0" />
                            {!isCollapsed && (
                                <span className="truncate font-medium">{label}</span>
                            )}

                            {isActive && isCollapsed && (
                                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-primary rounded-r-md" />
                            )}
                        </Link>
                    );
                })}
            </nav>

            <div className="p-2 border-t border-[#222] space-y-1">
                <Button
                    variant="ghost"
                    size={isCollapsed ? "icon" : "default"}
                    className={cn(
                        "w-full text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors",
                        isCollapsed ? "justify-center px-0" : "justify-start gap-3"
                    )}
                    title={isCollapsed ? "Appearance Settings" : undefined}
                    onClick={onOpenAppearance}
                >
                    <Settings className="w-4 h-4 shrink-0" />
                    {!isCollapsed && <span>Preferences</span>}
                </Button>

                <Button
                    variant="ghost"
                    size={isCollapsed ? "icon" : "default"}
                    className={cn(
                        "w-full text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors",
                        isCollapsed ? "justify-center px-0" : "justify-start gap-3"
                    )}
                    title={isCollapsed ? "Sign out" : undefined}
                // onClick={() => { logout logic }}
                >
                    <LogOut className="w-4 h-4 shrink-0" />
                    {!isCollapsed && <span>Sign Out</span>}
                </Button>
            </div>

            {/* Collapse Toggle Handle */}
            <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                className="absolute -right-3 top-12 flex h-6 w-6 items-center justify-center rounded-full border border-[#222] bg-[#0A0A0A] text-muted-foreground hover:text-foreground hover:border-primary z-50 transition-colors focus:outline-none"
            >
                {isCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
            </button>
        </aside>
    );
}
