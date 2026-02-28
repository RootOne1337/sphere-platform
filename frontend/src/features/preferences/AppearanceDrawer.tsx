'use client';

import { Paintbrush, X, MonitorPlay, Palette, Type, LayoutGrid } from 'lucide-react';
import { useUIStore } from '@/src/shared/store/useUIStore';
import { Button } from '@/src/shared/ui/button';

interface AppearanceDrawerProps {
    open: boolean;
    onClose: () => void;
}

export function AppearanceDrawer({ open, onClose }: AppearanceDrawerProps) {
    const { theme, setTheme, accentColor, setAccentColor, fontSize, setFontSize, density, setDensity } = useUIStore();

    if (!open) return null;

    return (
        <>
            <div
                className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[100] transition-opacity animate-in fade-in"
                onClick={onClose}
            />

            <div className="fixed top-0 right-0 bottom-0 w-[350px] bg-[#0A0A0A] border-l border-[#222] z-[110] flex flex-col shadow-2xl animate-in slide-in-from-right duration-300">

                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-[#222] bg-[#111]">
                    <div className="flex items-center gap-2">
                        <Paintbrush className="w-4 h-4 text-primary" />
                        <span className="font-mono font-bold tracking-widest text-xs uppercase uppercase pt-1">Preferences</span>
                    </div>
                    <Button variant="ghost" size="icon" className="h-6 w-6 rounded-sm text-muted-foreground hover:text-foreground hover:bg-[#222]" onClick={onClose}>
                        <X className="w-4 h-4" />
                    </Button>
                </div>

                <div className="flex-1 overflow-y-auto p-5 space-y-8 custom-scrollbar">

                    {/* Accent Colors */}
                    <div className="space-y-3">
                        <div className="flex items-center gap-2 text-muted-foreground">
                            <Palette className="w-3.5 h-3.5" />
                            <span className="text-[10px] font-bold uppercase tracking-widest">Accent Color</span>
                        </div>
                        <div className="grid grid-cols-5 gap-2">
                            {[
                                { name: 'violet', value: '#8b5cf6', tw: 'bg-violet-500' },
                                { name: 'blue', value: '#3b82f6', tw: 'bg-blue-500' },
                                { name: 'emerald', value: '#10b981', tw: 'bg-emerald-500' },
                                { name: 'rose', value: '#f43f5e', tw: 'bg-rose-500' },
                                { name: 'amber', value: '#f59e0b', tw: 'bg-amber-500' },
                            ].map((color) => (
                                <button
                                    key={color.name}
                                    onClick={() => setAccentColor(color.name as any)}
                                    className={`aspect-square rounded-full border-2 transition-all flex justify-center items-center ${accentColor === color.name ? 'border-primary' : 'border-transparent hover:scale-110'}`}
                                >
                                    <div className={`w-6 h-6 rounded-full ${color.tw} shadow-lg`} />
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Scaling / Font Size */}
                    <div className="space-y-3">
                        <div className="flex items-center gap-2 text-muted-foreground">
                            <Type className="w-3.5 h-3.5" />
                            <span className="text-[10px] font-bold uppercase tracking-widest">Interface Scaling</span>
                        </div>
                        <div className="flex bg-[#111] border border-[#222] rounded-sm p-1">
                            {['sm', 'base', 'lg'].map((size) => (
                                <button
                                    key={size}
                                    onClick={() => setFontSize(size as any)}
                                    className={`flex-1 py-1.5 text-xs font-mono font-bold rounded-sm transition-colors ${fontSize === size ? 'bg-[#333] text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                                >
                                    {size.toUpperCase()}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* UI Density */}
                    <div className="space-y-3">
                        <div className="flex items-center gap-2 text-muted-foreground">
                            <LayoutGrid className="w-3.5 h-3.5" />
                            <span className="text-[10px] font-bold uppercase tracking-widest">UI Density</span>
                        </div>
                        <div className="flex flex-col gap-2">
                            {['compact', 'comfortable', 'spacious'].map((d) => (
                                <button
                                    key={d}
                                    onClick={() => setDensity(d as any)}
                                    className={`p-3 text-left border rounded-sm transition-colors flex flex-col gap-1 ${density === d ? 'border-primary bg-primary/5' : 'border-[#333] bg-[#111] hover:border-[#444]'}`}
                                >
                                    <span className={`font-mono text-xs font-bold ${density === d ? 'text-primary' : 'text-foreground'}`}>{d.charAt(0).toUpperCase() + d.slice(1)}</span>
                                    <span className="text-[10px] text-muted-foreground block text-xs">
                                        {d === 'compact' && 'Max data density (NOC Mode)'}
                                        {d === 'comfortable' && 'Balanced padding & margins'}
                                        {d === 'spacious' && 'Touch-friendly easy reading'}
                                    </span>
                                </button>
                            ))}
                        </div>
                    </div>

                </div>

            </div>
        </>
    );
}
