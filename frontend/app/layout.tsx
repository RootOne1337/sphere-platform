import type { Metadata } from 'next';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import './globals.css';
import { Providers } from './providers';
import { ThemeProvider } from '@/src/shared/ui/ThemeProvider';
import { AppToaster } from '@/src/shared/ui/AppToaster';

export const metadata: Metadata = {
  title: 'Sphere Platform | Управление устройствами',
  description: 'Управление Android-устройствами, потоками и автоматизацией Sphere.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body className="font-sans antialiased text-sm bg-background text-foreground transition-colors duration-200">
        <ThemeProvider>
          <Providers>{children}</Providers>
          <AppToaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
