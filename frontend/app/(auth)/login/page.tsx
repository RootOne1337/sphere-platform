'use client';
import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ArrowRight, Eye, EyeOff, Fingerprint, GitBranch, Loader2, MonitorSmartphone, Radio, ShieldCheck } from 'lucide-react';
import { THEMES } from '@/src/shared/theme';
import { getApiErrorMessage } from '@/lib/apiError';
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
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // MFA flow state
  const [mfaRequired, setMfaRequired] = useState(false);
  const [stateToken, setStateToken] = useState('');
  const [mfaCode, setMfaCode] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
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
      setError(getApiErrorMessage(err, 'Не удалось войти. Проверьте данные и подключение.'));
    } finally {
      setLoading(false);
    }
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
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
      setError(getApiErrorMessage(err, 'Не удалось подтвердить вход. Проверьте код и повторите.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="sphere-auth-screen dark relative isolate flex min-h-dvh flex-col bg-[#0a0d12] text-slate-100"
      style={{ ...THEMES['neo-dark'], colorScheme: 'dark' } as React.CSSProperties}>
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-48 -top-64 h-[760px] w-[760px] rounded-full bg-emerald-400/[0.05] blur-[100px]" />
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff03_1px,transparent_1px),linear-gradient(to_bottom,#ffffff03_1px,transparent_1px)] bg-[size:64px_64px] [mask-image:linear-gradient(to_bottom,black,transparent_85%)]" />
      </div>
      <header className="mx-auto flex w-full max-w-[1360px] items-center justify-between gap-4 px-5 py-6 sm:px-10 sm:py-8">
        <div className="flex items-center gap-3" aria-label="Sphere Platform">
          <SphereMark />
          <span className="text-xl font-semibold tracking-tight">Sphere<span className="ml-2 hidden text-sm font-normal text-slate-400 sm:inline">Platform</span></span>
        </div>
        <span className="hidden text-xs tracking-wide text-slate-400 sm:block">Устройства. Сценарии. Контроль.</span>
      </header>

      <div className="mx-auto grid w-full max-w-[1360px] flex-1 items-center gap-10 px-5 py-8 sm:px-10 sm:py-12 lg:grid-cols-[minmax(0,1fr)_minmax(360px,440px)] lg:gap-16 xl:gap-24">
        <section className="hidden min-w-0 lg:block" aria-label="Возможности платформы">
          <p className="mb-6 flex items-center gap-2.5 text-xs font-medium uppercase tracking-[0.18em] text-emerald-400"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />Ваш центр управления</p>
          <h2 className="max-w-[650px] text-[clamp(2.8rem,4.4vw,4.4rem)] font-semibold leading-[1.08] tracking-[-0.045em]">Все устройства.<br /><span className="text-slate-400">Одно рабочее</span><br /><span className="text-slate-400">пространство.</span></h2>
          <p className="mt-6 max-w-[480px] text-base leading-7 text-slate-400">От первого подключения до сложного сценария — управляйте Android-парком в единой среде.</p>
          <div className="mt-10 grid max-w-[560px] grid-cols-3 gap-5 border-t border-white/[0.08] pt-7">
            <Feature icon={MonitorSmartphone} title="Парк устройств" text="Состояние и доступ" />
            <Feature icon={Radio} title="Прямой поток" text="Видео и управление" />
            <Feature icon={GitBranch} title="Автоматизация" text="Визуальные сценарии" />
          </div>
          <div aria-hidden="true" className="mt-12 flex max-w-[530px] items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.015] px-4 py-3 text-xs text-slate-400">
            <span className="rounded-md border border-white/[0.07] bg-white/[0.025] px-2.5 py-1.5 font-mono text-slate-400">Browser</span><span className="h-px flex-1 bg-gradient-to-r from-slate-700 to-emerald-500/40" /><span className="flex h-7 w-7 items-center justify-center rounded-full border border-emerald-500/20 text-emerald-400"><Radio className="h-3.5 w-3.5" /></span><span className="h-px flex-1 bg-gradient-to-r from-emerald-500/40 to-slate-700" /><span className="rounded-md border border-white/[0.07] bg-white/[0.025] px-2.5 py-1.5 font-mono text-slate-400">Android</span>
          </div>
        </section>

        <section className="mx-auto w-full max-w-[440px] rounded-[1.5rem] border border-white/[0.09] bg-[#10151d]/95 p-6 shadow-[0_24px_100px_-28px_#000000] sm:p-9" aria-labelledby="auth-title">
          <div className="mb-7 flex h-11 w-11 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-500/[0.07] text-emerald-400"><Fingerprint className="h-6 w-6" aria-hidden="true" /></div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-400">{mfaRequired ? 'Подтверждение личности' : 'Рабочее пространство'}</p>
          <h1 id="auth-title" className="text-2xl font-semibold tracking-tight">{mfaRequired ? 'Подтвердите вход' : 'Вход в Sphere'}</h1>
          <p className="mb-8 mt-2 text-sm leading-6 text-slate-400">{mfaRequired ? 'Введите одноразовый код из приложения-аутентификатора.' : 'Войдите в аккаунт, чтобы продолжить работу.'}</p>
          <form onSubmit={mfaRequired ? handleMfaSubmit : handleSubmit} className="space-y-5" aria-busy={loading}>
            {mfaRequired ? <div className="space-y-2">
              <Label htmlFor="mfa-code" className="text-slate-300">Код подтверждения</Label>
              <Input id="mfa-code" type="text" inputMode="numeric" autoComplete="one-time-code" autoFocus maxLength={8}
                value={mfaCode} onChange={event => setMfaCode(event.target.value)} required aria-describedby={error ? 'auth-error' : undefined}
                className="h-12 rounded-lg bg-[#0c1118] text-center font-mono text-lg tracking-[0.35em]" />
            </div> : <>
              <div className="space-y-2">
                <Label htmlFor="email" className="text-slate-300">Электронная почта</Label>
                <Input id="email" type="email" autoComplete="username" autoCapitalize="none" spellCheck={false}
                  placeholder="you@company.com" value={email} onChange={event => setEmail(event.target.value)} required
                  aria-describedby={error ? 'auth-error' : undefined} className="h-12 rounded-lg bg-[#0c1118] text-base sm:text-sm" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password" className="text-slate-300">Пароль</Label>
                <div className="relative">
                  <Input id="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password"
                    placeholder="Введите пароль" value={password} onChange={event => setPassword(event.target.value)} required
                    onKeyDown={event => setCapsLock(event.getModifierState('CapsLock'))} onKeyUp={event => setCapsLock(event.getModifierState('CapsLock'))} onBlur={() => setCapsLock(false)}
                    aria-describedby={[error ? 'auth-error' : '', capsLock ? 'caps-warning' : ''].filter(Boolean).join(' ') || undefined}
                    className="h-12 rounded-lg bg-[#0c1118] pr-12 text-base sm:text-sm" />
                  <button type="button" aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'} aria-pressed={showPassword}
                    onClick={() => setShowPassword(value => !value)} className="absolute inset-y-0 right-0 flex w-12 items-center justify-center rounded-r-lg text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    {showPassword ? <EyeOff className="h-[18px] w-[18px]" aria-hidden="true" /> : <Eye className="h-[18px] w-[18px]" aria-hidden="true" />}
                  </button>
                </div>
                {capsLock && <p id="caps-warning" role="status" className="text-xs text-amber-300">Включён Caps Lock</p>}
              </div>
            </>}
            {!mfaRequired && logoutWarning && <p role="status" className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">{logoutWarning}</p>}
            {error && <p id="auth-error" role="alert" className="rounded-lg border border-red-400/20 bg-red-400/5 px-3 py-2 text-sm text-red-300">{error}</p>}
            <Button type="submit" className="h-12 w-full gap-2 rounded-lg font-semibold shadow-[0_4px_24px_-6px_hsl(160_65%_48%/0.35)]" disabled={loading}>
              {loading ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />{mfaRequired ? 'Проверяем код…' : 'Входим…'}</> : <>{mfaRequired ? 'Подтвердить вход' : 'Войти в Sphere'}<ArrowRight className="h-4 w-4" aria-hidden="true" /></>}
            </Button>
            {mfaRequired && <Button type="button" variant="ghost" className="h-11 w-full text-slate-400"
              onClick={() => { beginLogin(); attemptVersion.current = null; setLoading(false); setMfaRequired(false); setStateToken(''); setMfaCode(''); setError(''); }}>
              Вернуться ко входу
            </Button>}
          </form>
          <div className="mt-7 flex items-start gap-2.5 border-t border-white/[0.07] pt-5 text-xs leading-5 text-slate-400"><ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /><p>Доступ к устройствам и действиям определяется правами вашего аккаунта.</p></div>
        </section>
      </div>
      <footer className="mx-auto flex w-full max-w-[1360px] flex-wrap items-center justify-between gap-2 px-5 py-6 text-xs text-slate-400 sm:px-10">
        <span>Sphere Platform</span><span>Управление Android-инфраструктурой</span>
      </footer>
    </main>
  );
}

function SphereMark() {
  return <svg viewBox="0 0 40 40" fill="none" aria-hidden="true" className="h-9 w-9 shrink-0 text-emerald-400">
    <rect x="0.5" y="0.5" width="39" height="39" rx="12" fill="currentColor" fillOpacity="0.08" stroke="currentColor" strokeOpacity="0.25" />
    <circle cx="20" cy="20" r="9" stroke="currentColor" strokeWidth="1.5" />
    <ellipse cx="20" cy="20" rx="4" ry="9" stroke="currentColor" strokeWidth="1.5" transform="rotate(35 20 20)" />
    <path d="M11 20h18" stroke="currentColor" strokeWidth="1.5" /><circle cx="28" cy="12" r="2.5" fill="currentColor" />
  </svg>;
}
function Feature({ icon: Icon, title, text }: { icon: typeof Radio; title: string; text: string }) {
  return <div><Icon className="mb-3 h-[18px] w-[18px] text-emerald-400/80" aria-hidden="true" /><p className="text-sm font-medium text-slate-200">{title}</p><p className="mt-1 text-xs leading-5 text-slate-400">{text}</p></div>;
}
