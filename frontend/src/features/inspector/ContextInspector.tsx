"use client";

import { X } from "lucide-react";
import { cn } from "@/src/shared/lib/utils";
import { useInspectorStore } from "./inspectorStore";
import { DeviceInspectorDetail } from "@/src/features/devices/DeviceInspectorDetail";

export function ContextInspector() {
    const { isOpen, contentType, contentId, payload, closeInspector } = useInspectorStore();

    return (
        <aside
            aria-label="Инспектор Sphere"
            aria-hidden={!isOpen}
            className={cn(
                "absolute right-0 top-0 z-40 flex h-full w-[min(400px,100vw)] flex-col border-l border-border bg-card shadow-2xl transition-transform duration-300 motion-reduce:transition-none",
                isOpen ? "translate-x-0" : "translate-x-full"
            )}
        >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div>
                    <h2 className="text-sm font-bold text-foreground">
                        {contentType === "device" && "Устройство"}
                        {contentType === "task" && "Задание"}
                        {contentType === "script" && "Скрипт"}
                        {contentType === "vpn" && "VPN"}
                        {!contentType && "Инспектор"}
                    </h2>
                    {contentId && (
                        <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                            ID: {contentId}
                        </p>
                    )}
                </div>
                <button
                    type="button"
                    aria-label="Закрыть инспектор"
                    tabIndex={isOpen ? 0 : -1}
                    onClick={closeInspector}
                    className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-6">
                {isOpen ? (
                    <>
                        {contentType === 'device' && payload && <DeviceInspectorDetail device={payload} />}
                        {contentType !== 'device' && (
                            <div className="space-y-2 text-sm text-muted-foreground">
                                <p>Данные этой панели пока недоступны.</p>
                                {contentType && <p className="text-xs">Тип: {contentType}{contentId ? ` · ID ${contentId}` : ''}</p>}
                            </div>
                        )}
                    </>
                ) : null}
            </div>
        </aside>
    );
}
