'use client';
import { useState } from 'react';
import { FolderOpen, Plus, Tag, Settings2, ShieldAlert } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Badge } from '@/src/shared/ui/badge';
import { Input } from '@/src/shared/ui/input';

const MOCK_GROUPS = [
    { id: '1', name: 'US-East Farm', tag: '@us-east', devices: 450, status: 'ONLINE', risk: 'LOW' },
    { id: '2', name: 'EU-West Cluster', tag: '@eu-west', devices: 120, status: 'DEGRADED', risk: 'MEDIUM' },
    { id: '3', name: 'QA Testing Pool', tag: '@qa-pool', devices: 15, status: 'OFFLINE', risk: 'HIGH' },
];

export default function FleetGroupsPage() {
    const [search, setSearch] = useState('');

    return (
        <div className="flex flex-col h-full bg-[#0A0A0A]">
            <div className="px-6 py-5 border-b border-[#222] bg-[#111] flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <FolderOpen className="w-5 h-5 text-primary" />
                        <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">Fleet Groups</h1>
                    </div>
                    <p className="text-xs text-muted-foreground font-mono">
                        Manage device topology, assign bulk policies, and group fleets logically.
                    </p>
                </div>

                <div className="flex items-center gap-3">
                    <Input
                        placeholder="Filter by group or tag..."
                        className="w-64 h-9 bg-black/50 border-[#333] font-mono text-xs focus-visible:ring-primary/50"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    />
                    <Button variant="default" size="sm" className="h-9">
                        <Plus className="w-4 h-4 mr-2" />
                        Create Group
                    </Button>
                </div>
            </div>

            <div className="p-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {MOCK_GROUPS.filter(g => g.name.toLowerCase().includes(search.toLowerCase()) || g.tag.includes(search)).map(group => (
                    <div key={group.id} className="bg-[#111] border border-[#222] rounded-sm p-4 hover:border-primary/50 transition-colors group cursor-pointer relative overflow-hidden flex flex-col justify-between min-h-[160px]">
                        <div className="absolute top-0 right-0 w-16 h-16 bg-primary/5 rounded-bl-[100px] pointer-events-none transition-transform group-hover:scale-110" />

                        <div className="flex justify-between items-start mb-4 relative z-10">
                            <div>
                                <h3 className="text-sm font-bold font-mono text-foreground tracking-wide">{group.name}</h3>
                                <div className="flex items-center gap-1 mt-1 text-xs text-muted-foreground font-mono">
                                    <Tag className="w-3 h-3" /> {group.tag}
                                </div>
                            </div>
                            <Badge variant="outline" className={`text-[9px] ${group.status === 'ONLINE' ? 'border-success text-success' :
                                    group.status === 'DEGRADED' ? 'border-warning text-warning' :
                                        'border-destructive text-destructive'
                                }`}>
                                {group.status}
                            </Badge>
                        </div>

                        <div className="flex items-end justify-between relative z-10 mt-auto">
                            <div>
                                <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-1">Endpoints</div>
                                <div className="text-2xl font-mono font-bold text-foreground leading-none">{group.devices}</div>
                            </div>
                            <div className="flex gap-2">
                                <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-primary">
                                    <ShieldAlert className="w-4 h-4" />
                                </Button>
                                <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-primary">
                                    <Settings2 className="w-4 h-4" />
                                </Button>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
