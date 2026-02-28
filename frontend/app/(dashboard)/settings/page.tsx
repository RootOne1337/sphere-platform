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
import {
  Settings,
  Shield,
  Key,
  User,
  Plus,
  Trash2,
  Copy,
  CheckCircle,
  XCircle,
  Fingerprint,
  Users,
} from 'lucide-react';
import { TeamTab } from './TeamTab';

/* ── Профиль оператора ──────────────────────────────────────────────────── */
function ProfileTab() {
  const { user } = useAuthStore();

  const fields = [
    { label: 'EMAIL', value: user?.email ?? '—' },
    { label: 'ROLE', value: user?.role?.toUpperCase() ?? '—' },
    { label: 'MFA', value: user?.mfa_enabled ? 'ENABLED' : 'DISABLED', status: user?.mfa_enabled },
    { label: 'USER_ID', value: user?.id ?? '—', mono: true },
  ];

  return (
    <Card className="border-border bg-muted rounded-sm">
      <CardHeader className="pb-3 border-b border-border">
        <CardTitle className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
          <User className="w-4 h-4 text-primary" />
          Идентификация оператора
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {fields.map((f) => (
            <div key={f.label} className="p-3 rounded-sm bg-card border border-border">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono font-bold mb-1">{f.label}</p>
              <p className={`text-sm font-medium ${f.mono ? 'font-mono text-xs break-all' : ''}`}>
                {f.status !== undefined ? (
                  <span className="flex items-center gap-2">
                    {f.status ? (
                      <CheckCircle className="w-3.5 h-3.5 text-success" />
                    ) : (
                      <XCircle className="w-3.5 h-3.5 text-muted-foreground" />
                    )}
                    {f.value}
                  </span>
                ) : (
                  f.value
                )}
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Двухфакторная аутентификация ──────────────────────────────────────── */
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
    onError: () => setError('Неверный код. Повторите попытку.'),
  });

  const disableMfa = useMutation({
    mutationFn: () => api.delete('/auth/mfa'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  });

  return (
    <Card className="border-border bg-muted rounded-sm">
      <CardHeader className="pb-3 border-b border-border">
        <CardTitle className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
          <Shield className="w-4 h-4 text-primary" />
          Двухфакторная аутентификация (TOTP)
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-4 space-y-4">
        <div className="flex items-center gap-3 p-3 rounded-sm bg-card border border-border">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono font-bold">STATUS</span>
          <Badge
            variant={user?.mfa_enabled ? 'default' : 'outline'}
            className={user?.mfa_enabled
              ? 'bg-success/20 text-success border-success/30 font-mono text-[10px]'
              : 'font-mono text-[10px]'
            }
          >
            {user?.mfa_enabled ? 'ACTIVE' : 'INACTIVE'}
          </Badge>
        </div>

        {user?.mfa_enabled ? (
          <Button
            variant="destructive"
            size="sm"
            className="font-mono text-xs uppercase tracking-wider"
            onClick={() => disableMfa.mutate()}
            disabled={disableMfa.isPending}
          >
            {disableMfa.isPending ? 'Отключение…' : 'Отключить MFA'}
          </Button>
        ) : setupData ? (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground">
              Отсканируйте QR-код приложением-аутентификатором (Google Authenticator, Authy и т.д.)
            </p>
            <div className="flex justify-center p-4 rounded-sm bg-white">
              <img
                src={`data:image/png;base64,${setupData.qr_code}`}
                alt="MFA QR Code"
                className="w-48 h-48"
              />
            </div>
            <div className="p-3 rounded-sm bg-card border border-border">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono font-bold mb-1">
                MANUAL_KEY
              </p>
              <code className="text-xs text-foreground font-mono break-all select-all">
                {setupData.secret}
              </code>
            </div>
            <div className="space-y-2">
              <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
                Код из приложения
              </Label>
              <div className="flex gap-2">
                <Input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  maxLength={8}
                  placeholder="000000"
                  inputMode="numeric"
                  className="font-mono tracking-[0.5em] text-center text-lg bg-card border-border"
                />
                <Button
                  size="sm"
                  className="font-mono text-xs uppercase"
                  onClick={() => verifyMfa.mutate()}
                  disabled={verifyMfa.isPending || code.length < 6}
                >
                  Verify
                </Button>
              </div>
              {error && <p className="text-xs text-destructive font-mono">{error}</p>}
            </div>
          </div>
        ) : (
          <Button
            size="sm"
            className="font-mono text-xs uppercase tracking-wider"
            onClick={() => setupMfa.mutate()}
            disabled={setupMfa.isPending}
          >
            <Fingerprint className="w-4 h-4 mr-2" />
            {setupMfa.isPending ? 'Генерация…' : 'Настроить MFA'}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

/* ── API-ключи доступа ──────────────────────────────────────────────────── */
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
  const [copied, setCopied] = useState(false);

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

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card className="border-border bg-muted rounded-sm">
      <CardHeader className="pb-3 border-b border-border">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
            <Key className="w-4 h-4 text-primary" />
            API-ключи доступа
          </CardTitle>
          <Dialog open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) { setCreatedKey(null); setCopied(false); } }}>
            <DialogTrigger asChild>
              <Button size="sm" className="font-mono text-xs uppercase tracking-wider h-8">
                <Plus className="w-3.5 h-3.5 mr-1.5" />
                Новый ключ
              </Button>
            </DialogTrigger>
            <DialogContent aria-describedby={undefined}>
              <DialogHeader>
                <DialogTitle className="font-mono text-sm uppercase tracking-widest">
                  Создание API-ключа
                </DialogTitle>
              </DialogHeader>
              {createdKey ? (
                <div className="space-y-3">
                  <p className="text-xs text-muted-foreground">
                    Скопируйте ключ сейчас. Повторный просмотр невозможен.
                  </p>
                  <div className="relative">
                    <code className="block p-3 rounded-sm bg-muted border border-border text-xs font-mono break-all select-all pr-10">
                      {createdKey}
                    </code>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="absolute right-1 top-1 h-7 w-7"
                      onClick={() => handleCopy(createdKey)}
                    >
                      {copied ? <CheckCircle className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
                    </Button>
                  </div>
                  <Button
                    className="w-full font-mono text-xs uppercase"
                    onClick={() => { setDialogOpen(false); setCreatedKey(null); }}
                  >
                    Готово
                  </Button>
                </div>
              ) : (
                <div className="space-y-4 pt-2">
                  <div className="space-y-1">
                    <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
                      Название ключа
                    </Label>
                    <Input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="n8n-integration"
                      className="font-mono bg-card border-border"
                    />
                  </div>
                  <Button
                    onClick={() => createKey.mutate()}
                    disabled={createKey.isPending || !name}
                    className="w-full font-mono text-xs uppercase tracking-wider"
                  >
                    {createKey.isPending ? 'Создание…' : 'Создать ключ'}
                  </Button>
                </div>
              )}
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent className="pt-4">
        {isLoading ? (
          <p className="text-xs text-muted-foreground font-mono py-4 text-center animate-pulse">Загрузка ключей…</p>
        ) : !keys || keys.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Key className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-[10px] font-mono uppercase tracking-widest font-bold">Нет API-ключей</p>
          </div>
        ) : (
          <div className="space-y-1.5">
            {keys.map((key) => (
              <div
                key={key.id}
                className="flex items-center justify-between p-3 rounded-sm bg-card border border-border hover:border-primary/30 transition-colors group"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium truncate">{key.name}</p>
                    <Badge
                      variant="outline"
                      className={`text-[9px] font-mono ${key.is_active ? 'text-success border-success/30' : 'text-destructive border-destructive/30'}`}
                    >
                      {key.is_active ? 'ACTIVE' : 'REVOKED'}
                    </Badge>
                  </div>
                  <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                    {key.key_prefix}••• · {new Date(key.created_at).toLocaleDateString()}
                    {key.last_used_at && ` · Исп. ${new Date(key.last_used_at).toLocaleDateString()}`}
                  </p>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => revokeKey.mutate(key.id)}
                  disabled={revokeKey.isPending}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ── Settings Page — NOC Enterprise ─────────────────────────────────────── */
export default function SettingsPage() {
  return (
    <div className="flex flex-col h-full bg-card">
      {/* Заголовок страницы */}
      <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
        <div className="flex items-center gap-2 mb-1">
          <Settings className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">
            Sys Config
          </h1>
        </div>
        <p className="text-xs text-muted-foreground font-mono max-w-2xl">
          Профиль оператора, двухфакторная аутентификация, управление командой и API-ключами доступа.
        </p>
      </div>

      {/* Контент */}
      <div className="p-6 flex-1 overflow-auto">
        <Tabs defaultValue="profile" className="space-y-4">
          <TabsList className="bg-muted border border-border rounded-sm h-9">
            <TabsTrigger value="profile" className="font-mono text-[10px] uppercase tracking-widest data-[state=active]:bg-primary/10 data-[state=active]:text-primary rounded-sm">
              <User className="w-3.5 h-3.5 mr-1.5" /> Profile
            </TabsTrigger>
            <TabsTrigger value="team" className="font-mono text-[10px] uppercase tracking-widest data-[state=active]:bg-primary/10 data-[state=active]:text-primary rounded-sm">
              <Users className="w-3.5 h-3.5 mr-1.5" /> Team
            </TabsTrigger>
            <TabsTrigger value="mfa" className="font-mono text-[10px] uppercase tracking-widest data-[state=active]:bg-primary/10 data-[state=active]:text-primary rounded-sm">
              <Shield className="w-3.5 h-3.5 mr-1.5" /> MFA
            </TabsTrigger>
            <TabsTrigger value="api-keys" className="font-mono text-[10px] uppercase tracking-widest data-[state=active]:bg-primary/10 data-[state=active]:text-primary rounded-sm">
              <Key className="w-3.5 h-3.5 mr-1.5" /> API Keys
            </TabsTrigger>
          </TabsList>

          <TabsContent value="profile"><ProfileTab /></TabsContent>
          <TabsContent value="team"><TeamTab /></TabsContent>
          <TabsContent value="mfa"><MfaTab /></TabsContent>
          <TabsContent value="api-keys"><ApiKeysTab /></TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
