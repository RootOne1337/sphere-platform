export type ThemeType = 'neo-dark' | 'matrix-green' | 'deep-space' | 'light-corporate' | 'graphite' | 'sandstone';
export type DensityType = 'compact' | 'cozy' | 'spacious';
export type AccentColor = 'theme' | 'violet' | 'blue' | 'emerald' | 'rose' | 'amber';
export type FontScale = 'sm' | 'base' | 'lg';
export type SurfaceStyle = 'solid' | 'glass';
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
        '--destructive-foreground': '222 47% 11%',
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
        '--muted-foreground': '120 35% 57%',
        '--accent': '120 100% 6%',
        '--accent-foreground': '120 100% 50%',
        '--destructive-foreground': '222 47% 11%',
        '--border': '120 100% 15%',
        '--input': '120 100% 15%',
        '--ring': '120 100% 50%',
        '--success': '120 100% 50%',
        '--warning': '60 100% 50%',
        '--destructive': '0 85% 70%',
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
        '--destructive-foreground': '222 47% 11%',
        '--border': '240 30% 20%',
        '--input': '240 30% 20%',
        '--ring': '210 100% 60%',
        '--success': '160 80% 40%',
        '--warning': '40 90% 60%',
        '--destructive': '350 80% 70%',
    },
    'light-corporate': {
        '--background': '210 24% 97%',
        '--foreground': '222 36% 14%',
        '--card': '0 0% 100%',
        '--card-foreground': '222 36% 14%',
        '--popover': '0 0% 100%',
        '--popover-foreground': '222 47% 11%',
        '--primary': '160 74% 27%',
        '--primary-foreground': '0 0% 100%',
        '--secondary': '210 20% 94%',
        '--secondary-foreground': '222 36% 14%',
        '--muted': '210 20% 94%',
        '--muted-foreground': '215 16% 42%',
        '--accent': '160 42% 94%',
        '--accent-foreground': '160 78% 24%',
        '--border': '214 22% 88%',
        '--input': '214 22% 88%',
        '--ring': '160 74% 27%',
        '--success': '152 62% 27%',
        '--warning': '32 90% 27%',
        '--destructive-foreground': '0 0% 100%',
        '--destructive': '0 76% 43%',
    },
    'graphite': {
        '--background': '220 9% 8%', '--foreground': '220 14% 96%',
        '--card': '220 9% 11%', '--card-foreground': '220 14% 96%',
        '--popover': '220 9% 13%', '--popover-foreground': '220 14% 96%',
        '--primary': '215 80% 76%', '--primary-foreground': '222 47% 11%',
        '--secondary': '220 9% 17%', '--secondary-foreground': '220 14% 96%',
        '--muted': '220 9% 17%', '--muted-foreground': '220 10% 70%',
        '--accent': '220 14% 19%', '--accent-foreground': '215 80% 83%',
        '--border': '220 9% 23%', '--input': '220 9% 28%', '--ring': '215 80% 76%',
        '--success': '152 65% 58%', '--warning': '38 92% 68%',
        '--destructive': '0 84% 72%', '--destructive-foreground': '222 47% 11%',
    },
    'sandstone': {
        '--background': '40 33% 96%', '--foreground': '28 22% 15%',
        '--card': '40 40% 99%', '--card-foreground': '28 22% 15%',
        '--popover': '40 40% 99%', '--popover-foreground': '28 22% 15%',
        '--primary': '28 65% 32%', '--primary-foreground': '0 0% 100%',
        '--secondary': '38 24% 91%', '--secondary-foreground': '28 22% 15%',
        '--muted': '38 24% 91%', '--muted-foreground': '28 12% 38%',
        '--accent': '35 40% 91%', '--accent-foreground': '28 65% 28%',
        '--border': '35 18% 83%', '--input': '35 18% 80%', '--ring': '28 65% 32%',
        '--success': '152 62% 27%', '--warning': '32 90% 27%',
        '--destructive': '0 76% 43%', '--destructive-foreground': '0 0% 100%',
    },
};

export const DENSITIES: Record<DensityType, Record<string, string>> = {
    'compact': {
        '--radius': '0.375rem',
        '--spacing-base': '0.75',
        '--control-height': '2rem', '--control-sm-height': '1.75rem', '--control-lg-height': '2.5rem',
        '--control-icon-size': '2rem', '--control-padding': '0.75rem',
        '--row-padding-y': '0.5rem', '--row-padding-x': '0.75rem',
        '--page-gap': '1rem', '--page-padding-y': '1rem', '--page-padding-x': '1.25rem',
        '--panel-padding': '0.875rem', '--nav-height': '2.25rem',
    },
    'cozy': {
        '--radius': '0.625rem',
        '--spacing-base': '1',
        '--control-height': '2.375rem', '--control-sm-height': '2rem', '--control-lg-height': '2.75rem',
        '--control-icon-size': '2.375rem', '--control-padding': '1rem',
        '--row-padding-y': '0.75rem', '--row-padding-x': '1rem',
        '--page-gap': '1.5rem', '--page-padding-y': '1.5rem', '--page-padding-x': '1.5rem',
        '--panel-padding': '1.25rem', '--nav-height': '2.5rem',
    },
    'spacious': {
        '--radius': '0.875rem',
        '--spacing-base': '1.25',
        '--control-height': '2.75rem', '--control-sm-height': '2.375rem', '--control-lg-height': '3rem',
        '--control-icon-size': '2.75rem', '--control-padding': '1.25rem',
        '--row-padding-y': '1rem', '--row-padding-x': '1.25rem',
        '--page-gap': '2rem', '--page-padding-y': '2rem', '--page-padding-x': '2rem',
        '--panel-padding': '1.5rem', '--nav-height': '2.75rem',
    }
};

export const isTheme = (value: unknown): value is ThemeType => typeof value === 'string' && Object.hasOwn(THEMES, value);
export const isDensity = (value: unknown): value is DensityType => typeof value === 'string' && Object.hasOwn(DENSITIES, value);

export const ACCENT_TOKENS = {
    violet: { dark: '262 85% 78%', light: '263 70% 43%' },
    blue: { dark: '213 93% 70%', light: '221 83% 45%' },
    emerald: { dark: '160 65% 55%', light: '160 74% 27%' },
    rose: { dark: '347 85% 75%', light: '347 72% 39%' },
    amber: { dark: '38 95% 65%', light: '32 90% 27%' },
} as const;
export const FONT_SCALES: Record<FontScale, string> = { sm: '87.5%', base: '100%', lg: '112.5%' };
export const isAccent = (value: unknown): value is AccentColor => value === 'theme' || (typeof value === 'string' && Object.hasOwn(ACCENT_TOKENS, value));
export const isFontScale = (value: unknown): value is FontScale => typeof value === 'string' && Object.hasOwn(FONT_SCALES, value);
export const isLightTheme = (theme: ThemeType) => theme === 'light-corporate' || theme === 'sandstone';

export interface AppearanceOptions { accentColor?: AccentColor; fontSize?: FontScale; surfaceStyle?: SurfaceStyle }

/** The same resolver owns every token before paint and after hydration. */
export function resolveAppearance(theme: ThemeType, density: DensityType, options: AppearanceOptions = {}): Record<string, string> {
    const tokens = { ...THEMES[theme], ...DENSITIES[density], '--font-size-base': FONT_SCALES[options.fontSize ?? 'base'] };
    const accent = options.accentColor ?? 'theme';
    if (accent !== 'theme') {
        const color = ACCENT_TOKENS[accent][isLightTheme(theme) ? 'light' : 'dark'];
        Object.assign(tokens, { '--primary': color, '--primary-foreground': isLightTheme(theme) ? '0 0% 100%' : '222 47% 11%',
            '--ring': color, '--accent-foreground': color });
    }
    return tokens;
}

export function applyTheme(root: HTMLElement, theme: ThemeType, density: DensityType, options: AppearanceOptions = {}) {
    Object.entries(resolveAppearance(theme, density, options)).forEach(([key, value]) => root.style.setProperty(key, value));
    root.classList.remove('matrix-mode', 'light-mode', 'space-mode', 'dark');
    root.classList.toggle('dark', !isLightTheme(theme));
    root.classList.toggle('matrix-mode', theme === 'matrix-green');
    root.classList.toggle('light-mode', isLightTheme(theme));
    root.classList.toggle('space-mode', theme === 'deep-space');
    root.style.colorScheme = isLightTheme(theme) ? 'light' : 'dark';
    root.dataset.theme = theme;
    root.dataset.density = density;
    root.dataset.surface = options.surfaceStyle ?? 'glass';
    // Remove the legacy inline font size that used to override density tokens.
    root.style.removeProperty('font-size');
}

// Runs before the page paints. Only known tokens are read from storage; no
// stored CSS or JavaScript is evaluated. Explicit light/density choices survive.
export const themeBootstrapScript = `(function(){try{
var themes=${JSON.stringify(THEMES)},densities=${JSON.stringify(DENSITIES)},accents=${JSON.stringify(ACCENT_TOKENS)},fonts=${JSON.stringify(FONT_SCALES)},p={},u={};
try{p=JSON.parse(localStorage.getItem('sphere-theme-preferences')||'null')?.state||{};}catch(_){}
try{u=JSON.parse(localStorage.getItem('sphere-ui-preferences')||'null')?.state||{};}catch(_){}
var t=Object.prototype.hasOwnProperty.call(themes,p.theme)?p.theme:'neo-dark';
var d=Object.prototype.hasOwnProperty.call(densities,p.density)?p.density:'cozy';
var r=document.documentElement;
var light=t==='light-corporate'||t==='sandstone';
var tokens=Object.assign({},themes[t],densities[d],{'--font-size-base':Object.prototype.hasOwnProperty.call(fonts,u.fontSize)?fonts[u.fontSize]:fonts.base});
if(Object.prototype.hasOwnProperty.call(accents,u.accentColor)){
var color=accents[u.accentColor][light?'light':'dark'];tokens['--primary']=color;tokens['--primary-foreground']=light?'0 0% 100%':'222 47% 11%';tokens['--ring']=color;tokens['--accent-foreground']=color;}
Object.entries(tokens).forEach(function(e){r.style.setProperty(e[0],e[1]);});
r.classList.remove('matrix-mode','light-mode','space-mode','dark');
if(!light)r.classList.add('dark');
if(light)r.classList.add('light-mode');
if(t==='matrix-green')r.classList.add('matrix-mode');
if(t==='deep-space')r.classList.add('space-mode');
r.style.colorScheme=light?'light':'dark';
r.dataset.theme=t;r.dataset.density=d;r.dataset.surface=u.surfaceStyle==='solid'?'solid':'glass';
r.style.removeProperty('font-size');
}catch(_){}})();`;
