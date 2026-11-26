# Gist design system

Gist's interface direction is **"analyst's notebook"**: warm paper, ink-dark text, and one evergreen accent. It should feel calm and precise, and above all honest about evidence.

## Principles

1. **Voice vs. system.** Customer words (feedback, quotes, ticket bodies, source text) are set in the serif (`.voice`, Newsreader). Everything Gist says is in the sans (IBM Plex Sans). Record IDs use the mono (IBM Plex Mono, `<Id>`). You can always tell who is speaking.
2. **Every number opens its records.** Figures, bars, months and counts link to the filtered Feedback or Tickets view.
3. **Say what it isn't.** Association ≠ causation, checklists ≠ confidence, suggestions ≠ recommendations. Uncertainty is shown in words, never as a fabricated score.
4. **Spacing and hairlines before boxes.** Use `Section` (a title over a hairline) by default. Use `Panel` (a surface with a 1px border) only for primary data modules and tools. Never nest cards.

## Tokens (`frontend/app/globals.css`, mapped in `tailwind.config.ts`)

| Role | Token | Light | Dark |
|---|---|---|---|
| App background | `paper` | #F5F3EE | #151513 |
| Raised surface | `surface` | #FFFFFC | #1D1C1A |
| Recessed fill | `sunken` | #EDEAE3 | #262522 |
| Text | `ink` / `ink-2` / `ink-3` | 15.5 / 7.0 / 4.9 :1 | 15.0 / 8.2 / 5.3 :1 |
| Hairline / strong line | `line` / `line-strong` | decorative | decorative |
| Control border | `control` | ≥3:1 non-text | ≥3:1 |
| Accent (action, evidence, data) | `accent` (+`-soft`, `-ink`) | #1D5E4E | #7DBFA6 |
| Negative / high severity | `signal` | #A63D26 | #EE9078 |
| Partial / caution / triage | `caution` | #7D5A12 | #D8B260 |
| Positive / resolved | `positive` | #2E6B3A | #8CC38F |

Contrast ratios are WCAG values on `paper`. All text tokens are ≥4.5:1 on every surface in both themes. Dark is designed separately (warm charcoal, lifted sage accent), not inverted. The theme follows the OS by default; the sidebar switch (System / Light / Dark) is stored per device.

**Type scale:** 12 / 13 / 14 / 16 / 20 / 28 / 36 px. **Radius:** 4px (controls), 6px (notices), 8px (panels, sheets); nothing is pill-shaped. **Elevation:** none on content; `shadow-pop` on active segments and tooltips; `shadow-overlay` on dialogs and the command menu only. **Motion:** 120–240ms `cubic-bezier(.2,.8,.2,1)`, used only for state changes (sheet in, drawer slide, fade). All motion is disabled under `prefers-reduced-motion`.

## Components

- **`components/ui.tsx`:** `PageHeader`, `Section`, `Panel`, `Button`/`buttonClass`, `IconButton`, `Field`, `Select`, `Input`, `SearchField`, `Segmented` (radiogroup with arrow keys), `Kbd`, `Id`, `Meta` (dot-separated metadata that wraps without a stray dot), `Status` (dot + word, never colour alone), `Tag`, `TrendMark`, `Figure`, `Notice`, `EmptyState`, `FilterChip`, `Pagination`, `useFlash` (announced confirmations), `useMediaQuery`.
- **`components/dialog.tsx`:** one `Dialog` for every overlay. It is a right drawer on desktop (so context stays visible), a centred modal when asked, and a bottom sheet on phones. It traps focus, closes on Esc or the backdrop, restores focus, and locks scroll.
- **`components/scope.tsx`:** date range, segment and area filters, shared by Overview and Ask. They fold behind a "Filters (n)" button on phones.
- **`components/charts.tsx`:** single-series charts in the accent colour, drawn at the measured container width (labels stay 11px on phones), with a hover/focus tooltip, keyboard-operable months and a table view.
- **`components/shell.tsx`:** sidebar navigation grouped by goal (Overview, Ask · Evidence · *Signal to decision* 1–4), a ⌘K command menu (jump to any page, ask a question, search feedback, switch theme), a phone bottom bar, and the single persistent "Pulse · synthetic data" label.

## Adding a screen

Start from `PageHeader`. Put filters in one row above the content. Use `Section` for groups and `Panel` only for the main module. Show loading with `Loading` (a skeleton that names what is loading), failures with `ErrorState` (what happened plus *Try again*), and nothing-found with `EmptyState` (why it's empty plus the next action). Write copy as a competent colleague would: specific verbs, no hype.
