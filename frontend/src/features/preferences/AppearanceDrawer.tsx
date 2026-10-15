'use client';

import { Check, LayoutGrid, Monitor, Paintbrush, Palette, PanelLeft, RotateCcw, Sparkles, Type, Waves } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useUIStore, type AccentColor, type FontScale, type SidebarMode, type SurfaceStyle, type GlassStrength, type MotionMode, type InspectorMode, type UIDensity } from '@/src/shared/store/useUIStore';
import { isLightTheme } from '@/src/shared/theme';
import { THEME_PRESETS, WORKSPACE_LOOKS } from '@/src/shared/themePresets';
import { useThemeStore, type DensityType, type ThemeType } from '@/src/shared/store/themeStore';

const ACCENTS: { id: AccentColor; label: string; color: string }[] = [
  { id: 'emerald', label: 'Изумрудный', color: '#16845d' }, { id: 'blue', label: 'Синий', color: '#2563eb' },
  { id: 'violet', label: 'Фиолетовый', color: '#7c3aed' }, { id: 'rose', label: 'Розовый', color: '#e11d48' }, { id: 'amber', label: 'Янтарный', color: '#b45309' },
];
const DENSITIES: { id: DensityType; uiId: UIDensity; label: string; description: string }[] = [
  { id: 'compact', uiId: 'compact', label: 'Компактная', description: 'Больше строк на экране' },
  { id: 'cozy', uiId: 'comfortable', label: 'Обычная', description: 'Сбалансированные интервалы' },
  { id: 'spacious', uiId: 'spacious', label: 'Свободная', description: 'Больше воздуха и крупнее элементы' },
];

function Section({ title, icon, children, description }: { title: string; icon: ReactNode; children: ReactNode; description?: string }) {
  return <section aria-label={title} className="space-y-3"><h2 className="flex items-center gap-2 text-sm font-semibold">{icon}{title}</h2>{children}{description && <p className="text-xs leading-5 text-muted-foreground">{description}</p>}</section>;
}
function Choices<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (value: T) => void }) {
  return <div role="group" aria-label={label} className="flex gap-1 rounded-xl border border-border bg-muted/60 p-1">{options.map(([id, text]) =>
    <button key={id} type="button" data-ui="button" aria-label={text} aria-pressed={value === id} onClick={() => onChange(id)} className={`min-h-10 min-w-0 flex-1 rounded-lg px-2 py-1 text-xs font-medium [overflow-wrap:anywhere] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${value === id ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>{id === 'auto' ? <><span className="sm:hidden">Авто</span><span className="hidden sm:inline">{text}</span></> : text}</button>)}</div>;
}

export function AppearanceDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ui = useUIStore(); const { theme, setTheme, density, setDensity } = useThemeStore();
  const chooseTheme = (next: ThemeType) => { setTheme(next); ui.setTheme(isLightTheme(next) ? 'light' : 'dark'); };
  const chooseDensity = (next: DensityType, uiDensity: UIDensity) => { setDensity(next); ui.setDensity(uiDensity); };
  const chooseLook = (look: typeof WORKSPACE_LOOKS[number]) => {
    chooseTheme(look.theme);
    useUIStore.setState({ accentColor: look.accentColor, surfaceStyle: look.surfaceStyle, glassStrength: look.glassStrength });
  };
  const recommended = WORKSPACE_LOOKS.find(look => look.id === (ui.surfaceStyle === 'glass'
    ? theme === 'sandstone' ? 'sand-glass' : isLightTheme(theme) ? 'mist-glass' : 'space-glass'
    : isLightTheme(theme) ? 'sand-matte' : 'graphite-matte'))!;

  return <Dialog open={open} onOpenChange={next => { if (!next) onClose(); }}>
    <DialogContent placement="right" className="z-[110] gap-0 overflow-hidden border-border">
      <header className="shrink-0 border-b border-border px-5 py-5 sm:px-6"><div className="flex items-center gap-3 pr-8">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Paintbrush className="h-5 w-5" aria-hidden /></span>
        <div><DialogTitle className="text-base font-semibold tracking-tight">Внешний вид</DialogTitle><DialogDescription className="mt-1 text-xs">Ваше рабочее пространство. Сохраняется в этом браузере.</DialogDescription></div>
      </div></header>
      <Tabs defaultValue="style" className="flex min-h-0 flex-1 flex-col">
        <div className="shrink-0 border-b px-5 py-3 sm:px-6"><TabsList className="grid h-auto w-full grid-cols-2"><TabsTrigger value="style" className="min-h-10">Стиль</TabsTrigger><TabsTrigger value="layout" className="min-h-10">Компоновка</TabsTrigger></TabsList></div>
        <TabsContent value="style" className="custom-scrollbar m-0 min-h-0 flex-1 space-y-6 overflow-y-auto overscroll-contain px-5 py-5 sm:px-6">
          <div className="appearance-sample relative overflow-hidden rounded-2xl border border-border p-4" aria-label={`Предпросмотр: ${ui.surfaceStyle === 'glass' ? 'стекло' : 'матовые поверхности'}`}>
            <div className="sphere-material relative rounded-xl border border-border p-3"><div className="flex items-center gap-2 text-sm font-semibold"><span className="h-2 w-2 rounded-full bg-primary" />Sphere<span className="ml-auto rounded-md bg-primary px-2 py-1 text-[10px] text-primary-foreground">Акцент</span></div><div className="mt-3 h-2 w-3/4 rounded bg-muted-foreground/25" /><div className="mt-2 h-2 w-1/2 rounded bg-muted-foreground/15" /></div>
            <p className="relative mt-3 text-xs font-medium text-foreground">{ui.surfaceStyle === 'glass' ? 'Тонированное стекло и мягкий свет' : 'Спокойные непрозрачные поверхности'}</p>
          </div>
          <Section title="Готовые сочетания" icon={<Sparkles className="h-4 w-4 text-muted-foreground" aria-hidden />} description="Палитра, акцент и материал в один клик. Размер текста и плотность сохраняются.">
            <div className="grid grid-cols-2 gap-2">{WORKSPACE_LOOKS.map(look => {
              const selected = theme === look.theme && ui.accentColor === look.accentColor && ui.surfaceStyle === look.surfaceStyle && (look.surfaceStyle !== 'glass' || ui.glassStrength === look.glassStrength);
              return <button key={look.id} type="button" data-ui="button" aria-pressed={selected} onClick={() => chooseLook(look)} className={`min-h-16 rounded-xl border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected ? 'border-primary bg-primary/10' : 'border-border bg-card hover:border-primary/40'}`}><span className="flex items-center justify-between gap-1 text-sm font-medium">{look.label}{selected && <Check className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />}</span><span className="mt-1 block text-xs text-muted-foreground">{look.description}</span></button>;
            })}</div>
          </Section>
          <Section title="Палитра" icon={<Monitor className="h-4 w-4 text-muted-foreground" aria-hidden />}>
            <div className="grid grid-cols-2 gap-2">{THEME_PRESETS.map(item => <button key={item.id} type="button" data-ui="button" aria-pressed={theme === item.id} onClick={() => chooseTheme(item.id)} className={`rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${theme === item.id ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border bg-card hover:border-primary/40'}`}>
              <span className="mb-2 flex h-6 overflow-hidden rounded-md border border-border" aria-hidden>{item.swatches.map(color => <span key={color} className="h-full flex-1" style={{ backgroundColor: color }} />)}</span><span className="block text-sm font-medium">{item.label}</span><span className="mt-1 block text-xs leading-4 text-muted-foreground">{item.description}</span>
            </button>)}</div>
          </Section>
          <Section title="Цвет акцента" icon={<Palette className="h-4 w-4 text-muted-foreground" aria-hidden />}>
            <div className="flex flex-wrap gap-2"><button type="button" data-ui="button" aria-label="Акцент темы" aria-pressed={ui.accentColor === 'theme'} onClick={() => ui.setAccentColor('theme')} className={`flex h-11 items-center gap-2 rounded-full border px-3 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${ui.accentColor === 'theme' ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}><Palette className="h-4 w-4" aria-hidden />Авто</button>
              {ACCENTS.map(accent => <button key={accent.id} type="button" data-ui="button" aria-label={accent.label} aria-pressed={ui.accentColor === accent.id} onClick={() => ui.setAccentColor(accent.id)} className={`relative flex h-11 w-11 items-center justify-center rounded-full border-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${ui.accentColor === accent.id ? 'border-foreground' : 'border-transparent'}`}><span className="h-7 w-7 rounded-full shadow-sm" style={{ backgroundColor: accent.color }} />{ui.accentColor === accent.id && <Check className="absolute h-4 w-4 text-white" aria-hidden />}</button>)}
            </div>
          </Section>
          <Section title="Материал" icon={<Waves className="h-4 w-4 text-muted-foreground" aria-hidden />} description="Стекло: прозрачные тонированные плитки, панели и окна. Непрозрачный режим полностью убирает прозрачность. Поля, таблицы, редактор и видео сохраняют сплошной рабочий фон.">
            <Choices<SurfaceStyle> label="Материал" value={ui.surfaceStyle} options={[[ 'glass', 'Стекло' ], [ 'solid', 'Непрозрачный' ]]} onChange={ui.setSurfaceStyle} />
            {ui.surfaceStyle === 'glass' && <Choices<GlassStrength> label="Интенсивность стекла" value={ui.glassStrength} options={[[ 'soft', 'Лёгкое' ], [ 'balanced', 'Среднее' ], [ 'vivid', 'Яркое' ]]} onChange={ui.setGlassStrength} />}
            <Button variant="outline" size="sm" className="w-full" onClick={() => chooseLook(recommended)}><Sparkles className="h-3.5 w-3.5" aria-hidden />Рекомендуемое сочетание</Button>
          </Section>
        </TabsContent>
        <TabsContent value="layout" className="custom-scrollbar m-0 min-h-0 flex-1 space-y-6 overflow-y-auto overscroll-contain px-5 py-5 sm:px-6">
          <Section title="Размер текста" icon={<Type className="h-4 w-4 text-muted-foreground" aria-hidden />}><Choices<FontScale> label="Размер текста" value={ui.fontSize} options={[[ 'sm', 'Маленький' ], [ 'base', 'Обычный' ], [ 'lg', 'Крупный' ]]} onChange={ui.setFontSize} /></Section>
          <Section title="Плотность интерфейса" icon={<LayoutGrid className="h-4 w-4 text-muted-foreground" aria-hidden />}><div className="space-y-2">{DENSITIES.map(item => <button key={item.id} type="button" data-ui="button" aria-pressed={density === item.id} onClick={() => chooseDensity(item.id, item.uiId)} className={`flex min-h-14 w-full items-center justify-between gap-3 rounded-xl border px-4 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${density === item.id ? 'border-primary bg-primary/5' : 'border-border bg-card'}`}><span><span className="block text-sm font-medium">{item.label}</span><span className="mt-1 block text-xs text-muted-foreground">{item.description}</span></span>{density === item.id && <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden />}</button>)}</div></Section>
          <Section title="Боковая панель" icon={<PanelLeft className="h-4 w-4 text-muted-foreground" aria-hidden />} description="Автоматическое меню раскрывается при наведении или фокусе. На телефоне — по кнопке."><Choices<SidebarMode> label="Боковая панель" value={ui.sidebarMode} options={[[ 'auto', 'Автоматически' ], [ 'pinned', 'Закреплена' ], [ 'rail', 'Свёрнута' ]]} onChange={ui.setSidebarMode} /></Section>
          <Section title="Карточка устройства" icon={<Monitor className="h-4 w-4 text-muted-foreground" aria-hidden />} description="Просторное окно по центру или панель справа. На телефоне карточка занимает весь экран."><Choices<InspectorMode> label="Карточка устройства" value={ui.inspectorMode} options={[[ 'modal', 'Окно' ], [ 'drawer', 'Панель справа' ]]} onChange={ui.setInspectorMode} /></Section>
          <Section title="Анимации" icon={<Sparkles className="h-4 w-4 text-muted-foreground" aria-hidden />} description="Короткие переходы окон, меню и вкладок. Системное уменьшение движения имеет приоритет."><Choices<MotionMode> label="Анимации" value={ui.motionMode} options={[[ 'system', 'Плавные' ], [ 'reduced', 'Минимальные' ]]} onChange={ui.setMotionMode} /></Section>
        </TabsContent>
      </Tabs>
      <footer className="shrink-0 border-t px-5 py-3 [padding-bottom:max(.75rem,env(safe-area-inset-bottom))]"><Button type="button" variant="ghost" size="sm" onClick={() => { chooseTheme('neo-dark'); chooseDensity('cozy', 'comfortable'); useUIStore.setState({ accentColor: 'theme', fontSize: 'base', sidebarMode: 'auto', sidebarExpanded: true, surfaceStyle: 'glass', glassStrength: 'balanced', motionMode: 'system', inspectorMode: 'modal' }); }}><RotateCcw className="h-3.5 w-3.5" aria-hidden />Сбросить настройки</Button></footer>
    </DialogContent>
  </Dialog>;
}
