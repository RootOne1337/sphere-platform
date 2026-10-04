'use client';
import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Activity, ArrowRight, Boxes, ShieldCheck, Sparkles } from 'lucide-react';
import axios from 'axios';
import { beginLogin, useAuthStore } from '@/lib/store';

// Используем сырой axios (без interceptors) для login — иначе interceptor перехватывает 401
const authApi = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? '/api/v1',
  timeout: 30_000,
  withCredentials: true,
});

export default function LoginPage() {
  const router = useRouter();
  const logoutWarning = useAuthStore(s => s.logoutWarning);
  const attemptVersion = useRef<number | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // MFA flow state
  const [mfaRequired, setMfaRequired] = useState(false);
  const [stateToken, setStateToken] = useState('');
  const [mfaCode, setMfaCode] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    const version = beginLogin();
    attemptVersion.current = version;

    try {
      const { data } = await authApi.post(
        '/auth/login',
        { email, password },
      );

      if (useAuthStore.getState().sessionVersion !== version) return;

      // Check if MFA is required
      if (data.mfa_required) {
        setMfaRequired(true);
        setStateToken(data.state_token);
        setLoading(false);
        return;
      }

      if (useAuthStore.getState().completeLogin(data, version)) router.replace('/dashboard');
    } catch (err: unknown) {
      if (useAuthStore.getState().sessionVersion !== version) return;
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Login failed';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setLoading(false);
    }
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    const version = attemptVersion.current;
    if (version === null || useAuthStore.getState().sessionVersion !== version) { setLoading(false); return; }

    try {
      const { data } = await authApi.post(
        '/auth/login/mfa',
        { state_token: stateToken, code: mfaCode },
      );
      if (useAuthStore.getState().completeLogin(data, version)) router.replace('/dashboard');
    } catch (err: unknown) {
      if (useAuthStore.getState().sessionVersion !== version) return;
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Invalid MFA code';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setLoading(false);
    }
  };

  if (mfaRequired) {
    return (
      <main className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-background px-4 py-10">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,hsl(var(--primary)/0.12),transparent_48%),radial-gradient(ellipse_at_bottom_right,hsl(210_30%_85%/0.45),transparent_52%)]" />
        <Card className="relative w-full max-w-md rounded-2xl border-border/80 shadow-xl shadow-slate-900/5">
          <CardHeader className="space-y-4 p-7 pb-2 sm:p-8 sm:pb-2">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-lg font-bold text-primary-foreground shadow-sm">S</div>
            <div className="space-y-1.5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Защита аккаунта</p>
              <CardTitle className="font-sans text-2xl font-semibold tracking-tight">Подтвердите вход</CardTitle>
              <p className="text-sm leading-6 text-muted-foreground">Введите одноразовый код из приложения-аутентификатора.</p>
            </div>
          </CardHeader>
          <CardContent className="p-7 pt-5 sm:p-8 sm:pt-5">
            <form onSubmit={handleMfaSubmit} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="mfa-code">Код подтверждения</Label>
                <Input id="mfa-code" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} required className="h-11 font-mono tracking-[0.3em]" />
              </div>
              {error && <p role="alert" className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
              <Button type="submit" className="h-11 w-full" disabled={loading}>
                {loading ? 'Проверяем код…' : 'Подтвердить вход'}
                {!loading && <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" />}
              </Button>
              <Button type="button" variant="ghost" className="w-full text-muted-foreground" onClick={() => { beginLogin(); attemptVersion.current = null; setLoading(false); setMfaRequired(false); setMfaCode(''); setError(''); }}>
                Вернуться ко входу
              </Button>
            </form>
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <main className="relative flex min-h-dvh overflow-hidden bg-background">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,hsl(var(--primary)/0.10),transparent_42%),radial-gradient(ellipse_at_bottom_right,hsl(210_30%_85%/0.38),transparent_50%)]" />
      <div className="relative mx-auto grid min-h-dvh w-full max-w-7xl items-center gap-10 px-4 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(380px,460px)] lg:gap-16 lg:px-12">
        <section className="hidden max-w-2xl space-y-9 lg:block" aria-label="Sphere Platform">
          <div className="flex items-center gap-3">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-lg font-bold text-primary-foreground shadow-sm">S</span>
            <div><p className="text-lg font-semibold tracking-tight">Sphere</p><p className="text-sm text-muted-foreground">Платформа управления Android-устройствами</p></div>
          </div>
          <div className="space-y-4">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary"><Sparkles className="h-4 w-4" aria-hidden="true" />Операционная платформа</p>
            <h1 className="max-w-xl text-4xl font-semibold leading-[1.12] tracking-tight text-foreground xl:text-5xl">Управляйте парком устройств из одного рабочего пространства.</h1>
            <p className="max-w-xl text-base leading-7 text-muted-foreground">Потоки, состояние подключений и автоматизация собраны рядом — с понятными статусами и безопасными действиями.</p>
          </div>
          <div className="grid max-w-xl grid-cols-2 gap-3">
            <div className="rounded-xl border border-border/80 bg-card/80 p-4 shadow-sm"><Boxes className="mb-3 h-5 w-5 text-primary" aria-hidden="true" /><p className="text-sm font-medium">Единый реестр</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Устройства, группы и доступность</p></div>
            <div className="rounded-xl border border-border/80 bg-card/80 p-4 shadow-sm"><Activity className="mb-3 h-5 w-5 text-primary" aria-hidden="true" /><p className="text-sm font-medium">Операционная видимость</p><p className="mt-1 text-xs leading-5 text-muted-foreground">События, потоки и состояние агентов</p></div>
          </div>
        </section>

        <Card className="relative mx-auto w-full max-w-md rounded-2xl border-border/80 shadow-xl shadow-slate-900/5">
          <CardHeader className="space-y-4 p-7 pb-2 sm:p-8 sm:pb-2 lg:hidden">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-base font-bold text-primary-foreground shadow-sm">S</div>
            <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Sphere Platform</p><CardTitle className="mt-2 font-sans text-2xl font-semibold tracking-tight">Вход в систему</CardTitle></div>
          </CardHeader>
          <CardHeader className="hidden space-y-2 p-8 pb-2 lg:block">
            <CardTitle className="font-sans text-2xl font-semibold tracking-tight">С возвращением</CardTitle>
            <p className="text-sm text-muted-foreground">Войдите, чтобы открыть рабочее пространство.</p>
          </CardHeader>
          <CardContent className="p-7 pt-5 sm:p-8 sm:pt-5">
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="email">Электронная почта</Label>
                <Input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required className="h-11" />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between"><Label htmlFor="password">Пароль</Label><ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" /></div>
                <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required className="h-11" />
              </div>
              {logoutWarning && <p role="status" className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">{logoutWarning}</p>}
              {error && <p role="alert" className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
              <Button type="submit" className="h-11 w-full" disabled={loading}>
                {loading ? 'Входим…' : 'Войти в Sphere'}
                {!loading && <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" />}
              </Button>
            </form>
            <div className="mt-6 flex items-center justify-center gap-2 border-t border-border pt-5 text-xs text-muted-foreground"><ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />Защищённое подключение к рабочему пространству</div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
