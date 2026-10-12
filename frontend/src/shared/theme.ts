export type ThemeType = 'neo-dark' | 'matrix-green' | 'deep-space' | 'light-corporate';
export type DensityType = 'compact' | 'cozy' | 'spacious';
export const DEFAULT_THEME: ThemeType = 'neo-dark';
export const DEFAULT_DENSITY: DensityType = 'cozy';

export const THEMES: Record<ThemeType, Record<string, string>> = {
    'neo-dark': {
        '--background': '222 20% 5%',
        '--foreground': '210 20% 96%',
        '--card': '222 18% 7%',
        '--card-foreground': '210 20% 96%',
        '--popover': '222 18% 8%',
        '--popover-foreground': '210 20% 96%',
        '--primary': '160 65% 48%',
        '--primary-foreground': '164 70% 5%',
        '--secondary': '218 15% 12%',
        '--secondary-foreground': '210 20% 92%',
        '--muted': '218 15% 12%',
        '--muted-foreground': '217 12% 65%',
        '--accent': '160 20% 13%',
        '--accent-foreground': '158 65% 72%',
        '--border': '218 14% 17%',
        '--input': '218 14% 20%',
        '--ring': '160 65% 48%',
        '--success': '152 65% 48%',
        '--warning': '38 92% 58%',
        '--destructive': '0 84% 68%',
        '--destructive-foreground': '0 0% 100%',
    },
    'matrix-green': {
        '--background': '120 100% 2%', // Very dark green #000A00
        '--foreground': '120 100% 40%', // Hacker green #00CC00
        '--card': '120 100% 4%',
        '--card-foreground': '120 100% 40%',
        '--popover': '120 100% 4%',
        '--popover-foreground': '120 100% 40%',
        '--primary': '120 100% 50%', // Bright green #00FF00
        '--primary-foreground': '120 100% 2%',
        '--secondary': '120 100% 6%',
        '--secondary-foreground': '120 100% 40%',
        '--muted': '120 100% 6%',
        '--muted-foreground': '120 100% 25%',
        '--accent': '120 100% 6%',
        '--accent-foreground': '120 100% 50%',
        '--destructive-foreground': '0 0% 100%',
        '--border': '120 100% 15%',
        '--input': '120 100% 15%',
        '--ring': '120 100% 50%',
        '--success': '120 100% 50%',
        '--warning': '60 100% 50%',
        '--destructive': '0 100% 50%',
    },
    'deep-space': {
        '--background': '240 50% 4%', // Very dark blue #05050F
        '--foreground': '210 50% 90%', // Light blueish white
        '--card': '240 50% 6%',
        '--card-foreground': '210 50% 90%',
        '--popover': '240 50% 6%',
        '--popover-foreground': '210 50% 90%',
        '--primary': '210 100% 60%', // Sci-fi blue
        '--primary-foreground': '240 50% 4%',
        '--secondary': '240 30% 10%',
        '--secondary-foreground': '210 50% 90%',
        '--muted': '240 30% 10%',
        '--muted-foreground': '210 30% 60%',
        '--accent': '240 30% 10%',
        '--accent-foreground': '210 100% 70%',
        '--destructive-foreground': '0 0% 100%',
        '--border': '240 30% 20%',
        '--input': '240 30% 20%',
        '--ring': '210 100% 60%',
        '--success': '160 80% 40%',
        '--warning': '40 90% 60%',
        '--destructive': '350 80% 60%',
    },
    'light-corporate': {
        '--background': '210 24% 97%',
        '--foreground': '222 36% 14%',
        '--card': '0 0% 100%',
        '--card-foreground': '222 36% 14%',
        '--popover': '0 0% 100%',
        '--popover-foreground': '222 47% 11%',
        '--primary': '160 74% 34%',
        '--primary-foreground': '0 0% 100%',
        '--secondary': '210 20% 94%',
        '--secondary-foreground': '222 36% 14%',
        '--muted': '210 20% 94%',
        '--muted-foreground': '215 16% 42%',
        '--accent': '160 42% 94%',
        '--accent-foreground': '160 78% 24%',
        '--border': '214 22% 88%',
        '--input': '214 22% 88%',
        '--ring': '160 74% 34%',
        '--success': '152 62% 32%',
        '--warning': '38 92% 42%',
        '--destructive-foreground': '0 0% 100%',
        '--destructive': '0 84% 50%',
    }
};

export const DENSITIES: Record<DensityType, Record<string, string>> = {
    'compact': {
        '--radius': '0.375rem',
        '--spacing-base': '0.75', // Scaled down everything 
        '--font-size-base': '85%',
    },
    'cozy': {
        '--radius': '0.625rem',
        '--spacing-base': '1',
        '--font-size-base': '100%',
    },
    'spacious': {
        '--radius': '0.875rem',
        '--spacing-base': '1.25',
        '--font-size-base': '115%',
    }
};

export const isTheme = (value: unknown): value is ThemeType => typeof value === 'string' && Object.hasOwn(THEMES, value);
export const isDensity = (value: unknown): value is DensityType => typeof value === 'string' && Object.hasOwn(DENSITIES, value);

export function applyTheme(root: HTMLElement, theme: ThemeType, density: DensityType) {
    Object.entries({ ...THEMES[theme], ...DENSITIES[density] }).forEach(([key, value]) => root.style.setProperty(key, value));
    root.classList.remove('matrix-mode', 'light-mode', 'space-mode', 'dark');
    root.classList.toggle('dark', theme !== 'light-corporate');
    root.classList.toggle('matrix-mode', theme === 'matrix-green');
    root.classList.toggle('light-mode', theme === 'light-corporate');
    root.classList.toggle('space-mode', theme === 'deep-space');
    root.style.colorScheme = theme === 'light-corporate' ? 'light' : 'dark';
}

// Runs before the page paints. Only known tokens are read from storage; no
// stored CSS or JavaScript is evaluated. Explicit light/density choices survive.
export const themeBootstrapScript = `(function(){try{
var themes=${JSON.stringify(THEMES)},densities=${JSON.stringify(DENSITIES)},p={};
try{p=JSON.parse(localStorage.getItem('sphere-theme-preferences')||'null')?.state||{};}catch(_){}
var t=Object.prototype.hasOwnProperty.call(themes,p.theme)?p.theme:'neo-dark';
var d=Object.prototype.hasOwnProperty.call(densities,p.density)?p.density:'cozy';
var r=document.documentElement;
Object.entries(Object.assign({},themes[t],densities[d])).forEach(function(e){r.style.setProperty(e[0],e[1]);});
r.classList.remove('matrix-mode','light-mode','space-mode','dark');
if(t!=='light-corporate')r.classList.add('dark');
if(t==='light-corporate')r.classList.add('light-mode');
if(t==='matrix-green')r.classList.add('matrix-mode');
if(t==='deep-space')r.classList.add('space-mode');
r.style.colorScheme=t==='light-corporate'?'light':'dark';
}catch(_){}})();`;
