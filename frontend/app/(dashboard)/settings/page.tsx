'use client';
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Plus, Trash2, Shield, Key } from 'lucide-react';

/* ── MFA Tab ────────────────────────────────────────────────────────────── */
function MfaTab() {
  const { user } = useAuthStore();
  const qc = useQueryClient();
  const [setupData, setSetupData] = useState<{ qr_code: string; secret: string } | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState('');

  const setupMfa = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/auth/mfa/setup');
      return data as { qr_code: string; secret: string };
    },
    onSuccess: (data) => setSetupData(data),
  });

  const verifyMfa = useMutation({
    mutationFn: async () => {
      await api.post('/auth/mfa/verify-setup', { code });
      return true;
    },
    onSuccess: () => {
      setSetupData(null);
      setCode('');
      setError('');
      qc.invalidateQueries({ queryKey: ['me'] });
    },
    onError: () => setError('Invalid code. Try again.'),
  });

  const disableMfa = useMutation({
    mutationFn: () => api.delete('/auth/mfa'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Shield className="w-5 h-5" />
          Two-Factor Authentication
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <span className="text-sm">Status:</span>
          <Badge variant={user?.mfa_enabled ? 'default' : 'outline'}>
            {user?.mfa_enabled ? 'Enabled' : 'Disabled'}
          </Badge>
        </div>

        {user?.mfa_enabled ? (
          <Button variant="destructive" onClick={() => disableMfa.mutate()} disabled={disableMfa.isPending}>
            Disable MFA
          </Button>
        ) : setupData ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.)
            </p>
            <div className="flex justify-center">
              <img src={`data:image/png;base64,${setupData.qr_code}`} alt="MFA QR Code" className="w-48 h-48" />
            </div>
            <div className="text-xs text-muted-foreground text-center">
              Manual key: <code className="text-foreground">{setupData.secret}</code>
            </div>
            <div className="space-y-2">
              <Label>Enter code from app</Label>
              <div className="flex gap-2">
                <Input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  maxLength={8}
                  placeholder="123456"
                  inputMode="numeric"
                />
                <Button onClick={() => verifyMfa.mutate()} disabled={verifyMfa.isPending || code.length < 6}>
                  Verify
                </Button>
              </div>
              {error && <p className="text-sm text-red-500">{error}</p>}
            </div>
          </div>
        ) : (
          <Button onClick={() => setupMfa.mutate()} disabled={setupMfa.isPending}>
            {setupMfa.isPending ? 'Generating…' : 'Setup MFA'}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

/* ── API Keys Tab ───────────────────────────────────────────────────────── */
interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  permissions: string[];
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

function ApiKeysTab() {
  const qc = useQueryClient();
  const { data: keys, isLoading } = useQuery<ApiKey[]>({
    queryKey: ['api-keys'],
    queryFn: async () => {
      const { data } = await api.get('/auth/api-keys');
      return data;
    },
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState('');
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  const createKey = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/auth/api-keys', { name, permissions: [] });
      return data as { raw_key: string };
    },
    onSuccess: (data) => {
      setCreatedKey(data.raw_key);
      setName('');
      qc.invalidateQueries({ queryKey: ['api-keys'] });
    },
  });

  const revokeKey = useMutation({
    mutationFn: (keyId: string) => api.delete(`/auth/api-keys/${keyId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Key className="w-5 h-5" />
            API Keys
          </CardTitle>
          <Dialog open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) setCreatedKey(null); }}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="w-4 h-4 mr-1" /> New Key
              </Button>
            </DialogTrigger>
            <DialogContent aria-describedby={undefined}>
              <DialogHeader>
                <DialogTitle>Create API Key</DialogTitle>
              </DialogHeader>
              {createdKey ? (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">
                    Copy this key now. You won't be able to see it again.
                  </p>
                  <code className="block p-3 rounded bg-muted text-sm break-all select-all">{createdKey}</code>
                  <Button className="w-full" onClick={() => { setDialogOpen(false); setCreatedKey(null); }}>
                    Done
                  </Button>
                </div>
              ) : (
                <div className="space-y-4 pt-2">
                  <div className="space-y-1">
                    <Label>Key Name</Label>
                    <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="n8n-integration" />
                  </div>
                  <Button onClick={() => createKey.mutate()} disabled={createKey.isPending || !name} className="w-full">
                    {createKey.isPending ? 'Creating…' : 'Create'}
                  </Button>
                </div>
              )}
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : !keys || keys.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">No API keys yet</p>
        ) : (
          <div className="space-y-2">
            {keys.map((key) => (
              <div key={key.id} className="flex items-center justify-between p-3 border rounded">
                <div>
                  <p className="font-medium text-sm">{key.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {key.key_prefix}••• · Created {new Date(key.created_at).toLocaleDateString()}
                    {key.last_used_at && ` · Last used ${new Date(key.last_used_at).toLocaleDateString()}`}
                  </p>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="text-red-400 hover:text-red-300"
                  onClick={() => revokeKey.mutate(key.id)}
                  disabled={revokeKey.isPending}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ── Profile Tab ────────────────────────────────────────────────────────── */
function ProfileTab() {
  const { user } = useAuthStore();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground">Email</p>
            <p className="font-medium">{user?.email ?? '—'}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Role</p>
            <p className="font-medium">{user?.role ?? '—'}</p>
          </div>
          <div>
            <p className="text-muted-foreground">MFA</p>
            <p className="font-medium">{user?.mfa_enabled ? 'Enabled' : 'Disabled'}</p>
          </div>
          <div>
            <p className="text-muted-foreground">User ID</p>
            <p className="font-mono text-xs">{user?.id ?? '—'}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Settings Page ──────────────────────────────────────────────────────── */
export default function SettingsPage() {
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>
      <Tabs defaultValue="profile">
        <TabsList>
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="mfa">MFA</TabsTrigger>
          <TabsTrigger value="api-keys">API Keys</TabsTrigger>
        </TabsList>
        <TabsContent value="profile"><ProfileTab /></TabsContent>
        <TabsContent value="mfa"><MfaTab /></TabsContent>
        <TabsContent value="api-keys"><ApiKeysTab /></TabsContent>
      </Tabs>
    </div>
  );
}
