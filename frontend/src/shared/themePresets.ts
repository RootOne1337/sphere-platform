import type { ThemeType } from './theme';

/** Both appearance entry points present the same palette catalog. */
export const THEME_PRESETS: { id: ThemeType; label: string; description: string; swatches: string[] }[] = [
  { id: 'neo-dark', label: 'Тёмная', description: 'Нейтральная тёмная тема', swatches: ['#0a0c0f', '#101216', '#33c295'] },
  { id: 'light-corporate', label: 'Светлая', description: 'Чистая рабочая область', swatches: ['#f5f7f9', '#ffffff', '#127855'] },
  { id: 'deep-space', label: 'Deep Space', description: 'Тёмно-синяя палитра', swatches: ['#05050f', '#080817', '#3399ff'] },
  { id: 'matrix-green', label: 'Matrix', description: 'Зелёная контрастная палитра', swatches: ['#000a00', '#001400', '#00ff00'] },
  { id: 'graphite', label: 'Графит', description: 'Спокойные нейтральные оттенки', swatches: ['#131416', '#191b1f', '#91b5f3'] },
  { id: 'sandstone', label: 'Песочная', description: 'Мягкие тёплые оттенки', swatches: ['#f8f5ef', '#fdfcfb', '#86501d'] },
];
