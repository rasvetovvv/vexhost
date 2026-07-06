# Product

## Register

product

## Users

Indie developers and Telegram builders (bots, mini apps, small APIs, static sites). They live in Telegram, ship small projects fast, and want free hosting without DevOps. Two contexts: evaluating VexHost on the landing page (brand moment), and daily project management in the dashboard/console (product moment). Interface language is English; `lang="en"`.

## Product Purpose

VexHost is free hosting for websites, servers and Telegram bots. Users create a project from the browser or from @VexHostBot, get a `*.vexory.xyz` subdomain, edit files in a built-in editor, deploy into isolated Docker containers, and watch live logs/metrics. Success = a first-time user goes from landing to a live deployed project in minutes, and returns to the dashboard as their daily control center.

## Brand Personality

Strict, premium, engineered. Vercel-adjacent restraint: monochrome surfaces, one functional accent (Telegram blue reserved for Telegram touchpoints), green only for "live" status. Confidence through precision, not decoration. Copy is direct and technical, never hype.

## Anti-references

- Glassmorphism / neon-purple aesthetics (the `frontend/newdes` Cyber-Ether system belongs to VexVPN, a different product — do not port it here).
- Crypto/gaming-landing hype: giant gradient text, glow-heavy cards, fake urgency.
- Generic SaaS template look: identical icon-card grids, gradient CTA bands.

## Design Principles

1. **Practice what you preach** — a hosting platform's own site must feel fast, precise and reliable; every rough edge undermines the pitch.
2. **Terminal truth** — show real artifacts (logs, deploy steps, metrics, commands) instead of abstract illustrations.
3. **One accent, spent deliberately** — monochrome by default; color always carries meaning (Telegram blue = Telegram, green = live, red = danger).
4. **Dashboard is a tool, not a brochure** — in the console, density, clarity and speed beat decoration.
5. **Honest copy** — no invented numbers, no design-jargon labels leaking into UI text.

## Accessibility & Inclusion

WCAG AA target: body text ≥4.5:1, visible focus states (already present via `:focus-visible`), `prefers-reduced-motion` honored (reveal system already checks it). Works inside Telegram Mini App webview and regular browsers; both dark (default) and light themes must hold contrast.
