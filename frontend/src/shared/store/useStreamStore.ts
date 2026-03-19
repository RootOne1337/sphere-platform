import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * Допустимые размеры сетки для Global Operations Center.
 * 1 — одиночный просмотр, до 64 — максимум для enterprise мониторинга.
 * Значения соответствуют количеству ячеек (не строк/колонок).
 */
export const GRID_SIZE_OPTIONS = [1, 4, 9, 16, 25, 32, 48, 64] as const;
export type GridSize = (typeof GRID_SIZE_OPTIONS)[number];

/** Вычислить количество колонок для заданного размера сетки */
export function gridColumns(size: GridSize): number {
    if (size <= 1) return 1;
    if (size <= 4) return 2;
    if (size <= 9) return 3;
    if (size <= 16) return 4;
    if (size <= 25) return 5;
    if (size <= 32) return 6;  // 6×6 = 36 ячеек, 32 устройства + 4 пустых
    if (size <= 48) return 7;  // 7×7 = 49 ячеек
    return 8;                  // 8×8 = 64 ячейки
}

/** Человекочитаемая метка (для кнопки) */
export function gridLabel(size: GridSize): string {
    const cols = gridColumns(size);
    const rows = Math.ceil(size / cols);
    return `${cols}×${rows}`;
}

interface StreamState {
    gridSize: GridSize;
    objectFit: 'contain' | 'cover' | 'fill';
    quality: 'auto' | '1080p' | '720p' | 'low';
    showHUD: boolean;
    showStats: boolean;
    setGridSize: (size: GridSize) => void;
    setObjectFit: (fit: 'contain' | 'cover' | 'fill') => void;
    setQuality: (quality: 'auto' | '1080p' | '720p' | 'low') => void;
    toggleHUD: () => void;
    toggleStats: () => void;
}

export const useStreamStore = create<StreamState>()(
    persist(
        (set) => ({
            gridSize: 4,
            objectFit: 'contain',
            quality: 'auto',
            showHUD: true,
            showStats: true,
            setGridSize: (size) => set({ gridSize: size }),
            setObjectFit: (fit) => set({ objectFit: fit }),
            setQuality: (quality) => set({ quality }),
            toggleHUD: () => set((state) => ({ showHUD: !state.showHUD })),
            toggleStats: () => set((state) => ({ showStats: !state.showStats })),
        }),
        {
            name: 'sphere-stream-storage',
        }
    )
);
