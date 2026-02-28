'use client';
import { useState } from 'react';
import { FolderOpen, Plus, Tag, Settings2, ShieldAlert, Loader2 } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Badge } from '@/src/shared/ui/badge';
import { Input } from '@/src/shared/ui/input';
import { useGroups, useCreateGroup, useDeleteGroup } from '@/lib/hooks/useGroups';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger } from '@/components/ui/dialog';
import { toast } from 'sonner';

export default function FleetGroupsPage() {
    const [search, setSearch] = useState('');
    const { data: groups = [], isLoading } = useGroups();
    const createGroup = useCreateGroup();
    const deleteGroup = useDeleteGroup();
    const [createOpen, setCreateOpen] = useState(false);
    const [newName, setNewName] = useState('');
    const [newDescription, setNewDescription] = useState('');

    const handleCreate = () => {
        if (!newName.trim()) return;
        createGroup.mutate({ name: newName, description: newDescription || undefined }, {
            onSuccess: () => {
                toast.success('Group created');
                setCreateOpen(false);
                setNewName('');
                setNewDescription('');
            },
            onError: () => toast.error('Failed to create group'),
        });
    };

    const handleDelete = (id: string, name: string) => {
        if (!confirm(`Delete group "${name}"?`)) return;
        deleteGroup.mutate(id, {
            onSuccess: () => toast.success('Group deleted'),
            onError: () => toast.error('Failed to delete group'),
        });
    };

    const filteredGroups = groups.filter(g =>
        g.name.toLowerCase().includes(search.toLowerCase()) ||
        (g.description || '').toLowerCase().includes(search.toLowerCase())
    );

    const getGroupStatus = (g: typeof groups[0]) => {
        if (g.total_devices === 0) return 'EMPTY';
        if (g.online_devices === g.total_devices) return 'ONLINE';
        if (g.online_devices === 0) return 'OFFLINE';
        return 'DEGRADED';
    };

    return (
        <div className="flex flex-col h-full bg-card">
            <div className="px-6 py-5 border-b border-border bg-muted flex flex-col md:flex-row md:items-center justify-between gap-4">
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
                        placeholder="Filter by group..."
                        className="w-64 h-9 bg-black/50 border-border font-mono text-xs focus-visible:ring-primary/50"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    />
                    <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                        <DialogTrigger asChild>
                            <Button variant="default" size="sm" className="h-9">
                                <Plus className="w-4 h-4 mr-2" />
                                Create Group
                            </Button>
                        </DialogTrigger>
                        <DialogContent>
                            <DialogHeader>
                                <DialogTitle>Create Fleet Group</DialogTitle>
                            </DialogHeader>
                            <div className="grid gap-3 py-2">
                                <Input placeholder="Group name" value={newName} onChange={e => setNewName(e.target.value)} />
                                <Input placeholder="Description (optional)" value={newDescription} onChange={e => setNewDescription(e.target.value)} />
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
                                <Button onClick={handleCreate} disabled={createGroup.isPending || !newName.trim()}>
                                    {createGroup.isPending ? 'Creating...' : 'Create'}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                </div>
            </div>

            <div className="p-6">
                {isLoading && (
                    <div className="flex items-center justify-center py-16 text-muted-foreground gap-2">
                        <Loader2 className="w-5 h-5 animate-spin" /> Loading groups...
                    </div>
                )}
                {!isLoading && filteredGroups.length === 0 && (
                    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
                        <FolderOpen className="w-10 h-10 opacity-30" />
                        <span className="text-sm font-mono">{groups.length === 0 ? 'No groups yet. Create your first one.' : 'No groups match your filter.'}</span>
                    </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filteredGroups.map(group => {
                        const status = getGroupStatus(group);
                        return (
                            <div key={group.id} className="bg-muted border border-border rounded-sm p-4 hover:border-primary/50 transition-colors group cursor-pointer relative overflow-hidden flex flex-col justify-between min-h-[160px]">
                                <div className="absolute top-0 right-0 w-16 h-16 bg-primary/5 rounded-bl-[100px] pointer-events-none transition-transform group-hover:scale-110" />

                                <div className="flex justify-between items-start mb-4 relative z-10">
                                    <div>
                                        <h3 className="text-sm font-bold font-mono text-foreground tracking-wide">{group.name}</h3>
                                        {group.description && (
                                            <div className="flex items-center gap-1 mt-1 text-xs text-muted-foreground font-mono">
                                                <Tag className="w-3 h-3" /> {group.description}
                                            </div>
                                        )}
                                    </div>
                                    <Badge variant="outline" className={`text-[9px] ${
                                        status === 'ONLINE' ? 'border-success text-success' :
                                        status === 'DEGRADED' ? 'border-warning text-warning' :
                                        status === 'OFFLINE' ? 'border-destructive text-destructive' :
                                        'border-muted-foreground text-muted-foreground'
                                    }`}>
                                        {status}
                                    </Badge>
                                </div>

                                <div className="flex items-end justify-between relative z-10 mt-auto">
                                    <div>
                                        <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-1">Endpoints</div>
                                        <div className="text-2xl font-mono font-bold text-foreground leading-none">
                                            {group.total_devices}
                                            {group.online_devices > 0 && (
                                                <span className="text-xs text-success ml-2">{group.online_devices} online</span>
                                            )}
                                        </div>
                                    </div>
                                    <div className="flex gap-2">
                                        <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
                                            onClick={(e) => { e.stopPropagation(); handleDelete(group.id, group.name); }}>
                                            <ShieldAlert className="w-4 h-4" />
                                        </Button>
                                        <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-primary">
                                            <Settings2 className="w-4 h-4" />
                                        </Button>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
