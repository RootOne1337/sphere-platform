'use client';

import { useThemeStore, ThemeType, DensityType } from '@/src/shared/store/themeStore';
import { Monitor, Moon, Sun, MonitorSmartphone, LayoutGrid, Shrink, Maximize, PaintBucket } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Badge } from '@/src/shared/ui/badge';

const THEMES: { id: ThemeType; label: string; icon: React.ReactNode; color: string }[] = [
    { id: 'neo-dark', label: 'Neo Dark', icon: <Moon className="w-4 h-4" />, color: 'bg-[#111] border-[#333]' },
    { id: 'matrix-green', label: 'Matrix', icon: <TerminalIcon />, color: 'bg-[#001100] border-[#00FF00]' },
    { id: 'deep-space', label: 'Deep Space', icon: <Monitor className="w-4 h-4" />, color: 'bg-[#050511] border-[#3366FF]' },
    { id: 'light-corporate', label: 'Corporate', icon: <Sun className="w-4 h-4" />, color: 'bg-[#F0F0F0] border-[#CCC] text-black' },
];

const DENSITIES: { id: DensityType; label: string; icon: React.ReactNode }[] = [
    { id: 'compact', label: 'Compact', icon: <Shrink className="w-4 h-4" /> },
    { id: 'cozy', label: 'Cozy', icon: <LayoutGrid className="w-4 h-4" /> },
    { id: 'spacious', label: 'Spacious', icon: <Maximize className="w-4 h-4" /> },
];

function TerminalIcon() {
    return <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" /></svg>
}

export function ThemeSwitcherModal({ onClose }: { onClose?: () => void }) {
    const { theme, density, setTheme, setDensity } = useThemeStore();

    return (
        <div className="flex flex-col gap-6 p-4">
            {/* Header */}
            <div className="flex items-center gap-3 border-b border-border pb-4">
                <div className="bg-primary/10 p-2 rounded-sm ring-1 ring-primary/20">
                    <PaintBucket className="w-5 h-5 text-primary" />
                </div>
                <div>
                    <h2 className="text-lg font-bold font-mono tracking-wider">UI Configuration</h2>
                    <p className="text-xs text-muted-foreground">Adjust the environment to your workstation needs</p>
                </div>
            </div>

            {/* Theme Selection */}
            <div className="space-y-3">
                <h3 className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground flex items-center gap-2">
                    Color Profiles <Badge variant="outline" className="text-[9px] px-1 py-0 border-primary text-primary">LIVE</Badge>
                </h3>
                <div className="grid grid-cols-2 gap-2">
                    {THEMES.map((t) => (
                        <button
                            key={t.id}
                            onClick={() => setTheme(t.id)}
                            className={`flex items-center gap-3 p-3 text-left rounded-sm border transition-all duration-200 ${theme === t.id
                                    ? 'ring-2 ring-primary border-transparent opacity-100 shadow-[0_0_15px_rgba(var(--primary),0.3)]'
                                    : 'border-border opacity-70 hover:opacity-100 hover:border-primary/50'
                                } ${t.color}`}
                        >
                            <div className={theme === t.id ? 'text-primary' : 'text-foreground'}>{t.icon}</div>
                            <span className={`text-xs font-mono font-bold ${theme === t.id ? 'text-primary' : ''}`}>
                                {t.label}
                            </span>
                        </button>
                    ))}
                </div>
            </div>

            {/* Density Selection */}
            <div className="space-y-3">
                <h3 className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                    Interface Density / Scaling
                </h3>
                <div className="grid grid-cols-3 gap-2">
                    {DENSITIES.map((d) => (
                        <button
                            key={d.id}
                            onClick={() => setDensity(d.id)}
                            className={`flex flex-col items-center justify-center gap-2 p-3 rounded-sm border transition-all duration-200 ${density === d.id
                                    ? 'bg-primary/10 border-primary text-primary shadow-[0_0_10px_rgba(var(--primary),0.2)]'
                                    : 'bg-transparent border-border hover:bg-white/5 text-muted-foreground hover:text-foreground'
                                }`}
                        >
                            {d.icon}
                            <span className="text-[10px] font-mono font-bold uppercase tracking-wider">{d.label}</span>
                        </button>
                    ))}
                </div>
            </div>

            {/* Visual Demo */}
            <div className="mt-4 p-4 border border-dashed border-border rounded-sm bg-black/20 space-y-3">
                <p className="text-[10px] text-muted-foreground uppercase font-bold text-center mb-2">Live Preview Area</p>
                <div className="flex gap-2 justify-center">
                    <Button variant="default" size="sm">Primary Action</Button>
                    <Button variant="outline" size="sm">Secondary</Button>
                    <Button variant="destructive" size="sm">Danger</Button>
                </div>
            </div>

            {onClose && (
                <Button variant="outline" className="w-full mt-2" onClick={onClose}>
                    Close Matrix Configurator
                </Button>
            )}
        </div>
    );
}
