import { create } from 'zustand';

interface CommandPaletteState {
    isOpen: boolean;
    toggle: () => void;
    open: () => void;
    close: () => void;
}

export const useCommandPaletteStore = create<CommandPaletteState>((set) => ({
    isOpen: false,
    toggle: () => set((state) => ({ isOpen: !state.isOpen })),
    open: () => set({ isOpen: true }),
    close: () => set({ isOpen: false }),
}));
