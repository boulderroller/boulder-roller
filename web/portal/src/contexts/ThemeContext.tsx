import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { BR_PRIMARY_ALPHA_THEME, SEMANTIC_COLORS } from '../constants/colors';

export type ThemeId = 'hoo-breddin' | 'water' | 'sunny' | 'safari' | 'moss' | 'foundries';
export const DEFAULT_THEME_ID: ThemeId = 'hoo-breddin';

interface Theme {
  id: ThemeId;
  name: string;
  emoji: string;
  light: {
    bg: string;
    bgSecondary: string;
    accent: string;
    text: string;
    textMuted: string;
    border: string;
  };
  dark: {
    bg: string;
    bgSecondary: string;
    accent: string;
    text: string;
    textMuted: string;
    border: string;
  };
}

export const THEMES: Record<ThemeId, Theme> = {
  'hoo-breddin': {
    id: 'hoo-breddin',
    name: 'Hoo-Breddin',
    emoji: '🍂',
    light: {
      bg: '#f9faf5',
      bgSecondary: '#f3f5ed',
      accent: '#8b9475',
      text: '#2a2d1e',
      textMuted: '#6b7a5a',
      border: '#2a2d1e',
    },
    dark: {
      bg: '#2a2d1e',
      bgSecondary: '#1a1d14',
      accent: '#8b9475',
      text: '#f9faf5',
      textMuted: '#a0a89a',
      border: '#3a3d2e',
    },
  },
  water: {
    id: 'water',
    name: 'Water',
    emoji: '🌊',
    light: {
      bg: '#f0f8ff',
      bgSecondary: '#e6f3ff',
      accent: '#4a90d9',
      text: '#1e3a5f',
      textMuted: '#4a6b8a',
      border: '#1e3a5f',
    },
    dark: {
      bg: '#1e3a5f',
      bgSecondary: '#152840',
      accent: '#6ba8d4',
      text: '#e8f4ff',
      textMuted: '#8fb5d9',
      border: '#2e4a6f',
    },
  },
  sunny: {
    id: 'sunny',
    name: 'Sunny',
    emoji: '☀️',
    light: {
      bg: '#fffcf0',
      bgSecondary: '#fff8e6',
      accent: '#f0c869',
      text: '#4a3f1e',
      textMuted: '#8a7a5a',
      border: '#4a3f1e',
    },
    dark: {
      bg: '#3a2f1e',
      bgSecondary: '#2a2014',
      accent: '#f0c869',
      text: '#fffef5',
      textMuted: '#c9b899',
      border: '#4a3f2e',
    },
  },
  safari: {
    id: 'safari',
    name: 'Safari',
    emoji: '🦒',
    light: {
      bg: '#faf7f0',
      bgSecondary: '#f5f0e6',
      accent: '#c7a76f',
      text: '#4a3829',
      textMuted: '#8a7a6a',
      border: '#4a3829',
    },
    dark: {
      bg: '#3a2f26',
      bgSecondary: '#2a2016',
      accent: '#d9b885',
      text: '#f5f0e8',
      textMuted: '#b5a599',
      border: '#4a3f36',
    },
  },
  moss: {
    id: 'moss',
    name: 'Moss',
    emoji: '🌲',
    light: {
      bg: '#f5f9f0',
      bgSecondary: '#edf5e6',
      accent: '#6b8e5a',
      text: '#2a3d1e',
      textMuted: '#5a7a4a',
      border: '#2a3d1e',
    },
    dark: {
      bg: '#2a3d1e',
      bgSecondary: '#1a2d14',
      accent: '#8ba87a',
      text: '#f0f9f0',
      textMuted: '#9ab599',
      border: '#3a4d2e',
    },
  },
  foundries: {
    id: 'foundries',
    name: 'Foundries',
    emoji: '🏭',
    light: {
      bg: '#f5f5f5',
      bgSecondary: '#ebebeb',
      accent: '#6b7a8e',
      text: '#2a2d38',
      textMuted: '#5a6a7a',
      border: '#2a2d38',
    },
    dark: {
      bg: '#2a2d38',
      bgSecondary: '#1a1d28',
      accent: '#8e9aab',
      text: '#f0f3f5',
      textMuted: '#9aa5b5',
      border: '#3a3d48',
    },
  },
};

const PRIMARY_ALPHA_PORTAL_COLORS: Theme['light'] = {
  bg: BR_PRIMARY_ALPHA_THEME.colors.paper,
  bgSecondary: BR_PRIMARY_ALPHA_THEME.colors.paperSoft,
  accent: BR_PRIMARY_ALPHA_THEME.colors.terrain,
  text: BR_PRIMARY_ALPHA_THEME.colors.ink,
  textMuted: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  border: BR_PRIMARY_ALPHA_THEME.colors.line,
};

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && value in THEMES;
}

interface ThemeContextType {
  themeId: ThemeId;
  isDarkMode: boolean;
  theme: Theme;
  setThemeId: (id: ThemeId) => void;
  setDarkMode: (dark: boolean) => void;
  toggleDarkMode: () => void;
  colors: Theme['light'] | Theme['dark'];
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Initialize from localStorage or defaults
  const [themeId, setThemeId] = useState<ThemeId>(() => {
    const saved = localStorage.getItem('boulder-roller-theme-id');
    return isThemeId(saved) ? saved : DEFAULT_THEME_ID;
  });

  const [isDarkMode, setIsDarkMode] = useState(() => {
    const saved = localStorage.getItem('boulder-roller-dark-mode');
    if (saved !== null) {
      return saved === 'true';
    }
    // Respect system preference if no saved preference
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  const theme = THEMES[themeId] ?? THEMES[DEFAULT_THEME_ID];
  const colors = PRIMARY_ALPHA_PORTAL_COLORS;

  const setDarkMode = (dark: boolean) => {
    setIsDarkMode(dark);
  };

  const toggleDarkMode = () => {
    setIsDarkMode(!isDarkMode);
  };

  // Persist theme preferences to localStorage
  useEffect(() => {
    localStorage.setItem('boulder-roller-theme-id', themeId);
  }, [themeId]);

  useEffect(() => {
    localStorage.setItem('boulder-roller-dark-mode', isDarkMode.toString());
  }, [isDarkMode]);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.portalTheme = BR_PRIMARY_ALPHA_THEME.id;
    root.dataset.portalColorScheme = 'dark';
  }, [themeId, isDarkMode]);

  // Apply CSS variables to root
  useEffect(() => {
    const root = document.documentElement;
    // Core Boulder Roller Variables
    root.style.setProperty('--br-theme-id', BR_PRIMARY_ALPHA_THEME.id);
    root.style.setProperty('--br-paper', BR_PRIMARY_ALPHA_THEME.colors.paper);
    root.style.setProperty('--br-paper-soft', BR_PRIMARY_ALPHA_THEME.colors.paperSoft);
    root.style.setProperty('--br-card', BR_PRIMARY_ALPHA_THEME.colors.card);
    root.style.setProperty('--br-ink', BR_PRIMARY_ALPHA_THEME.colors.ink);
    root.style.setProperty('--br-ink-soft', BR_PRIMARY_ALPHA_THEME.colors.inkSoft);
    root.style.setProperty('--br-ink-muted', BR_PRIMARY_ALPHA_THEME.colors.inkMuted);
    root.style.setProperty('--br-ink-faint', BR_PRIMARY_ALPHA_THEME.colors.inkFaint);
    root.style.setProperty('--br-line', BR_PRIMARY_ALPHA_THEME.colors.line);
    root.style.setProperty('--br-terrain', BR_PRIMARY_ALPHA_THEME.colors.terrain);
    root.style.setProperty('--br-cal', BR_PRIMARY_ALPHA_THEME.colors.cal);
    root.style.setProperty('--br-dung', BR_PRIMARY_ALPHA_THEME.colors.dung);
    root.style.setProperty('--br-radius-control', BR_PRIMARY_ALPHA_THEME.radius.control);
    root.style.setProperty('--br-radius-surface', BR_PRIMARY_ALPHA_THEME.radius.surface);
    root.style.setProperty('--br-font-sans', BR_PRIMARY_ALPHA_THEME.fonts.sans);
    root.style.setProperty('--br-font-mono', BR_PRIMARY_ALPHA_THEME.fonts.mono);

    root.style.setProperty('--color-bg', colors.bg);
    root.style.setProperty('--color-bg-secondary', colors.bgSecondary);
    root.style.setProperty('--color-accent', colors.accent);
    root.style.setProperty('--color-text', colors.text);
    root.style.setProperty('--color-text-muted', colors.textMuted);
    root.style.setProperty('--color-border', colors.border);

    // Portal semantic object colors (--portal-cal, --portal-climb, category
    // and tone ladders, danger) are owned by the stylesheet token layer
    // (portal-spine.css :root). They are deliberately NOT written inline here:
    // an inline custom property on <html> outranks every stylesheet rule and
    // silently kept money cobalt and the category rainbow alive after the
    // 2026-09-01 ledger flip.
    // Map to Shadcn/Tailwind Variables for System Consistency
    root.style.setProperty('--background', colors.bg);
    root.style.setProperty('--foreground', colors.text);
    root.style.setProperty('--card', BR_PRIMARY_ALPHA_THEME.colors.card);
    root.style.setProperty('--card-foreground', colors.text);
    root.style.setProperty('--popover', colors.bgSecondary);
    root.style.setProperty('--popover-foreground', colors.text);
    root.style.setProperty('--primary', colors.accent);
    root.style.setProperty('--primary-foreground', BR_PRIMARY_ALPHA_THEME.colors.paper);
    root.style.setProperty('--secondary', colors.bgSecondary);
    root.style.setProperty('--secondary-foreground', colors.text);
    root.style.setProperty('--muted', BR_PRIMARY_ALPHA_THEME.colors.card);
    root.style.setProperty('--muted-foreground', colors.textMuted);
    root.style.setProperty('--accent', colors.accent);
    root.style.setProperty('--accent-foreground', BR_PRIMARY_ALPHA_THEME.colors.paper);
    root.style.setProperty('--destructive-foreground', BR_PRIMARY_ALPHA_THEME.colors.ink);
    root.style.setProperty('--border', colors.border);
    root.style.setProperty('--input', BR_PRIMARY_ALPHA_THEME.colors.card);
    root.style.setProperty('--input-background', BR_PRIMARY_ALPHA_THEME.colors.card);
    root.style.setProperty('--switch-background', BR_PRIMARY_ALPHA_THEME.colors.inkFaint);
    root.style.setProperty('--ring', colors.accent);

    // Sidebar Specific Mappings
    // IMPORTANT: These must match the variables defined in globals.css for Tailwind to pick them up
    root.style.setProperty('--sidebar', colors.bgSecondary);
    root.style.setProperty('--sidebar-foreground', colors.text);
    root.style.setProperty('--sidebar-primary', colors.accent);
    root.style.setProperty('--sidebar-primary-foreground', BR_PRIMARY_ALPHA_THEME.colors.paper);
    root.style.setProperty('--sidebar-accent', colors.accent + '20'); // Low opacity accent for hover
    root.style.setProperty('--sidebar-accent-foreground', colors.text);
    root.style.setProperty('--sidebar-border', colors.border);
    root.style.setProperty('--sidebar-ring', colors.accent);
  }, [colors, isDarkMode]);

  return (
    <ThemeContext.Provider value={{ themeId, isDarkMode, theme, setThemeId, setDarkMode, toggleDarkMode, colors }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
