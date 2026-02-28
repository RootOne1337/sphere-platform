import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface StreamState {
    gridSize: 1 | 4 | 9 | 16;
    objectFit: 'contain' | 'cover' | 'fill';
    quality: 'auto' | '1080p' | '720p' | 'low';
    showHUD: boolean;
    showStats: boolean;
    setGridSize: (size: 1 | 4 | 9 | 16) => void;
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
