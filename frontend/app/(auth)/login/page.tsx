'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import axios from 'axios';
import { useAuthStore, saveRefreshToken } from '@/lib/store';

// Используем сырой axios (без interceptors) для login — иначе interceptor перехватывает 401
const authApi = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? '/api/v1',
  timeout: 30_000,
  withCredentials: true,
});

export default function LoginPage() {
  const { setAccessToken, setUser } = useAuthStore();
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

    try {
      const { data } = await authApi.post(
        '/auth/login',
        { email, password },
      );

      // Check if MFA is required
      if (data.mfa_required) {
        setMfaRequired(true);
        setStateToken(data.state_token);
        setLoading(false);
        return;
      }

      setAccessToken(data.access_token);
      setUser(data.user);
      // Сохраняем refresh_token в localStorage (fallback для tunnel/proxy)
      if (data.refresh_token) {
        saveRefreshToken(data.refresh_token);
      }
      // Полная перезагрузка — гарантирует чистый init auth через useInitAuth с localStorage
      window.location.href = '/dashboard';
    } catch (err: unknown) {
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

    try {
      const { data } = await authApi.post(
        '/auth/login/mfa',
        { state_token: stateToken, code: mfaCode },
      );
      setAccessToken(data.access_token);
      setUser(data.user);
      // Сохраняем refresh_token в localStorage (fallback для tunnel/proxy)
      if (data.refresh_token) {
        saveRefreshToken(data.refresh_token);
      }
      // Полная перезагрузка для чистого init
      window.location.href = '/dashboard';
    } catch (err: unknown) {
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
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle className="text-2xl">Two-Factor Auth</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleMfaSubmit} className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Enter the 6-digit code from your authenticator app.
              </p>
              <div>
                <Label htmlFor="mfa-code">TOTP Code</Label>
                <Input
                  id="mfa-code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={8}
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  required
                />
              </div>
              {error && <p className="text-sm text-red-500">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? 'Verifying…' : 'Verify'}
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="w-full"
                onClick={() => { setMfaRequired(false); setMfaCode(''); setError(''); }}
              >
                Back to login
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">Sphere Platform</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
