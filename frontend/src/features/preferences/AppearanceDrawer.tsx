'use client';

import { LayoutGrid, MonitorPlay, Paintbrush, Palette, Type } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { useUIStore, type AccentColor, type FontScale, type UIDensity } from '@/src/shared/store/useUIStore';
import { useThemeStore, type DensityType, type ThemeType } from '@/src/shared/store/themeStore';

interface AppearanceDrawerProps {
  open: boolean;
  onClose: () => void;
}

const THEMES: { id: ThemeType; label: string; description: string; swatches: string[] }[] = [
  { id: 'light-corporate', label: 'Светлая', description: 'Чистая рабочая область', swatches: ['#f4f7f8', '#ffffff', '#16845d'] },
  { id: 'neo-dark', label: 'Тёмная', description: 'Нейтральная тёмная тема', swatches: ['#09090b', '#18181b', '#e4e4e7'] },
  { id: 'deep-space', label: 'Deep Space', description: 'Тёмно-синяя палитра', swatches: ['#080817', '#111126', '#3b82f6'] },
  { id: 'matrix-green', label: 'Matrix', description: 'Высокий контраст, зелёный', swatches: ['#001000', '#061b06', '#00d900'] },
];

const ACCENTS: { id: AccentColor; label: string; color: string }[] = [
  { id: 'emerald', label: 'Изумрудный', color: '#16845d' },
  { id: 'blue', label: 'Синий', color: '#2563eb' },
  { id: 'violet', label: 'Фиолетовый', color: '#7c3aed' },
  { id: 'rose', label: 'Розовый', color: '#e11d48' },
  { id: 'amber', label: 'Янтарный', color: '#b45309' },
];

const DENSITIES: { id: DensityType; uiId: UIDensity; label: string; description: string }[] = [
  { id: 'compact', uiId: 'compact', label: 'Компактная', description: 'Больше строк и данных на экране' },
  { id: 'cozy', uiId: 'comfortable', label: 'Обычная', description: 'Сбалансированные интервалы' },
  { id: 'spacious', uiId: 'spacious', label: 'Свободная', description: 'Увеличенные отступы и элементы' },
];

export function AppearanceDrawer({ open, onClose }: AppearanceDrawerProps) {
  const { accentColor, setAccentColor, fontSize, setFontSize, setDensity: setUiDensity, setTheme: setUiTheme } = useUIStore();
  const { theme, setTheme, density, setDensity } = useThemeStore();

  const chooseTheme = (nextTheme: ThemeType) => {
    setTheme(nextTheme);
    setUiTheme(nextTheme === 'light-corporate' ? 'light' : 'dark');
  };

  const chooseDensity = (nextDensity: DensityType, uiDensity: UIDensity) => {
    setDensity(nextDensity);
    setUiDensity(uiDensity);
  };

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }}>
      <DialogContent
        className="fixed inset-y-0 left-auto right-0 top-0 z-[110] flex h-dvh w-[min(420px,100vw)] max-w-none translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-l border-border bg-card p-0 shadow-2xl duration-200 data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right sm:rounded-none"
      >
        <header className="shrink-0 border-b border-border px-6 py-5">
          <div className="flex items-center gap-3 pr-8">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary"><Paintbrush className="h-5 w-5" aria-hidden="true" /></span>
            <div>
              <DialogTitle className="text-base font-semibold tracking-tight">Внешний вид</DialogTitle>
              <DialogDescription className="mt-1 text-xs">Настройки сохраняются в этом браузере.</DialogDescription>
            </div>
          </div>
        </header>

        <div className="custom-scrollbar flex-1 space-y-7 overflow-y-auto px-6 py-6">
          <section aria-labelledby="appearance-theme-title" className="space-y-3">
            <h2 id="appearance-theme-title" className="flex items-center gap-2 text-sm font-semibold text-foreground"><MonitorPlay className="h-4 w-4 text-muted-foreground" aria-hidden="true" />Тема</h2>
            <div className="grid grid-cols-2 gap-3">
              {THEMES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={theme === item.id}
                  onClick={() => chooseTheme(item.id)}
                  className={`rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${theme === item.id ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border bg-background hover:border-primary/40'}`}
                >
                  <span className="mb-3 flex h-8 overflow-hidden rounded-md border border-border" aria-hidden="true">
                    {item.swatches.map((color) => <span key={color} className="h-full flex-1" style={{ backgroundColor: color }} />)}
                  </span>
                  <span className="block text-sm font-medium text-foreground">{item.label}</span>
                  <span className="mt-1 block text-xs leading-4 text-muted-foreground">{item.description}</span>
                </button>
              ))}
            </div>
          </section>

          <section aria-labelledby="appearance-accent-title" className="space-y-3">
            <h2 id="appearance-accent-title" className="flex items-center gap-2 text-sm font-semibold text-foreground"><Palette className="h-4 w-4 text-muted-foreground" aria-hidden="true" />Цвет акцента</h2>
            <div className="flex flex-wrap gap-3">
              {ACCENTS.map((accent) => (
                <button
                  key={accent.id}
                  type="button"
                  aria-label={accent.label}
                  aria-pressed={accentColor === accent.id}
                  onClick={() => setAccentColor(accent.id)}
                  className={`flex h-10 w-10 items-center justify-center rounded-full border-2 transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${accentColor === accent.id ? 'border-foreground' : 'border-transparent'}`}
                >
                  <span className="h-7 w-7 rounded-full shadow-sm" style={{ backgroundColor: accent.color }} />
                </button>
              ))}
            </div>
          </section>

          <section aria-labelledby="appearance-scale-title" className="space-y-3">
            <h2 id="appearance-scale-title" className="flex items-center gap-2 text-sm font-semibold text-foreground"><Type className="h-4 w-4 text-muted-foreground" aria-hidden="true" />Размер текста</h2>
            <div className="grid grid-cols-3 rounded-xl border border-border bg-muted/60 p-1">
              {([
                ['sm', 'Маленький'],
                ['base', 'Обычный'],
                ['lg', 'Крупный'],
              ] as [FontScale, string][]).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={fontSize === id}
                  onClick={() => setFontSize(id)}
                  className={`min-h-9 rounded-lg px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${fontSize === id ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          <section aria-labelledby="appearance-density-title" className="space-y-3">
            <h2 id="appearance-density-title" className="flex items-center gap-2 text-sm font-semibold text-foreground"><LayoutGrid className="h-4 w-4 text-muted-foreground" aria-hidden="true" />Плотность интерфейса</h2>
            <div className="space-y-2">
              {DENSITIES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={density === item.id}
                  onClick={() => chooseDensity(item.id, item.uiId)}
                  className={`flex min-h-16 w-full items-center justify-between gap-4 rounded-xl border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${density === item.id ? 'border-primary bg-primary/5' : 'border-border bg-background hover:border-primary/40'}`}
                >
                  <span><span className="block text-sm font-medium text-foreground">{item.label}</span><span className="mt-1 block text-xs text-muted-foreground">{item.description}</span></span>
                  <span className={`h-4 w-4 shrink-0 rounded-full border ${density === item.id ? 'border-[5px] border-primary' : 'border-muted-foreground/40'}`} aria-hidden="true" />
                </button>
              ))}
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
