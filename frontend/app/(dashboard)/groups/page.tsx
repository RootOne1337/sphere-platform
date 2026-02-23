'use client';
import { useState } from 'react';
import { useGroups, useCreateGroup, useDeleteGroup } from '@/lib/hooks/useGroups';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Plus, Trash2, FolderOpen } from 'lucide-react';

export default function GroupsPage() {
  const { data: groups, isLoading } = useGroups();
  const createGroup = useCreateGroup();
  const deleteGroup = useDeleteGroup();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#3B82F6');

  const handleCreate = async () => {
    await createGroup.mutateAsync({ name, description: description || undefined, color });
    setName('');
    setDescription('');
    setDialogOpen(false);
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Groups</h1>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="w-4 h-4 mr-2" />
              New Group
            </Button>
          </DialogTrigger>
          <DialogContent aria-describedby={undefined}>
            <DialogHeader>
              <DialogTitle>Create Group</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 pt-2">
              <div className="space-y-1">
                <Label>Name</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>Description</Label>
                <Input value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>Color</Label>
                <div className="flex gap-2 items-center">
                  <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="w-8 h-8 rounded cursor-pointer" />
                  <span className="text-sm text-muted-foreground">{color}</span>
                </div>
              </div>
              <Button onClick={handleCreate} disabled={createGroup.isPending || !name} className="w-full">
                {createGroup.isPending ? 'Creating…' : 'Create'}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : !groups || groups.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <FolderOpen className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No groups yet. Create your first group to organize devices.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {groups.map((group) => (
            <div
              key={group.id}
              className="rounded-lg border p-4 hover:bg-accent/50 transition-colors"
              style={{ borderLeftColor: group.color ?? undefined, borderLeftWidth: group.color ? 4 : undefined }}
            >
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-semibold">{group.name}</h3>
                  {group.description && (
                    <p className="text-xs text-muted-foreground mt-1">{group.description}</p>
                  )}
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="text-red-400 hover:text-red-300 h-7 w-7"
                  onClick={() => {
                    if (confirm(`Delete group "${group.name}"?`)) deleteGroup.mutate(group.id);
                  }}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
              <div className="flex gap-2 mt-3">
                <Badge variant="outline">
                  {group.total_devices} devices
                </Badge>
                <Badge variant="outline" className="text-green-400 border-green-600">
                  {group.online_devices} online
                </Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
