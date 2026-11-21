import type { StateStorage } from 'zustand/middleware';

// Historical values can still paint the public shell. Only the account-scoped
// synchronizer persists authenticated changes, with a verified identity and revision.
export const browserAppearanceStorage: StateStorage = {
  getItem: name => typeof window === 'undefined' ? null : window.localStorage.getItem(name),
  setItem: () => undefined,
  removeItem: name => { if (typeof window !== 'undefined') window.localStorage.removeItem(name); },
};
