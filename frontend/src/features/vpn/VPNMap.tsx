'use client';

import { useMemo } from 'react';

interface VPNMapProps {
    tunnels: any[];
}

export function VPNMap({ tunnels }: VPNMapProps) {
    // Простая SVG карта мира (демонстрационная) со случайными "дугами"
    const arcs = useMemo(() => {
        return Array.from({ length: 8 }).map((_, i) => {
            const startX = 400 + (Math.random() * 50 - 25);
            const startY = 150 + (Math.random() * 30 - 15);
            const endX = Math.random() * 800;
            const endY = Math.random() * 400;

            const cx = (startX + endX) / 2;
            const cy = (startY + endY) / 2 - 100; // Curve

            return {
                id: i,
                d: `M ${startX} ${startY} Q ${cx} ${cy} ${endX} ${endY}`,
                opacity: Math.random() * 0.5 + 0.2,
                active: Math.random() > 0.3
            };
        });
    }, []);

    return (
        <div className="relative w-full h-[350px] bg-card rounded-sm overflow-hidden border border-border">

            {/* Decorative Grid Background */}
            <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] pointer-events-none" />

            {/* SVG Map Container */}
            <svg viewBox="0 0 800 400" className="w-full h-full opacity-60">
                <defs>
                    <radialGradient id="masterNode" cx="50%" cy="50%" r="50%">
                        <stop offset="0%" stopColor="#22c55e" stopOpacity="1" />
                        <stop offset="100%" stopColor="#22c55e" stopOpacity="0" />
                    </radialGradient>
                </defs>

                {/* Abstract World Map Dotted Pattern (simplified) */}
                {Array.from({ length: 150 }).map((_, i) => (
                    <circle
                        key={`dot-${i}`}
                        cx={Math.random() * 800}
                        cy={Math.random() * 400}
                        r={Math.random() * 1.5 + 0.5}
                        fill="#333"
                        opacity={Math.random() * 0.5 + 0.1}
                    />
                ))}

                {/* Animated Arcs */}
                {arcs.map(arc => (
                    <g key={`arc-${arc.id}`}>
                        <path
                            d={arc.d}
                            fill="none"
                            stroke={arc.active ? "#22c55e" : "#ef4444"}
                            strokeWidth={1.5}
                            opacity={arc.opacity}
                            className={arc.active ? "animate-pulse" : ""}
                            strokeDasharray="4 4"
                        />
                        <circle
                            cx={arc.d.split(' ')[arc.d.split(' ').length - 2]}
                            cy={arc.d.split(' ')[arc.d.split(' ').length - 1]}
                            r={3}
                            fill={arc.active ? "#22c55e" : "#ef4444"}
                        />
                    </g>
                ))}

                {/* Master Server Node (Center) */}
                <circle cx="400" cy="150" r="15" fill="url(#masterNode)" className="animate-pulse" />
                <circle cx="400" cy="150" r="4" fill="#22c55e" />

                <text x="415" y="154" fill="#fff" fontSize="10" fontFamily="monospace" opacity="0.8">FRAMEWORK-MASTER [FRA-1]</text>
            </svg>

            {/* Overlay Stats */}
            <div className="absolute bottom-4 left-4 flex gap-4 pointer-events-none">
                <div className="bg-black/80 border border-border px-3 py-2 rounded-sm backdrop-blur-md">
                    <div className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Active Tunnels</div>
                    <div className="text-xl font-mono text-primary animate-pulse">{arcs.filter(a => a.active).length}</div>
                </div>
                <div className="bg-black/80 border border-border px-3 py-2 rounded-sm backdrop-blur-md">
                    <div className="text-[9px] uppercase font-bold tracking-widest text-[#555]">Global Latency</div>
                    <div className="text-xl font-mono text-foreground">{'< 45ms'}</div>
                </div>
            </div>
        </div>
    );
}
