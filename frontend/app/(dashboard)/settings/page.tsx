'use client';

import { useState } from 'react';
import {
  UserCog, Shield, Key, Mail, User, Clock, Copy,
  CheckCircle2, Trash2, Plus, QrCode, AlertTriangle,
  ChevronRight, Eye, EyeOff, RefreshCw, Lock, Loader2
} from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { useAuthStore } from '@/lib/store';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { toast } from 'sonner';

const TABS = [
  { id: 'profile', label: 'Profile', icon: User },
  { id: 'mfa', label: 'MFA Setup', icon: Shield },
  { id: 'apikeys', label: 'API Keys', icon: Key },
] as const;

type TabId = typeof TABS[number]['id'];

/** Формат ответа GET /auth/api-keys */
interface APIKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  permissions: string[];
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

/** Формат ответа POST /auth/api-keys */
interface APIKeyCreated {
  id: string;
  name: string;
  key_prefix: string;
  raw_key: string;
  permissions: string[];
  expires_at: string | null;
  created_at: string;
}

/** Формат ответа POST /auth/mfa/setup */
interface MFASetupData {
  qr_code: string;
  secret: string;
}

export default function SettingsPage() {
  const { user } = useAuthStore();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabId>('profile');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [showNewKeyDialog, setShowNewKeyDialog] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [mfaStep, setMfaStep] = useState<'status' | 'verify' | 'done'>('status');
  const [mfaCode, setMfaCode] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [mfaSetupData, setMfaSetupData] = useState<MFASetupData | null>(null);

  // ── API Keys: список ───────────────────────────────────────────────────────
  const { data: apiKeys = [], isLoading: keysLoading } = useQuery<APIKeyItem[]>({
    queryKey: ['api-keys'],
    queryFn: async () => {
      const { data } = await api.get('/auth/api-keys');
      return data;
    },
  });

  // ── API Keys: создание ─────────────────────────────────────────────────────
  const createKeyMutation = useMutation({
    mutationFn: async (name: string) => {
      const { data } = await api.post<APIKeyCreated>('/auth/api-keys', { name });
      return data;
    },
    onSuccess: (data) => {
      setNewKeyValue(data.raw_key);
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      toast.success(`Ключ "${data.name}" создан`);
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Ошибка создания API-ключа');
    },
  });

  // ── API Keys: удаление ─────────────────────────────────────────────────────
  const revokeKeyMutation = useMutation({
    mutationFn: async (keyId: string) => {
      await api.delete(`/auth/api-keys/${keyId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      toast.success('Ключ отозван');
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Ошибка отзыва ключа');
    },
  });

  // ── MFA: setup (шаг 1) ─────────────────────────────────────────────────────
  const mfaSetupMutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post<MFASetupData>('/auth/mfa/setup');
      return data;
    },
    onSuccess: (data) => {
      setMfaSetupData(data);
      setMfaStep('verify');
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Ошибка настройки MFA');
    },
  });

  // ── MFA: verify-setup (шаг 2) ──────────────────────────────────────────────
  const mfaVerifyMutation = useMutation({
    mutationFn: async (code: string) => {
      const { data } = await api.post('/auth/mfa/verify-setup', { code });
      return data;
    },
    onSuccess: () => {
      setMfaStep('done');
      toast.success('MFA успешно активирован');
      queryClient.invalidateQueries({ queryKey: ['auth-me'] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Неверный TOTP-код');
    },
  });

  // ── MFA: отключение ────────────────────────────────────────────────────────
  const mfaDisableMutation = useMutation({
    mutationFn: async () => {
      await api.delete('/auth/mfa');
    },
    onSuccess: () => {
      setMfaStep('status');
      setMfaCode('');
      setMfaSetupData(null);
      toast.success('MFA отключён');
      queryClient.invalidateQueries({ queryKey: ['auth-me'] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Ошибка отключения MFA');
    },
  });

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(id);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  /** Форматирование даты для отображения */
  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '—';
    return new Date(dateStr).toLocaleDateString('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric',
    });
  };

  /** Форматирование last_used_at */
  const formatLastUsed = (dateStr: string | null) => {
    if (!dateStr) return 'Никогда';
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'Только что';
    if (diffMin < 60) return `${diffMin} мин назад`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH} ч назад`;
    return formatDate(dateStr);
  };

  return (
    <div className="flex flex-col h-full bg-card overflow-y-auto custom-scrollbar">
      {/* Заголовок */}
      <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
        <div className="flex items-center gap-2 mb-1">
          <UserCog className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">System Configuration</h1>
        </div>
        <p className="text-xs text-muted-foreground font-mono">
          Управление профилем, безопасностью и API-интеграциями.
        </p>
      </div>

      <div className="flex flex-col md:flex-row h-full">
        {/* Боковая навигация */}
        <div className="flex md:flex-col gap-1 p-4 border-b md:border-b-0 md:border-r border-border bg-muted/30 md:min-w-[200px] shrink-0">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-sm text-xs font-mono font-bold tracking-wider uppercase transition-colors w-full text-left ${activeTab === id
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
              {activeTab === id && <ChevronRight className="w-3 h-3 ml-auto" />}
            </button>
          ))}
        </div>

        {/* Основной контент */}
        <div className="flex-1 p-6 overflow-y-auto">

          {/* === TAB: PROFILE === */}
          {activeTab === 'profile' && (
            <div className="space-y-6 max-w-2xl">
              <div className="border border-border rounded-sm bg-muted/30 p-5">
                <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-4">
                  Идентификация Пользователя
                </div>
                <div className="flex items-center gap-4 mb-6">
                  <div className="w-16 h-16 rounded-sm bg-primary/20 border border-primary/30 flex items-center justify-center text-2xl font-bold font-mono text-primary">
                    {user?.email?.[0]?.toUpperCase() ?? '?'}
                  </div>
                  <div>
                    <p className="text-base font-bold font-mono text-foreground">{user?.email ?? '—'}</p>
                    <Badge variant="outline" className="text-[9px] mt-1 border-primary/50 text-primary">
                      {user?.role?.toUpperCase() ?? '—'}
                    </Badge>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-3">
                  {[
                    { label: 'Email', value: user?.email ?? '—', icon: Mail },
                    { label: 'User ID', value: user?.id ?? '—', icon: User },
                    { label: 'Role', value: user?.role?.toUpperCase() ?? '—', icon: Lock },
                    { label: 'Сессия создана', value: new Date().toLocaleDateString('ru-RU'), icon: Clock },
                  ].map(({ label, value, icon: Icon }) => (
                    <div key={label} className="flex items-center justify-between py-2.5 px-3 bg-muted border border-border rounded-sm">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Icon className="w-3.5 h-3.5" />
                        <span className="text-xs font-mono">{label}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-foreground">{value}</span>
                        <button
                          onClick={() => copyToClipboard(String(value), label)}
                          className="text-muted-foreground hover:text-primary transition-colors"
                        >
                          {copiedKey === label
                            ? <CheckCircle2 className="w-3 h-3 text-success" />
                            : <Copy className="w-3 h-3" />
                          }
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="border border-border rounded-sm bg-muted/30 p-5">
                <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-4">
                  Статус Безопасности Аккаунта
                </div>
                <div className="space-y-3">
                  <div className="flex items-center justify-between p-3 bg-success/10 border border-success/30 rounded-sm">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-success" />
                      <span className="text-xs font-mono text-foreground">Email верифицирован</span>
                    </div>
                    <Badge variant="outline" className="text-[9px] border-success/50 text-success">VERIFIED</Badge>
                  </div>
                  <div className={`flex items-center justify-between p-3 rounded-sm ${user?.mfa_enabled
                    ? 'bg-success/10 border border-success/30'
                    : 'bg-warning/10 border border-warning/30'
                    }`}>
                    <div className="flex items-center gap-2">
                      {user?.mfa_enabled
                        ? <CheckCircle2 className="w-4 h-4 text-success" />
                        : <AlertTriangle className="w-4 h-4 text-warning" />
                      }
                      <span className="text-xs font-mono text-foreground">Двухфакторная аутентификация</span>
                    </div>
                    <Badge variant="outline" className={`text-[9px] ${user?.mfa_enabled
                      ? 'border-success/50 text-success'
                      : 'border-warning/50 text-warning'
                      }`}>
                      {user?.mfa_enabled ? 'ENABLED' : 'NOT CONFIGURED'}
                    </Badge>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* === TAB: MFA === */}
          {activeTab === 'mfa' && (
            <div className="space-y-6 max-w-lg">
              {mfaStep === 'status' && (
                <div className="border border-border rounded-sm bg-muted/30 p-5">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-4">
                    TOTP Аутентификатор
                  </div>
                  <div className="p-4 bg-warning/10 border border-warning/30 rounded-sm mb-5">
                    <div className="flex items-center gap-2 mb-2">
                      <AlertTriangle className="w-4 h-4 text-warning" />
                      <span className="text-xs font-bold font-mono text-warning uppercase">Не настроено</span>
                    </div>
                    <p className="text-xs text-muted-foreground font-mono">
                      Включите TOTP-аутентификацию через Google Authenticator или Authy для защиты аккаунта.
                    </p>
                  </div>
                  <Button
                    onClick={() => mfaSetupMutation.mutate()}
                    disabled={mfaSetupMutation.isPending}
                    className="w-full font-mono font-bold text-xs uppercase tracking-wider"
                  >
                    {mfaSetupMutation.isPending
                      ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Генерация...</>
                      : <><QrCode className="w-4 h-4 mr-2" /> Настроить MFA</>
                    }
                  </Button>
                </div>
              )}

              {mfaStep === 'verify' && mfaSetupData && (
                <div className="border border-border rounded-sm bg-muted/30 p-5 space-y-5">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                    Шаг 1: Сканируйте QR-код
                  </div>

                  {/* Реальный QR-код из бэкенда (base64 PNG) */}
                  <div className="flex justify-center">
                    <div className="w-48 h-48 bg-white border-4 border-border rounded-sm flex items-center justify-center overflow-hidden">
                      <img
                        src={`data:image/png;base64,${mfaSetupData.qr_code}`}
                        alt="TOTP QR Code"
                        className="w-full h-full object-contain"
                      />
                    </div>
                  </div>

                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-bold mb-2">
                      Ключ вручную
                    </p>
                    <div className="flex items-center gap-2 p-3 bg-muted border border-border rounded-sm font-mono text-sm">
                      <span className="flex-1 text-foreground tracking-widest">
                        {showSecret ? mfaSetupData.secret : '•'.repeat(mfaSetupData.secret.length)}
                      </span>
                      <button onClick={() => setShowSecret(!showSecret)} className="text-muted-foreground hover:text-foreground">
                        {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                      <button onClick={() => copyToClipboard(mfaSetupData.secret, 'secret')} className="text-muted-foreground hover:text-primary">
                        {copiedKey === 'secret' ? <CheckCircle2 className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-bold mb-2">
                      Шаг 2: Введите 6-значный код
                    </p>
                    <div className="flex gap-2">
                      <Input
                        value={mfaCode}
                        onChange={e => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                        placeholder="000000"
                        className="flex-1 font-mono text-center tracking-[0.5em] text-lg"
                        maxLength={6}
                      />
                      <Button
                        onClick={() => mfaVerifyMutation.mutate(mfaCode)}
                        disabled={mfaCode.length !== 6 || mfaVerifyMutation.isPending}
                        className="font-mono font-bold text-xs uppercase"
                      >
                        {mfaVerifyMutation.isPending
                          ? <Loader2 className="w-4 h-4 animate-spin" />
                          : 'Подтвердить'
                        }
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {mfaStep === 'done' && (
                <div className="border border-success/30 bg-success/10 rounded-sm p-6 text-center space-y-4">
                  <CheckCircle2 className="w-12 h-12 text-success mx-auto" />
                  <div>
                    <p className="font-bold font-mono text-foreground text-sm uppercase tracking-wider">MFA Активирован</p>
                    <p className="text-xs text-muted-foreground font-mono mt-1">
                      Аккаунт защищён двухфакторной аутентификацией.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => mfaDisableMutation.mutate()}
                    disabled={mfaDisableMutation.isPending}
                    className="font-mono text-xs uppercase text-destructive border-destructive/30 hover:bg-destructive/10"
                  >
                    {mfaDisableMutation.isPending
                      ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Отключение...</>
                      : 'Отключить MFA'
                    }
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* === TAB: API KEYS === */}
          {activeTab === 'apikeys' && (
            <div className="space-y-5 max-w-3xl">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                    API-ключи для интеграций
                  </p>
                  <p className="text-xs text-muted-foreground font-mono mt-0.5">
                    Используются для CI/CD, ботов и внешних систем.
                  </p>
                </div>
                <Button
                  size="sm"
                  className="font-mono font-bold text-xs uppercase tracking-wider"
                  onClick={() => { setShowNewKeyDialog(true); setNewKeyValue(null); setNewKeyName(''); }}
                >
                  <Plus className="w-3.5 h-3.5 mr-2" />
                  Новый Ключ
                </Button>
              </div>

              {/* Диалог создания */}
              {showNewKeyDialog && (
                <div className="border border-primary/30 bg-primary/5 rounded-sm p-4 space-y-3">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-primary">
                    Создание API-ключа
                  </p>
                  <div className="flex gap-2">
                    <Input
                      placeholder="Название (например: CI/CD Pipeline)"
                      value={newKeyName}
                      onChange={e => setNewKeyName(e.target.value)}
                      className="flex-1 font-mono text-xs"
                    />
                    <Button
                      size="sm"
                      onClick={() => createKeyMutation.mutate(newKeyName)}
                      disabled={!newKeyName.trim() || createKeyMutation.isPending}
                      className="font-mono text-xs uppercase"
                    >
                      {createKeyMutation.isPending
                        ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        : <><RefreshCw className="w-3.5 h-3.5 mr-1" /> Создать</>
                      }
                    </Button>
                  </div>
                  {newKeyValue && (
                    <div>
                      <p className="text-[10px] text-warning font-mono mb-2">
                        ⚠ Скопируйте ключ — он показывается один раз!
                      </p>
                      <div className="flex items-center gap-2 p-3 bg-muted border border-border rounded-sm">
                        <span className="flex-1 text-xs font-mono text-success break-all">{newKeyValue}</span>
                        <button onClick={() => copyToClipboard(newKeyValue, 'new')}>
                          {copiedKey === 'new'
                            ? <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
                            : <Copy className="w-4 h-4 text-muted-foreground hover:text-primary shrink-0" />
                          }
                        </button>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-3 w-full font-mono text-xs uppercase"
                        onClick={() => setShowNewKeyDialog(false)}
                      >
                        Готово
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {/* Загрузка */}
              {keysLoading && (
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin mr-2" />
                  <span className="text-xs font-mono">Загрузка ключей...</span>
                </div>
              )}

              {/* Список ключей */}
              <div className="space-y-3">
                {apiKeys.map(k => (
                  <div key={k.id} className="border border-border bg-muted/30 rounded-sm p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Key className="w-3.5 h-3.5 text-primary shrink-0" />
                          <span className="text-sm font-bold font-mono text-foreground">{k.name}</span>
                        </div>
                        <p className="text-xs font-mono text-muted-foreground truncate mb-2">{k.key_prefix}••••••••</p>
                        <div className="flex flex-wrap gap-1">
                          {k.permissions.map(s => (
                            <Badge key={s} variant="outline" className="text-[9px] font-mono">{s}</Badge>
                          ))}
                          {k.permissions.length === 0 && (
                            <Badge variant="outline" className="text-[9px] font-mono text-muted-foreground">full-access</Badge>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-2 shrink-0">
                        <button
                          onClick={() => revokeKeyMutation.mutate(k.id)}
                          disabled={revokeKeyMutation.isPending}
                          className="text-muted-foreground hover:text-destructive transition-colors disabled:opacity-50"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                        <div className="text-right">
                          <p className="text-[10px] text-muted-foreground font-mono">Последнее использование</p>
                          <p className={`text-[11px] font-mono font-bold ${!k.last_used_at ? 'text-muted-foreground' : 'text-success'}`}>
                            {formatLastUsed(k.last_used_at)}
                          </p>
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 pt-3 border-t border-border/50 flex items-center justify-between">
                      <span className="text-[10px] font-mono text-muted-foreground">
                        Создан: {formatDate(k.created_at)}
                      </span>
                      <Badge variant="outline" className={`text-[9px] ${k.is_active ? 'border-success/50 text-success' : 'border-destructive/50 text-destructive'}`}>
                        {k.is_active ? 'ACTIVE' : 'REVOKED'}
                      </Badge>
                    </div>
                  </div>
                ))}
                {!keysLoading && apiKeys.length === 0 && (
                  <div className="text-center py-8">
                    <Key className="w-8 h-8 text-muted-foreground/30 mx-auto mb-3" />
                    <p className="text-xs font-mono text-muted-foreground">API-ключи не созданы</p>
                  </div>
                )}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
