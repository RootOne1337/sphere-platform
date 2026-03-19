'use client';

import { Shield, X, Code2, Play, AlertTriangle } from 'lucide-react';
import { Badge } from '@/src/shared/ui/badge';

interface AuditDrawerProps {
    event: any | null; // В будущем строгая типизация
    onClose: () => void;
}

export function AuditDrawer({ event, onClose }: AuditDrawerProps) {
    if (!event) return null;

    // Mock JSON Data generator based on action
    const getMockDetails = (action: string) => {
        if (action?.includes('CONFIG')) {
            return {
                previous: { "vpn_mode": "split", "max_retries": 3 },
                new: { "vpn_mode": "full", "max_retries": 5 },
                diff: { "vpn_mode": "split -> full", "max_retries": "3 -> 5" }
            };
        }
        if (action?.includes('LOGIN')) {
            return {
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "timestamp": event.timestamp,
                "auth_method": "OAUTH2_AZURE_AD",
                "ip": event.ip,
                "mfa_passed": true
            };
        }
        return {
            "raw_request": `POST /api/v1/system/action\nHost: sphereadb.local\nAuthorization: Bearer ***\n\n{"action":"${action}","target":"${event.resource}"}`
        };
    };

    const details = getMockDetails(event.action);

    return (
        <div className="absolute top-0 right-0 w-[500px] h-full bg-card border-l border-border shadow-2xl z-40 flex flex-col transform transition-transform duration-300">

            {/* Drawer Header */}
            <div className="px-5 py-4 border-b border-border bg-muted flex items-center justify-between shrink-0">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-primary/10 rounded-sm">
                        <Shield className="w-4 h-4 text-primary" />
                    </div>
                    <div>
                        <h2 className="text-sm font-bold font-mono tracking-widest uppercase text-foreground">Event Inspector</h2>
                        <p className="text-[10px] text-muted-foreground font-mono mt-0.5">{event.id}</p>
                    </div>
                </div>
                <button onClick={onClose} className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-border rounded-sm transition-colors">
                    <X className="w-4 h-4" />
                </button>
            </div>

            {/* Drawer Body */}
            <div className="flex-1 overflow-auto custom-scrollbar p-5 space-y-6">

                {/* Metadata Section */}
                <div className="grid grid-cols-2 gap-4 border border-border rounded-sm p-4 bg-background">
                    <div>
                        <span className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground/60 block mb-1">Actor (User)</span>
                        <span className="text-sm font-mono text-primary/80">{event.user}</span>
                    </div>
                    <div>
                        <span className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground/60 block mb-1">Timestamp</span>
                        <span className="text-sm font-mono text-muted-foreground">{new Date(event.timestamp).toLocaleString()}</span>
                    </div>
                    <div>
                        <span className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground/60 block mb-1">Action Triggered</span>
                        <Badge variant="outline" className="text-[10px] border-border mt-1">{event.action}</Badge>
                    </div>
                    <div>
                        <span className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground/60 block mb-1">Source IP</span>
                        <span className="text-sm font-mono text-muted-foreground">{event.ip}</span>
                    </div>
                </div>

                {/* Alert Box for FAILED/WARNING */}
                {event.status !== 'SUCCESS' && (
                    <div className={`p-3 rounded-sm border flex gap-3 ${event.status === 'FAILED' ? 'bg-destructive/10 border-destructive/30' : 'bg-warning/10 border-warning/30'}`}>
                        <AlertTriangle className={`w-4 h-4 shrink-0 mt-0.5 ${event.status === 'FAILED' ? 'text-destructive' : 'text-warning'}`} />
                        <div>
                            <h4 className={`text-xs font-bold uppercase tracking-widest ${event.status === 'FAILED' ? 'text-destructive' : 'text-warning'}`}>{event.status}</h4>
                            <p className="text-[11px] font-mono text-muted-foreground mt-1">
                                System detected an anomaly during this event execution. Requires manual review.
                            </p>
                        </div>
                    </div>
                )}

                {/* JSON Payload Section */}
                <div>
                    <div className="flex items-center gap-2 mb-3">
                        <Code2 className="w-4 h-4 text-muted-foreground/60" />
                        <span className="text-xs uppercase font-bold tracking-widest text-muted-foreground">JSON Payload & Metadata</span>
                    </div>

                    <div className="bg-muted border border-border rounded-sm p-4 overflow-x-auto relative group">
                        <pre className="text-[11px] font-mono leading-relaxed text-success/80">
                            {JSON.stringify(details, null, 2)}
                        </pre>

                        {/* Decorative Play button */}
                        <button className="absolute top-2 right-2 p-1.5 bg-primary/20 hover:bg-primary/40 text-primary rounded-sm opacity-0 group-hover:opacity-100 transition-opacity" title="Replay Event (Mock)">
                            <Play className="w-3 h-3" />
                        </button>
                    </div>
                </div>

            </div>

        </div>
    );
}
