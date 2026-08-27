export type WorkbenchTheme = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'egoagent.workbench-theme';

export function readWorkbenchTheme(): WorkbenchTheme {
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved === 'light' || saved === 'dark' || saved === 'system' ? saved : 'system';
}

export function applyWorkbenchTheme(theme: WorkbenchTheme): () => void {
  const root = document.documentElement;
  const media = window.matchMedia('(prefers-color-scheme: light)');
  const ideThemeObserver = new MutationObserver(() => apply());
  const apply = () => {
    const ideIsLight = document.body.classList.contains('vscode-light') || document.body.classList.contains('vscode-high-contrast-light');
    const ideIsDark = document.body.classList.contains('vscode-dark') || document.body.classList.contains('vscode-high-contrast');
    const resolved = theme === 'system' ? (ideIsLight ? 'light' : ideIsDark ? 'dark' : media.matches ? 'light' : 'dark') : theme;
    root.dataset.themeMode = theme;
    root.dataset.theme = resolved;
    root.style.colorScheme = resolved;
  };
  apply();
  localStorage.setItem(STORAGE_KEY, theme);
  if (theme === 'system') {
    media.addEventListener('change', apply);
    ideThemeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }
  return () => {
    if (theme === 'system') {
      media.removeEventListener('change', apply);
      ideThemeObserver.disconnect();
    }
  };
}
