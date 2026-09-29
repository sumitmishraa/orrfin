# Orrfin brand colours

Source: the founder's palette (26 Sep 2026). Step 1 turns this into the app's design tokens (Tailwind theme + CSS variables).

## Role mapping (what each colour is used for)

| App role | Token | Hex |
|---|---|---|
| Page background | `--orffin-ice-light` | `#f3f9fe` |
| Cards / panels | `--orffin-white` | `#ffffff` |
| Subtle panel / table header | `--orffin-ice` | `#e8f5fe` |
| Sidebar and top header (dark) | `--orffin-navy` | `#050f1b` |
| Sidebar hover / active item background | `--orffin-blue-dark` | `#09203d` |
| Primary button, links, focus ring | `--orffin-blue-medium` | `#2b64ae` |
| Primary button hover | `--orffin-blue` | `#15376a` |
| Text on primary buttons | `--orffin-white` | `#ffffff` |
| Accent (highlights, active tab line, charts) | `--orffin-blue-bright` | `#4496e0` |
| Accent on dark backgrounds | `--orffin-cyan` | `#85c9f7` |
| Main text | `--orffin-ink` | `#071422` |
| Headings / emphasis text | `--orffin-text-blue` | `#15376a` |
| Secondary text, labels | `--orffin-text-muted` | `#5f7690` |
| Borders, dividers | `--orffin-border` | `#bee3fc` |
| Matched / approved | `--orffin-success` | `#2b64ae` |
| Needs review | `--orffin-warning` | `#d99124` |
| Exception / rejected / blocked | `--orffin-error` | `#c94343` |
| Glow behind the logo or hero (decorative only) | `--orffin-cyan-bloom` | `rgb(129 217 251 / 40%)` |
| Frosted sticky header | `--orffin-header-glass` | `rgb(5 15 27 / 82%)` |

## Rules for the UI

- **Status is never shown by colour alone.** "Matched", "Needs review" and "Exception" always show an icon and a text label as well. This matters here because `--orffin-success` is the same blue as the primary buttons, so blue alone can't mean "approved".
- Text must meet WCAG AA contrast (4.5:1 for body text). **Checked in Step 1:** `#5f7690` on `--orffin-ice` is ~4.2:1 and fails, so the app uses `#536a84` for `--orffin-text-muted` (~5.0:1 on ice, ~5.6:1 on white). See `frontend/src/styles/tokens.css`.
- Dark sidebar/header with a light content area: navy chrome, ice/white workspace.

## Original CSS (keep exactly as supplied)

```css
:root {
  /* Core */
  --orffin-navy: #050f1b;
  --orffin-navy-soft: #051325;
  --orffin-blue-dark: #09203d;
  --orffin-blue: #15376a;
  --orffin-blue-medium: #2b64ae;
  --orffin-blue-bright: #4496e0;
  --orffin-cyan: #85c9f7;

  /* Surfaces */
  --orffin-ice: #e8f5fe;
  --orffin-ice-light: #f3f9fe;
  --orffin-white: #ffffff;

  /* Text */
  --orffin-ink: #071422;
  --orffin-text-blue: #15376a;
  --orffin-text-muted: #5f7690;

  /* Borders and states */
  --orffin-border: #bee3fc;
  --orffin-success: #2b64ae;
  --orffin-warning: #d99124;
  --orffin-error: #c94343;

  /* Effects */
  --orffin-cyan-bloom: rgb(129 217 251 / 40%);
  --orffin-header-glass: rgb(5 15 27 / 82%);
}
```

Fonts: not specified yet. Step 1 uses Inter; change it here if you have brand fonts.
Logo: not supplied yet. Put the file in `frontend/public/` and write its name here.
