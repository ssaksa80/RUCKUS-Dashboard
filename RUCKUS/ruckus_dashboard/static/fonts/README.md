# Self-hosted UI font (optional, CSP-safe)

The modern UI (`body[data-ui="modern"]`, enabled by `RUCKUS_MODERN_UI=1`) ships
with a **system font stack** by default:

```
system-ui, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif
```

No font is downloaded, nothing is fetched from a CDN, and the Content-Security-Policy
stays exactly `script-src 'self'` / `style-src 'self'`. This directory is empty on
purpose — the app fabricates no binary font.

## Activating a self-hosted face

If you want a branded typeface, self-host it here so it is served **same-origin**
(which keeps CSP intact — Google Fonts / any external origin is **not** allowed):

1. Drop a WOFF2 file in this directory named **`ui.woff2`**
   (`RUCKUS/ruckus_dashboard/static/fonts/ui.woff2`). Use a variable font if you
   have one so a single file covers all weights. Only `.woff2` is expected.
2. In `static/styles.css`, **uncomment** the `@font-face` block (search for
   `@font-face` / `ui.woff2`). Its `src` already points at the same-origin
   `url("fonts/ui.woff2")`, so no CSP change is needed.
3. In the same file, prepend the family to the `--font-ui` token, e.g.:

   ```css
   --font-ui: "UIFont", system-ui, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
   ```

That's it — the modern skin picks it up everywhere via `var(--font-ui)`. Because
the file is served from `static/` (same-origin), it is fully compatible with the
strict CSP; do **not** reference an external font URL.

## Why WOFF2 only

WOFF2 is the smallest broadly-supported web-font format and is all this app needs
for evergreen browsers. Keeping a single same-origin file avoids any third-party
request and keeps the security posture unchanged.
