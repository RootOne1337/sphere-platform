import { redirect } from 'next/navigation';

// Корневой роут — редиректим на /dashboard
// (для незалогиненных middleware уже делает redirect на /login)
export default function RootPage() {
  redirect('/dashboard');
}
