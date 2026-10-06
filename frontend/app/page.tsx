import { redirect } from 'next/navigation';

// Корневой роут — редиректим на /dashboard
// Проверка пользовательской сессии выполняется client-side guard в providers.
export default function RootPage() {
  redirect('/dashboard');
}
