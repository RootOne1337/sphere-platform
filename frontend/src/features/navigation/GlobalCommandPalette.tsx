"use client";

import * as React from "react";
import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { Search, Monitor, Code2, Wifi, Activity, PaintBucket, ArrowLeft, ScrollText } from "lucide-react";
import { useCommandPaletteStore } from "./commandPaletteStore";
import { useInspectorStore } from "@/src/features/inspector/inspectorStore";
import { ThemeSwitcherModal } from "@/src/features/settings/ThemeSwitcherModal";

export function GlobalCommandPalette() {
    const router = useRouter();
    const { isOpen, toggle, close } = useCommandPaletteStore();
    const { openInspector } = useInspectorStore();
    const [activeMenu, setActiveMenu] = React.useState<"main" | "themes">("main");

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
            setTimeout(() => setActiveMenu("main"), 200);
        }
    }, [isOpen]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-start justify-center pt-[15vh]">
            <div className="w-full max-w-2xl bg-[#0A0A0A] border border-[#333] rounded-sm shadow-2xl overflow-hidden relative min-h-[400px]">

                {/* Главное меню команд */}
                <div className={`absolute inset-0 transition-transform duration-300 ${activeMenu === "main" ? "translate-x-0" : "-translate-x-full"}`}>
                    <Command
                        className="w-full h-full flex flex-col"
                        onKeyDown={(e) => {
                            if (e.key === "Escape") close();
                        }}
                    >
                        <div className="flex items-center border-b border-[#333] px-3 font-mono shrink-0 h-[49px]">
                            <Search className="w-4 h-4 text-primary shrink-0 mr-2" />
                            <Command.Input
                                autoFocus={activeMenu === "main"}
                                className="w-full bg-transparent h-full outline-none text-foreground placeholder:text-muted-foreground text-sm"
                                placeholder="Search command or jump to..."
                            />
                            <div className="text-[10px] text-muted-foreground bg-[#222] px-1.5 py-0.5 rounded-sm">ESC</div>
                        </div>

                        <Command.List className="flex-1 overflow-y-auto custom-scrollbar p-2">
                            <Command.Empty className="p-4 text-center text-sm text-muted-foreground font-mono">
                                No results found.
                            </Command.Empty>

                            <Command.Group heading="Navigation" className="text-xs font-mono text-muted-foreground px-2 py-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:font-semibold">
                                <Command.Item
                                    onSelect={() => { router.push("/dashboard"); close(); }}
                                    className="flex items-center px-2 py-2 text-sm text-foreground hover:bg-[#1A1A1A] hover:text-primary cursor-pointer rounded-sm mb-1 aria-selected:bg-[#1A1A1A] aria-selected:text-primary transition-colors"
                                >
                                    <Activity className="w-4 h-4 mr-2" />
                                    Go to Overview
                                </Command.Item>
                                <Command.Item
                                    onSelect={() => { router.push("/devices"); close(); }}
                                    className="flex items-center px-2 py-2 text-sm text-foreground hover:bg-[#1A1A1A] hover:text-primary cursor-pointer rounded-sm mb-1 aria-selected:bg-[#1A1A1A] aria-selected:text-primary transition-colors"
                                >
                                    <Monitor className="w-4 h-4 mr-2" />
                                    Go to Fleet Matrix
                                </Command.Item>
                                <Command.Item
                                    onSelect={() => { router.push("/audit"); close(); }}
                                    className="flex items-center px-2 py-2 text-sm text-foreground hover:bg-[#1A1A1A] hover:text-primary cursor-pointer rounded-sm mb-1 aria-selected:bg-[#1A1A1A] aria-selected:text-primary transition-colors"
                                >
                                    <ScrollText className="w-4 h-4 mr-2" />
                                    Go to Security Audit
                                </Command.Item>
                            </Command.Group>

                            <Command.Group heading="Preferences & Settings" className="text-xs font-mono text-muted-foreground px-2 py-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:font-semibold mt-2">
                                <Command.Item
                                    onSelect={() => setActiveMenu("themes")}
                                    className="flex items-center px-2 py-2 text-sm text-foreground hover:bg-[#1A1A1A] hover:text-primary cursor-pointer rounded-sm mb-1 aria-selected:bg-[#1A1A1A] aria-selected:text-primary transition-colors"
                                >
                                    <PaintBucket className="w-4 h-4 mr-2" />
                                    UI Configuration (Themes & Scaling)
                                </Command.Item>
                            </Command.Group>

                            <Command.Group heading="Quick Actions" className="text-xs font-mono text-muted-foreground px-2 py-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:font-semibold mt-2">
                                <Command.Item
                                    onSelect={() => { openInspector("vpn", "global"); close(); }}
                                    className="flex items-center px-2 py-2 text-sm text-foreground hover:bg-[#1A1A1A] hover:text-primary cursor-pointer rounded-sm mb-1 aria-selected:bg-[#1A1A1A] aria-selected:text-primary transition-colors"
                                >
                                    <Wifi className="w-4 h-4 mr-2" />
                                    Inspect VPN Health
                                </Command.Item>
                                <Command.Item
                                    onSelect={() => { openInspector("script", "new"); close(); }}
                                    className="flex items-center px-2 py-2 text-sm text-foreground hover:bg-[#1A1A1A] hover:text-primary cursor-pointer rounded-sm aria-selected:bg-[#1A1A1A] aria-selected:text-primary transition-colors"
                                >
                                    <Code2 className="w-4 h-4 mr-2" />
                                    New Quick Script
                                </Command.Item>
                            </Command.Group>
                        </Command.List>
                    </Command>
                </div>

                {/* Меню настройки тем */}
                <div className={`absolute inset-0 bg-[#0A0A0A] transition-transform duration-300 overflow-y-auto custom-scrollbar ${activeMenu === "themes" ? "translate-x-0" : "translate-x-full"}`}>
                    <div className="sticky top-0 bg-[#0A0A0A] border-b border-[#333] z-10 flex items-center px-4 py-3 cursor-pointer hover:text-primary transition-colors" onClick={() => setActiveMenu("main")}>
                        <ArrowLeft className="w-4 h-4 mr-2" />
                        <span className="text-xs font-mono font-bold uppercase tracking-widest">Back to Search</span>
                    </div>
                    <ThemeSwitcherModal onClose={close} />
                </div>

            </div>

            {/* Клик по бэкграунду для закрытия */}
            <div className="absolute inset-0 z-[-1]" onClick={close} />
        </div>
    );
}
