---
name: VexHost Strict Premium
colors:
  # Dark theme (default)
  bg: '#000000'
  paper: '#0a0a0a'
  ink: '#ededed'
  gray-1: '#141414'
  gray-2: '#262626'
  gray-3: '#8f8f8f'
  gray-4: '#a1a1a1'
  border-strong: '#3a3a3a'
  tg: '#229ed9'
  tg-2: '#2aabee'
  live: '#22c55e'
  danger: '#e5484d'
  # Light theme overrides via [data-theme="light"]
  light-bg: '#ffffff'
  light-ink: '#0a0a0a'
  light-gray-2: '#eaeaea'
typography:
  display:
    fontFamily: Geist
    fontSize: clamp(40px, 7vw, 80px)
    fontWeight: '600'
    lineHeight: '1.01'
    letterSpacing: '-0.045em'
  title:
    fontFamily: Geist
    fontSize: clamp(28px, 4vw, 42px)
    fontWeight: '600'
    letterSpacing: '-0.04em'
  body:
    fontFamily: Geist
    fontSize: 16px
    lineHeight: '1.5'
    letterSpacing: '-0.011em'
  lead:
    fontFamily: Geist
    fontSize: 18px
    lineHeight: '1.6'
  eyebrow:
    fontFamily: Geist Mono
    fontSize: 12px
    fontWeight: '500'
    letterSpacing: '.14em'
    textTransform: uppercase
  mono:
    fontFamily: Geist Mono
    fontSize: 13px
rounded:
  sm: 6px
  DEFAULT: 8px
  md: 12px
  lg: 16px
  full: 999px
spacing:
  maxw: 1120px
  section: 96px 24px
  card-pad: 26px
  panel-pad: 24px
motion:
  ease: cubic-bezier(0.23, 1, 0.32, 1)
  ease-in-out: cubic-bezier(0.77, 0, 0.175, 1)
  ease-ios: cubic-bezier(0.32, 0.72, 0, 1)
---

## Brand & Style

Strict premium, Vercel-adjacent. Dark is the default theme; light is opt-in via `[data-theme="light"]` (persisted in `localStorage.vexhost_theme`). Monochrome surfaces built from a black→gray ramp; **one chromatic accent** — Telegram blue — reserved exclusively for Telegram touchpoints (bot links, chat mockup, telegram-flavored cards). Green (`--live`) means "running/live" only; red (`#e5484d`) means danger/crash only. No gradients on text, no glassmorphism (the `frontend/newdes` Cyber-Ether system belongs to VexVPN — never port it here).

## Colors

All tokens are CSS custom properties in `frontend/src/styles.css` `:root`, with a full light-theme override block. Buttons invert per theme (`--btn-primary-bg` is white-on-black in dark, black-on-white in light). The CTA band (`--cta-*`) is deliberately inverted relative to the page. Console/terminal surfaces are **hard-coded dark in both themes** (`#0a0a0a` bg, `#1f1f1f` border) — a terminal is always dark.

## Typography

Geist (sans) + Geist Mono, loaded from Google Fonts. Mono carries the "engineered" voice: eyebrows, badges, stats, file trees, terminal output, footer column headers. Negative tracking scales with size (body −0.011em → display −0.045em). Muted text uses `--gray-4` (secondary) and `--gray-3` (tertiary/mono labels).

## Layout & Spacing

`--maxw: 1120px` container, 24px side padding, 96px section rhythm. Landing sections use `.section-head` (max 640px) with optional `.center`. Dashboard is a `360px + 1fr` grid; IDE view is `262px + 1fr`. Bento feature grid is 3 columns with `feat-lg` (2-col span) and `feat-wide` variants.

## Components

- **Buttons**: `.primary` (inverted mono), `.secondary`/`.btn` (bordered paper), `.btn-tg` (Telegram gradient — the only gradient allowed), `.linkbtn`. 40px height, 8px radius; `.btn-lg` 48px. Tactile press: `scale(0.97)` at 80ms.
- **Cards**: `.card` 12px radius, 1px `--gray-2` border, hover lifts −2px with border-strengthen; suppressed on `(hover:none)`.
- **Panels**: `.panel` 14px radius — dashboard building block.
- **Pills**: `.pill-ok/down/idle` status dots with soft glow shadows.
- **Console mockup**: `.console` with traffic-light dots, mono body, staggered `lineIn` animation, blinking cursor.
- **Metrics**: `.metric` tiles with mono values and 4px `mini-chart` bars.
- **Reveal system**: `.reveal` + IntersectionObserver (`useReveal`), staggered by `--i`, honors `prefers-reduced-motion`, enhances-only (content visible without JS via `.js-reveal` gate).

## Motion

Ease-out quart default (`--ease`), 150–280ms for UI state, staggered entrances for hero/lists. No bounce. Terminal lines animate in at 280ms. Theme switch cross-fades at 200ms.
