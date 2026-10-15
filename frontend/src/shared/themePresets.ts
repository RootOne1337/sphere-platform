import type { ThemeType, AccentColor, SurfaceStyle, GlassStrength } from './theme';

/** Both appearance entry points present the same palette catalog. */
export const THEME_PRESETS: { id: ThemeType; label: string; description: string; swatches: string[] }[] = [
  { id: 'neo-dark', label: 'Тёмная', description: 'Нейтральная тёмная тема', swatches: ['#0a0c0f', '#101216', '#33c295'] },
  { id: 'light-corporate', label: 'Светлая', description: 'Чистая рабочая область', swatches: ['#f5f7f9', '#ffffff', '#127855'] },
  { id: 'deep-space', label: 'Deep Space', description: 'Тёмно-синяя палитра', swatches: ['#05050f', '#080817', '#3399ff'] },
  { id: 'matrix-green', label: 'Matrix', description: 'Зелёная контрастная палитра', swatches: ['#000a00', '#001400', '#00ff00'] },
  { id: 'graphite', label: 'Графит', description: 'Спокойные нейтральные оттенки', swatches: ['#131416', '#191b1f', '#91b5f3'] },
  { id: 'mist', label: 'Туман', description: 'Холодная светлая палитра', swatches: ['#edf1f7', '#fbfcfd', '#2d469f'] },
  { id: 'dune', label: 'Дюна', description: 'Тёплая тёмная палитра', swatches: ['#181411', '#241f1a', '#eac78c'] },
  { id: 'sandstone', label: 'Песочная', description: 'Мягкие тёплые оттенки', swatches: ['#f8f5ef', '#fdfcfb', '#86501d'] },
];

/** Complete, recommended combinations; applying a look leaves text size and density intact. */
export const WORKSPACE_LOOKS: { id: string; label: string; description: string; theme: ThemeType; accentColor: AccentColor; surfaceStyle: SurfaceStyle; glassStrength: GlassStrength }[] = [
  { id: 'sand-matte', label: 'Песчаник', description: 'Тёплый матовый', theme: 'sandstone', accentColor: 'theme', surfaceStyle: 'solid', glassStrength: 'balanced' },
  { id: 'sand-glass', label: 'Песочное стекло', description: 'Тёплый прозрачный', theme: 'sandstone', accentColor: 'theme', surfaceStyle: 'glass', glassStrength: 'vivid' },
  { id: 'mist-glass', label: 'Ледяное стекло', description: 'Светлый · рекомендуем', theme: 'mist', accentColor: 'blue', surfaceStyle: 'glass', glassStrength: 'balanced' },
  { id: 'space-glass', label: 'Ночное стекло', description: 'Тёмный · рекомендуем', theme: 'deep-space', accentColor: 'violet', surfaceStyle: 'glass', glassStrength: 'balanced' },
  { id: 'dune-matte', label: 'Тёплый вечер', description: 'Тёмный матовый', theme: 'dune', accentColor: 'theme', surfaceStyle: 'solid', glassStrength: 'balanced' },
  { id: 'graphite-matte', label: 'Рабочий графит', description: 'Нейтральный матовый', theme: 'graphite', accentColor: 'theme', surfaceStyle: 'solid', glassStrength: 'balanced' },
];
