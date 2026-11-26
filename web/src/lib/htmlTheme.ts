/**
 * Injects theme metadata & dark class hints into untrusted HTML strings rendered inside
 * sandboxed preview iframes so light/dark mode styling stays consistent across preview panes.
 */
export function injectHtmlTheme(rawHtml: string, dark: boolean): string {
  const theme = dark ? "dark" : "light";
  const themeTag =
    `<meta name="color-scheme" content="${theme}">` +
    `<style data-whitz-theme>:root{color-scheme:${theme};--whitz-theme:${theme};}</style>` +
    `<script>(function(){try{document.documentElement.setAttribute("data-theme","${theme}");document.documentElement.classList.toggle("dark",${dark});}catch(e){}})();<\/script>`;

  if (/<head[\s>]/i.test(rawHtml)) {
    return rawHtml.replace(/<head([^>]*)>/i, `<head$1>${themeTag}`);
  }
  if (/<html[\s>]/i.test(rawHtml)) {
    return rawHtml.replace(/<html([^>]*)>/i, `<html$1><head>${themeTag}</head>`);
  }
  return `<!doctype html><html data-theme="${theme}" class="${dark ? "dark" : ""}"><head><meta charset="utf-8">${themeTag}</head><body>${rawHtml}</body></html>`;
}
