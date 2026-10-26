// theme.js -- light/dark theme ka hook.
// index.html ka chhota script pehle hi data-theme set kar deta hai (flash na ho);
// ye hook usi value ko padhta hai aur toggle par badal kar localStorage me save karta hai.
import { useCallback, useEffect, useState } from "react";

const KEY = "studypilot_theme";
const current = () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");

// useTheme() -> [theme ('light'|'dark'), toggle()]
export function useTheme() {
  const [theme, setTheme] = useState(current);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const toggle = useCallback(() => {
    setTheme(prev => {
      const next = prev === "dark" ? "light" : "dark";
      try { localStorage.setItem(KEY, next); } catch { /* private mode: sirf is session ke liye */ }
      return next;
    });
  }, []);
  return [theme, toggle];
}