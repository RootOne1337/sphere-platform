"use client";

import { X } from "lucide-react";
import { cn } from "@/src/shared/lib/utils";
import { useInspectorStore } from "./inspectorStore";
import { DeviceInspectorDetail } from "@/src/features/devices/DeviceInspectorDetail";

export function ContextInspector() {
    const { isOpen, contentType, contentId, payload, closeInspector } = useInspectorStore();

    return (
        <aside
            className={cn(
                "absolute right-0 top-0 h-full w-[400px] bg-[#0A0A0A] border-l border-[#222] shadow-2xl transition-transform duration-300 z-40 flex flex-col",
                isOpen ? "translate-x-0" : "translate-x-full"
            )}
        >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#222]">
                <div>
                    <h2 className="text-sm font-bold text-foreground">
                        {contentType === "device" && "Device Inspector"}
                        {contentType === "task" && "Task Details"}
                        {contentType === "script" && "Script Viewer"}
                        {contentType === "vpn" && "Tunnel Config"}
                        {!contentType && "Inspector"}
                    </h2>
                    {contentId && (
                        <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                            ID: {contentId}
                        </p>
                    )}
                </div>
                <button
                    onClick={closeInspector}
                    className="p-1 rounded-sm text-muted-foreground hover:bg-[#1A1A1A] hover:text-white transition-colors"
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
                            <div className="text-xs text-muted-foreground font-mono">
                                {/* Fallback */}
                                <p>Content Type: {contentType}</p>
                                <p>Associated ID: {contentId}</p>
                                <p className="mt-4 text-[#555]">Awaiting module initialization...</p>
                            </div>
                        )}
                    </>
                ) : null}
            </div>
        </aside>
    );
}
