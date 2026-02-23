'use client';
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
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
import { Plus, Trash2, Webhook } from 'lucide-react';

interface WebhookItem {
  id: string;
  name: string;
  url: string;
  events: string[];
  tags: string[];
  is_active: boolean;
  secret: string | null;
  created_at: string;
}

interface WebhookListResponse {
  items: WebhookItem[];
  total: number;
}

export default function WebhooksPage() {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery<WebhookListResponse>({
    queryKey: ['webhooks'],
    queryFn: async () => {
      const { data } = await api.get('/n8n/webhooks');
      return data;
    },
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [events, setEvents] = useState('task.completed,device.online');
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);

  const createWebhook = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/n8n/webhooks', {
        name,
        url,
        events: events.split(',').map((e) => e.trim()).filter(Boolean),
      });
      return data as WebhookItem;
    },
    onSuccess: (data) => {
      setCreatedSecret(data.secret);
      setName('');
      setUrl('');
      qc.invalidateQueries({ queryKey: ['webhooks'] });
    },
  });

  const deleteWebhook = useMutation({
    mutationFn: (id: string) => api.delete(`/n8n/webhooks/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webhooks'] }),
  });

  const toggleWebhook = useMutation({
    mutationFn: async ({ id, isActive }: { id: string; isActive: boolean }) => {
      await api.patch(`/n8n/webhooks/${id}`, { is_active: isActive });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webhooks'] }),
  });

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Webhooks (n8n)</h1>
        <Dialog open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) setCreatedSecret(null); }}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="w-4 h-4 mr-2" />
              New Webhook
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Register Webhook</DialogTitle>
            </DialogHeader>
            {createdSecret ? (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  Webhook created. Save this secret — it won't be shown again.
                </p>
                <code className="block p-3 rounded bg-muted text-sm break-all select-all">{createdSecret}</code>
                <Button className="w-full" onClick={() => { setDialogOpen(false); setCreatedSecret(null); }}>
                  Done
                </Button>
              </div>
            ) : (
              <div className="space-y-4 pt-2">
                <div className="space-y-1">
                  <Label>Name</Label>
                  <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="n8n-task-callback" />
                </div>
                <div className="space-y-1">
                  <Label>URL</Label>
                  <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://n8n.example.com/webhook/..." />
                </div>
                <div className="space-y-1">
                  <Label>Events (comma separated)</Label>
                  <Input value={events} onChange={(e) => setEvents(e.target.value)} placeholder="task.completed,device.online" />
                </div>
                <Button onClick={() => createWebhook.mutate()} disabled={createWebhook.isPending || !name || !url} className="w-full">
                  {createWebhook.isPending ? 'Creating…' : 'Create'}
                </Button>
              </div>
            )}
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : !data || data.items.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <Webhook className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No webhooks registered. Connect n8n to automate workflows.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {data.items.map((wh) => (
            <div key={wh.id} className="flex items-center justify-between p-4 rounded border hover:bg-accent/50">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <p className="font-medium">{wh.name}</p>
                  <Badge variant={wh.is_active ? 'default' : 'outline'}>
                    {wh.is_active ? 'Active' : 'Disabled'}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground truncate max-w-lg">{wh.url}</p>
                <div className="flex gap-1 flex-wrap">
                  {wh.events.map((ev) => (
                    <Badge key={ev} variant="outline" className="text-xs">{ev}</Badge>
                  ))}
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => toggleWebhook.mutate({ id: wh.id, isActive: !wh.is_active })}
                >
                  {wh.is_active ? 'Disable' : 'Enable'}
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="text-red-400 hover:text-red-300"
                  onClick={() => {
                    if (confirm(`Delete webhook "${wh.name}"?`)) deleteWebhook.mutate(wh.id);
                  }}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
