'use client';

import { Code2, LayoutGrid, Maximize, Monitor, Moon, Paintbrush, Shrink, Sun, type LucideIcon } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { useThemeStore, type DensityType, type ThemeType } from '@/src/shared/store/themeStore';
import { useUIStore, type UIDensity } from '@/src/shared/store/useUIStore';

const THEMES: { id: ThemeType; label: string; description: string; icon: LucideIcon; swatches: string[] }[] = [
    { id: 'light-corporate', label: 'Светлая', description: 'Чистая рабочая область', icon: Sun, swatches: ['#f4f7f8', '#ffffff', '#16845d'] },
    { id: 'neo-dark', label: 'Тёмная', description: 'Нейтральная тёмная тема', icon: Moon, swatches: ['#09090b', '#18181b', '#e4e4e7'] },
    { id: 'deep-space', label: 'Deep Space', description: 'Тёмно-синяя палитра', icon: Monitor, swatches: ['#080817', '#111126', '#3b82f6'] },
    { id: 'matrix-green', label: 'Matrix', description: 'Высокий контраст, зелёный', icon: Code2, swatches: ['#001000', '#061b06', '#00d900'] },
];

const DENSITIES: { id: DensityType; uiId: UIDensity; label: string; description: string; icon: LucideIcon }[] = [
    { id: 'compact', uiId: 'compact', label: 'Компактная', description: 'Больше строк и данных на экране', icon: Shrink },
    { id: 'cozy', uiId: 'comfortable', label: 'Обычная', description: 'Сбалансированные интервалы', icon: LayoutGrid },
    { id: 'spacious', uiId: 'spacious', label: 'Свободная', description: 'Увеличенные отступы и элементы', icon: Maximize },
];

export function ThemeSwitcherModal({ onClose }: { onClose?: () => void }) {
    const { theme, density, setTheme, setDensity } = useThemeStore();
    const setUiTheme = useUIStore((state) => state.setTheme);
    const setUiDensity = useUIStore((state) => state.setDensity);

    const chooseTheme = (nextTheme: ThemeType) => {
        setTheme(nextTheme);
        setUiTheme(nextTheme === 'light-corporate' ? 'light' : 'dark');
    };

    const chooseDensity = (nextDensity: DensityType, uiDensity: UIDensity) => {
        setDensity(nextDensity);
        setUiDensity(uiDensity);
    };

    return (
        <div className="flex flex-col gap-6 p-5 sm:p-6">
            <header className="flex items-center gap-3 border-b border-border pb-5">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary"><Paintbrush className="h-5 w-5" aria-hidden="true" /></span>
                <div>
                    <h2 className="text-base font-semibold tracking-tight">Оформление интерфейса</h2>
                    <p className="mt-1 text-xs text-muted-foreground">Изменения сразу применяются в этом браузере.</p>
                </div>
            </header>

            <section className="space-y-3" aria-labelledby="palette-theme-title">
                <h3 id="palette-theme-title" className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Цветовая тема</h3>
                <div className="grid grid-cols-2 gap-3">
                    {THEMES.map(({ id, label, description, icon: Icon, swatches }) => (
                        <button
                            key={id}
                            type="button"
                            aria-pressed={theme === id}
                            onClick={() => chooseTheme(id)}
                            className={`rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${theme === id ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border bg-background hover:border-primary/40'}`}
                        >
                            <span className="mb-3 flex h-8 overflow-hidden rounded-md border border-border" aria-hidden="true">
                                {swatches.map((color) => <span key={color} className="h-full flex-1" style={{ backgroundColor: color }} />)}
                            </span>
                            <span className="flex items-center gap-2 text-xs font-semibold text-foreground"><Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />{label}</span>
                            <span className="mt-1 block text-[11px] leading-4 text-muted-foreground">{description}</span>
                        </button>
                    ))}
                </div>
            </section>

            <section className="space-y-3" aria-labelledby="palette-density-title">
                <h3 id="palette-density-title" className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Плотность интерфейса</h3>
                <div className="space-y-2">
                    {DENSITIES.map(({ id, uiId, label, description, icon: Icon }) => (
                        <button
                            key={id}
                            type="button"
                            aria-pressed={density === id}
                            onClick={() => chooseDensity(id, uiId)}
                            className={`flex min-h-14 w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${density === id ? 'border-primary bg-primary/5' : 'border-border bg-background hover:border-primary/40'}`}
                        >
                            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Icon className="h-4 w-4" aria-hidden="true" /></span>
                            <span className="min-w-0 flex-1"><span className="block text-sm font-medium text-foreground">{label}</span><span className="mt-0.5 block text-xs text-muted-foreground">{description}</span></span>
                            <span className={`h-4 w-4 shrink-0 rounded-full border ${density === id ? 'border-[5px] border-primary' : 'border-muted-foreground/40'}`} aria-hidden="true" />
                        </button>
                    ))}
                </div>
            </section>

            <section className="space-y-3 rounded-xl border border-border bg-muted/30 p-4" aria-label="Предпросмотр кнопок">
                <p className="text-xs font-semibold text-foreground">Предпросмотр элементов</p>
                <div className="flex flex-wrap gap-2">
                    <Button variant="default" size="sm">Основное действие</Button>
                    <Button variant="outline" size="sm">Вторичное</Button>
                </div>
            </section>

            {onClose && <Button variant="outline" className="w-full" onClick={onClose}>Закрыть настройки</Button>}
        </div>
    );
}
