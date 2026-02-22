# SPLIT-1 — Setup + Auth (Next.js 15 + JWT)

**ТЗ-родитель:** TZ-10-Web-Frontend  
**Ветка:** `stage/10-frontend`  
**Задача:** `SPHERE-051`  
**Исполнитель:** Frontend  
**Оценка:** 1 день  
**Блокирует:** TZ-10 SPLIT-2, SPLIT-3, SPLIT-4, SPLIT-5

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-10` — НЕ в `sphere-platform`.
> Ветка `stage/10-frontend` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.
>
> ⚠️ **Этап стартует ТОЛЬКО ПОСЛЕ merge всех backend-этапов (TZ-01..TZ-09, TZ-11) в develop!**
> Проверь у DevOps перед началом работы.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-10
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/10-frontend
pwd                          # ОБЯЗАНА содержать: sphere-stage-10
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-10 stage/10-frontend
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/10-frontend` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/10-frontend` → `develop` | ✅ ТОЛЬКО ПОСЛЕ merge всех backend PR |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `frontend/` (всё!) | `backend/` 🔴 (только читать OpenAPI доку) |
| `frontend/app/` | `backend/main.py` 🔴 |
| `frontend/components/` | `backend/core/` 🔴 |
| `frontend/lib/` | `android/` 🔴 |
| `frontend/package.json` | `docker-compose*.yml` 🔴 |

---

## Цель Сплита

Инициализировать Next.js 15 (App Router, shadcn/ui, настроить axios interceptors для JWT + refresh, реализовать login/logout страницы.

---

## Шаг 1 — Зависимости

```bash
npx create-next-app@15 frontend --typescript --tailwind --app
cd frontend
npx shadcn@latest init
npm install axios @tanstack/react-query zustand jwt-decode
```

```
frontend/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── layout.tsx
│   ├── (dashboard)/
│   │   ├── layout.tsx
│   │   ├── page.tsx           # redirect to /devices
│   │   ├── devices/page.tsx
│   │   ├── stream/[id]/page.tsx
│   │   ├── vpn/page.tsx
│   │   └── scripts/page.tsx
│   └── layout.tsx
├── lib/
│   ├── api.ts                 # axios instance
│   ├── auth.ts                # JWT helpers
│   └── store.ts               # Zustand store
└── components/
    ├── ui/                    # shadcn components
    └── sphere/                # custom components
```

---

## Шаг 2 — Zustand Auth Store

```typescript
// lib/store.ts
import { create } from 'zustand';

interface AuthState {
    accessToken: string | null;
    user: { id: string; email: string; role: string; org_id: string } | null;
    
    setAccessToken: (token: string) => void;
    setUser: (user: AuthState['user']) => void;
    logout: () => void;
}

// Access token — ТОЛЬКО в памяти (Zustand без persist)
// Refresh token — ТОЛЬКО в HTTPOnly cookie (управляется сервером)
// При перезагрузке страницы → вызов /auth/refresh автоматически обновляет access token
export const useAuthStore = create<AuthState>()((set) => ({
    accessToken: null,
    user: null,
    
    setAccessToken: (token) => set({ accessToken: token }),
    setUser: (user) => set({ user }),
    logout: () => set({ accessToken: null, user: null }),
}));

// ─── FIX 10.4: SILENT REFRESH ПРИ F5 ──────────────────────────────
// БЫЛО — accessToken только в Zustand (память), без persist
//   → F5 → Zustand сбрасывается → accessToken = null
//   → Redirect на /login ДАЖЕ ЕСЛИ refreshToken в httpOnly cookie жив!
//
// СТАЛО — useInitAuth() при монтировании Root Layout:
//   1) POST /auth/refresh (httpOnly cookie уйдёт автоматически)
//   2) 200 → сохраняем новый accessToken → пользователь залогинен
//   3) 401 → cookie протухла → redirect на /login (корректно)
// ────────────────────────────────────────────────────────────────────
export const useInitAuth = () => {
    const setAccessToken = useAuthStore((s) => s.setAccessToken);
    const setUser = useAuthStore((s) => s.setUser);
    const [ready, setReady] = useState(false);
    
    useEffect(() => {
        api.post('/auth/refresh')
            .then(res => {
                setAccessToken(res.data.access_token);
                if (res.data.user) setUser(res.data.user);
            })
            .catch(() => {
                // refreshToken протух или отсутствует — пользователь не залогинен
            })
            .finally(() => setReady(true));
    }, []);
    
    return ready;
};
```

---

## Шаг 3 — Axios Instance с JWT Interceptors

```typescript
// lib/api.ts
import axios, { AxiosError } from 'axios';
import { useAuthStore } from './store';

export const api = axios.create({
    baseURL: process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1',
    timeout: 30_000,
});

// Request: добавить Authorization
api.interceptors.request.use((config) => {
    const token = useAuthStore.getState().accessToken;
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Response: refresh при 401
let isRefreshing = false;
let failedQueue: Array<{ resolve: (v: string) => void; reject: (e: unknown) => void }> = [];

api.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
        const original = error.config as typeof error.config & { _retry?: boolean };
        
        if (error.response?.status === 401 && !original._retry) {
            if (isRefreshing) {
                // Ставим в очередь
                return new Promise((resolve, reject) => {
                    failedQueue.push({
                        resolve: (token) => {
                            original.headers!.Authorization = `Bearer ${token}`;
                            resolve(api(original));
                        },
                        reject,
                    });
                });
            }
            
            original._retry = true;
            isRefreshing = true;
            
            try {
                // Refresh token отправляется автоматически как HTTPOnly cookie
                // withCredentials: true — обязательно для cross-origin cookies
                const { data } = await axios.post(
                    `${api.defaults.baseURL}/auth/refresh`,
                    {},
                    { withCredentials: true },
                );
                
                const newAccess = data.access_token;
                useAuthStore.getState().setAccessToken(newAccess);
                
                // Разрешить очередь
                failedQueue.forEach(({ resolve }) => resolve(newAccess));
                failedQueue = [];
                
                original.headers!.Authorization = `Bearer ${newAccess}`;
                return api(original);
                
            } catch (refreshError) {
                failedQueue.forEach(({ reject }) => reject(refreshError));
                failedQueue = [];
                useAuthStore.getState().logout();
                window.location.href = '/login';
                return Promise.reject(refreshError);
            } finally {
                isRefreshing = false;
            }
        }
        
        return Promise.reject(error);
    }
);
```

---

## Шаг 4 — Login Page

```tsx
// app/(auth)/login/page.tsx
'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';

export default function LoginPage() {
    const router = useRouter();
    const { setAccessToken, setUser } = useAuthStore();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    
    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError('');
        
        try {
            // withCredentials: true — сервер установит HTTPOnly cookie с refresh token
            const { data } = await api.post('/auth/login', { email, password }, { withCredentials: true });
            setAccessToken(data.access_token);
            setUser(data.user);
            router.push('/devices');
        } catch (err: unknown) {
            const msg = (err as any)?.response?.data?.detail ?? 'Login failed';
            setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
        } finally {
            setLoading(false);
        }
    };
    
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
                                onChange={e => setEmail(e.target.value)}
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
                                onChange={e => setPassword(e.target.value)}
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
```

---

## Критерии готовности

- [ ] Access token хранится только в памяти (Zustand, без persist/localStorage)
- [ ] Refresh token НЕ хранится на клиенте — только HTTPOnly cookie (управляется сервером)
- [ ] `withCredentials: true` на login и refresh запросах для передачи cookie
- [ ] Очередь запросов: параллельные 401 ждут refresh, не делают несколько refresh
- [ ] Refresh fails → logout + redirect /login
- [ ] Login page: `autocomplete` атрибуты для password managers
- [ ] Dashboard layout: redirect `/login` если нет accessToken (middleware.ts)
