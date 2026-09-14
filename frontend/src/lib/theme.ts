export const THEMES = ["dark", "nord", "warm", "slate", "light"] as const;
export type Theme = (typeof THEMES)[number];

export const THEME_SWATCHES: Record<Theme, { bg: string; accent: string }> = {
  dark: { bg: "#08080B", accent: "#F0A63A" },
  nord: { bg: "#2E3440", accent: "#88C0D0" },
  warm: { bg: "#1C1510", accent: "#E39A57" },
  slate: { bg: "#161B22", accent: "#58A6FF" },
  light: { bg: "#F3F1EC", accent: "#9E620E" },
};

/** "dark" is the stored id of the default theme; Cinema is what it is called. */
export const THEME_LABELS: Record<Theme, string> = {
  dark: "Cinema",
  nord: "Nord",
  warm: "Warm",
  slate: "Slate",
  light: "Light",
};

export const THEME_STORAGE_KEY = "brein_theme";

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

/**
 * Runs before first paint, inlined in <head>, so the page never flashes the
 * default theme before the stored one is applied.
 */
export const THEME_INIT_SCRIPT = `(function(){try{
var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
var valid=${JSON.stringify(THEMES)};
if(valid.indexOf(t)===-1){t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}
document.documentElement.setAttribute('data-theme',t);
}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;
