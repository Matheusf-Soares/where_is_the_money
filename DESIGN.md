---
name: Onde foi parar?
description: Investigação de gastos pessoal, local e dark-only, no padrão do dashboard financeiro executado com rigor.
colors:
  graphite-base: "#0c0d10"
  graphite-lateral: "#0f1013"
  graphite-surface: "#14161a"
  graphite-raised: "#1a1c21"
  graphite-raised-high: "#212429"
  hairline: "#23262c"
  hairline-strong: "#2e3138"
  hairline-max: "#3b3f47"
  ink: "#eceef1"
  ink-secondary: "#a6abb5"
  ink-tertiary: "#7f8590"
  action-blue: "#6e9fff"
  action-blue-strong: "#8fb5ff"
  action-blue-wash: "rgba(110,159,255,.13)"
  action-blue-line: "rgba(110,159,255,.38)"
  action-ink: "#08132b"
  credit-green: "#4cc790"
  credit-green-wash: "rgba(76,199,144,.12)"
  spend-coral: "#f2786d"
  spend-coral-wash: "rgba(242,120,109,.12)"
  partial-amber: "#e8b65a"
  partial-amber-wash: "rgba(232,182,90,.1)"
  partial-amber-line: "rgba(232,182,90,.32)"
  help-lilac: "#c6b8ff"
  help-ink: "#1d1740"
  help-ground: "#121219"
  help-line: "#2a2840"
  help-wash: "#1e1b33"
  help-text: "#dcd8ec"
  help-muted: "#a19bbd"
typography:
  display:
    fontFamily: "Geist Variable, Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.03em"
    fontFeature: "\"tnum\""
  headline:
    fontFamily: "Geist Variable, Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.025em"
    fontFeature: "\"tnum\""
  title-page:
    fontFamily: "Geist Variable, Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Geist Variable, Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Geist Variable, Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"ss01\", \"cv11\""
  label:
    fontFamily: "Geist Variable, Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.3
  caption:
    fontFamily: "Geist Variable, Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.45
  mono:
    fontFamily: "Geist Mono Variable, Geist Mono, ui-monospace, Cascadia Mono, Menlo, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.7
  help-reading:
    fontFamily: "Iowan Old Style, Sitka Text, Charter, Cambria, Georgia, serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.65
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  pill: "999px"
spacing:
  hairline-gap: "1px"
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "20px"
  panel-x: "22px"
  total-gap: "18px"
components:
  button:
    backgroundColor: "{colors.graphite-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 13px"
    height: "34px"
  button-hover:
    backgroundColor: "{colors.graphite-raised-high}"
  button-primary:
    backgroundColor: "{colors.action-blue}"
    textColor: "{colors.action-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 13px"
    height: "34px"
  button-primary-hover:
    backgroundColor: "{colors.action-blue-strong}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-secondary}"
    rounded: "{rounded.md}"
    padding: "0 13px"
    height: "34px"
  input:
    backgroundColor: "{colors.graphite-surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 11px"
    height: "36px"
  chip:
    backgroundColor: "{colors.graphite-surface}"
    textColor: "{colors.ink-tertiary}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: "34px"
  panel:
    backgroundColor: "{colors.graphite-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "20px 22px"
  metric:
    backgroundColor: "{colors.graphite-surface}"
    textColor: "{colors.ink}"
    typography: "{typography.headline}"
    padding: "16px 20px 18px"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink-secondary}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 10px"
    height: "36px"
  nav-item-active:
    backgroundColor: "{colors.graphite-raised-high}"
    textColor: "{colors.ink}"
  pill:
    backgroundColor: "{colors.graphite-raised-high}"
    textColor: "{colors.ink-secondary}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "0 9px"
    height: "22px"
  table-total-row:
    backgroundColor: "{colors.graphite-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "12px"
  drawer:
    backgroundColor: "{colors.graphite-surface}"
    textColor: "{colors.ink}"
    width: "560px"
  help-button:
    backgroundColor: "{colors.help-lilac}"
    textColor: "{colors.help-ink}"
    rounded: "{rounded.pill}"
    size: "32px"
---

# Design System: Onde foi parar?

## Overview

**Creative North Star: "The Quiet Ledger"**

The financial dashboard of the category, chosen on purpose and executed to the Mercury bar: cold graphite in three layers, one-pixel hairlines, a single action blue, and numbers set in Geist with tabular figures. Nothing is smuggled in to look different. The distinction is in the finish: money values that de-emphasise the currency and the cents, a true minus sign, sort chevrons drawn in SVG, totals separated from the rows they sum, and every aggregate clickable down to the transaction that composes it.

Density follows the data. KPI strips and panels breathe; tables are tight hairline grids. Each screen leads with its answer (a number or an ordered list), then what changed or still needs checking, then the transaction-grain table. Colour carries meaning, never decoration: blue is action and the primary series, green and coral are money direction, amber is only "this data is incomplete". The help layer lives in its own lilac world so explanation is never mistaken for data.

Dark-only and Portuguese are product commitments, not states to be completed later. Rejected on purpose: the old quilt of mint-bordered cards, uppercase eyebrow labels, and Unicode glyphs standing in for icons.

**Key Characteristics:**
- Three graphite layers plus a slightly lifted sidebar; depth by tone and 1px hairlines, not shadows.
- One action blue for selection, links, focus and the primary data series.
- Semantic colour is reserved: green = decrease/credit, coral = spend increase/error, amber = partial data or pending review.
- Geist + Geist Mono, tabular numerals everywhere numbers align, fixed nine-step scale.
- Single-stroke 24×24 SVG icons inheriting text colour.
- Detail opens in a right-side drawer; filters are chips; help is a separate lilac layer.

## Colors

A cold, nearly neutral graphite field with one blue voice and three reserved semantic hues.

### Primary
- **Action Blue** (action-blue): selection, links, focus rings, active nav icon, active tab underline, sorted-column chevron, bar-list fills, the selected month column, the heat-strip base hue and the primary series of every chart. Primary buttons fill with it and set text in **Action Ink** (action-ink) for contrast.
- **Action Blue Strong** (action-blue-strong): hover state for primary buttons and links; text colour of the accent pill.
- **Action Blue Wash / Line** (action-blue-wash, action-blue-line): selected-row background and border (selected invoice, bulk-selection bar), input focus halo and border.

### Secondary
- **Credit Green** (credit-green) with its wash: spending that went down, credit/inflow, positive net-worth change, the "live" freshness dot, successful-state pills.
- **Spend Coral** (spend-coral) with its wash: spending that went up, debt in the net-worth composition, sync failures and error pills.

### Tertiary
- **Partial Amber** (partial-amber) with its wash and line: notices about incomplete publications, partial totals, "action needed" sync state, and review counts in the nav and tabs. Nothing else.

### Neutral
- **Graphite Base** (graphite-base): page background; also the SQL editor ground.
- **Graphite Lateral** (graphite-lateral): the sidebar, one step lifted from the page.
- **Graphite Surface** (graphite-surface): panels, KPI cells, inputs, chips, drawer.
- **Graphite Raised** (graphite-raised): default buttons, row hover, total rows, skeleton highlight.
- **Graphite Raised High** (graphite-raised-high): active nav item, button hover, neutral pills, bar tracks, checked segment.
- **Hairline / Strong / Max** (hairline, hairline-strong, hairline-max): table and panel dividers; control borders; hover borders and scrollbar thumb.
- **Ink / Secondary / Tertiary** (ink, ink-secondary, ink-tertiary): primary text; supporting text and descriptions; column headers, captions, metadata.

### Help layer
- **Help Lilac** (help-lilac) and its family (help-ink, help-ground, help-line, help-wash, help-text, help-muted): only the help button, help panel, numbered pins over the page and the help focus outline.

### Named Rules
**The One Blue Rule.** Action Blue is the only interactive and primary-series hue. A second accent never appears; a second series uses a lighter tint of the same blue.

**The Reserved Semantics Rule.** Green and coral mean money direction (and coral also means error); amber means only partial or pending data. A rising spend delta is coral, never amber. None of them is used for decoration or identity.

**The Identity Hue Rule.** Bank and merchant avatars take a stable hue from the name, constrained to 190–300° (blues and violets), at 30% saturation/21% lightness for the disc and 70%/80% for the initials, so identity never borrows green or red semantics.

**The Separate Voice Rule.** Lilac belongs to the help layer alone and never mixes with data colours; data colours never appear inside help chrome.

## Typography

**Display Font:** Geist Variable (with Geist, ui-sans-serif, system-ui)
**Body Font:** Geist Variable
**Label/Mono Font:** Geist Mono Variable (with ui-monospace, Cascadia Mono, Menlo), for SQL, identifiers and raw-field values
**Help Reading Font:** Iowan Old Style / Sitka Text / Charter / Cambria / Georgia, only inside the help layer

Both Geist families load from jsDelivr, `@fontsource-variable/geist@5.3.0` and `@fontsource-variable/geist-mono@5.3.0`.

**Character:** A precise, neutral grotesk tuned for numbers. Weight does the hierarchy work (400/500/600) while size steps stay small; the help layer switches to a serif reading voice so explanation sounds different from data.

### Hierarchy
The scale is fixed at nine steps, `--fs-1` to `--fs-9` = 12 / 13 / 14 / 16 / 18 / 20 / 24 / 28 / 34px. This is the scale as built and supersedes the contract's earlier "1.125 ratio" wording.
- **Display** (600, 34px, 1.2, -0.03em): the single net-worth figure on Patrimônio.
- **Headline** (600, 28px, 1.2, -0.025em): KPI values in the metric strip and the drawer's transaction amount. Drops to 20px under 760px.
- **Title-page** (600, 24px, 1.25, -0.02em): the screen `h1` in the topbar; 20px on mobile. Invoice totals also use 24px.
- **Title** (600, 16px, 1.35, -0.01em): panel `h2`, drawer head. 20px is used for the invoice detail heading and help-panel heading.
- **Body** (400, 14px, 1.5): tables, paragraphs, controls. Topbar purpose line capped at 72ch.
- **Label** (500, 13px): buttons, chips, metric labels, sub-descriptions, notices.
- **Caption** (500, 12px): column headers, pills, axis labels, nav group names, metadata under cells. Sentence case, not uppercase.

### Named Rules
**The Tabular Rule.** Every number that can sit above another number uses tabular numerals (`font-variant-numeric: tabular-nums`) and right alignment in tables.

**The Quiet Currency Rule.** Large money values set "R$" and the cents at 0.6em, weight 500, in Ink Secondary, so the integer reads first; negatives use a true minus sign (U+2212), never a hyphen.

**The Fixed Scale Rule.** Sizes come only from the nine `--fs-*` steps; no ad-hoc pixel sizes.

## Layout

A fixed 244px sidebar (212px under 1180px) on the left with grouped navigation and publication freshness in its foot, and a workspace capped at 1520px with `clamp(18px,3vw,44px)` side padding. The topbar holds the screen title, a purpose line, the publication snapshot pill and the help button. Below it, a chip filter bar separated by a hairline, then the screen's answer strip (KPIs or main list) at full width, then the dominant panel. Two-column panel grids use 1.3fr / 1fr (wide variant 1.5fr / 1fr); the invoices screen uses a 0.9fr list beside a sticky 1.5fr detail.

Spacing rhythm is 16px between panels and grid gaps, 20–22px inside panels, 8px between chips and actions, 4px inside lists. Breakpoints: 1180px collapses two-column grids; 900px stacks invoices; 760px turns the sidebar into a sticky blurred top bar with horizontally scrolling nav, hides filters behind a toggle, and sets the KPI strip to two columns. On coarse pointers and under 760px every interactive target grows to 44px. At 1440px and above the help panel pushes the content instead of covering it.

## Elevation & Depth

Flat by default. Depth comes from the three graphite layers and 1px hairlines; panels and KPI strips carry no shadow. Shadows appear only on things that float above the page.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 12px 32px rgba(0,0,0,.45), 0 2px 6px rgba(0,0,0,.3)`): the toast.
- **Drawer edge** (`box-shadow: -24px 0 60px rgba(0,0,0,.5)`): the transaction-detail drawer, over a `rgba(5,6,8,.62)` backdrop. The help panel uses `-24px 0 48px rgba(0,0,0,.45)` and drops it in push mode.
- **Segment lift** (`box-shadow: 0 1px 2px rgba(0,0,0,.35)`): the checked option of a segmented control.
- **Focus halo** (`box-shadow: 0 0 0 3px` Action Blue Wash): focused inputs and chips.

### Named Rules
**The Flat-At-Rest Rule.** Surfaces that sit in the page are separated by tone and hairline, never by shadow; shadow is reserved for overlays.

## Shapes

Gently rounded and consistent: 12px for panels, KPI strips, skeletons and the invoice list; 8px for buttons, inputs, chips, notices, row hovers and the total row; 6px for small buttons, tab tops and heat cells; full pills for badges, pills, counts and the snapshot. Avatars and the help button are circles. All borders are 1px hairlines. Missing data is drawn, not omitted: a 135° hatch of Graphite Raised High (with a dashed border on month columns).

## Components

### Buttons
Quiet and solid, never loud.
- **Shape:** gently rounded (8px), 34px tall; small variant 28px with 6px radius.
- **Default:** Graphite Raised fill, Hairline Strong border, Ink text, label weight 500.
- **Primary:** Action Blue fill and border with Action Ink text at weight 600; hover moves to Action Blue Strong. One primary per panel, placed in the panel header.
- **Ghost:** transparent, Ink Secondary text; hover takes Graphite Raised. Icon buttons are 32px square ghosts.
- **Hover / Focus:** 150ms colour transitions; focus is a 2px Action Blue outline offset 2px. Disabled drops to 45% opacity.

### Chips
- **Style:** each filter is a 34px chip with its label inside in Ink Tertiary and its value in Ink at 500, on Graphite Surface with a Hairline Strong border, 8px radius.
- **State:** hover strengthens the border; focus-within takes the Action Blue line and wash halo. The segmented control groups options in a 3px-padded track; the checked segment sits on Graphite Raised High with a 1px lift.

### Cards / Containers
- **Corner Style:** 12px.
- **Background:** Graphite Surface on Graphite Base.
- **Shadow Strategy:** none (see Elevation).
- **Border:** 1px Hairline.
- **Internal Padding:** 20px 22px; panel head separates title and optional sub line from right-aligned actions by 16px.
- **KPI strip:** metrics are joined into one bordered strip by a 1px gap over a Hairline background, cells auto-fit at 210px minimum. Each cell: label, headline value (clickable to its transactions, underline on hover), small note.

### Inputs / Fields
- **Style:** 36px, Graphite Surface, Hairline Strong border, 8px radius, placeholder in Ink Tertiary; selects carry an SVG chevron.
- **Focus:** border to Action Blue line plus a 3px Action Blue Wash halo; no outline.
- **Field labels** sit above the control at label size in Ink Secondary.

### Navigation
- **Sidebar:** grouped items (group names in caption, sentence case, Ink Tertiary), 36px rows with a 17px icon, Ink Secondary at rest, Graphite Raised on hover, Graphite Raised High with Ink text and a blue icon when active. Pending-review counts are amber pills on the right. Mobile: horizontal scrolling row of filled pills without icons.
- **Tabs:** text tabs over a hairline; the active tab gets a 2px Action Blue underline; counts are neutral pills, amber when they mean pending review.

### Tables
Hairline and sortable. Headers at caption size in Ink Tertiary; cells 11px 12px with 1px Hairline rows and a faint white row hover. Sortable headers carry a two-chevron SVG; the active direction lights in Action Blue and the column header turns Ink. Totals live in the footer, separated from the last row by an 18px empty gap, on a Graphite Raised band with 8px end radii at weight 600. Numbers right-aligned and tabular.

### Pills, Deltas and Quotas
- **Pills:** 22px full-round, caption weight 500; neutral, positive, negative, amber and accent variants each use the colour on its own wash.
- **Deltas:** SVG up/down arrow plus percentage at label size; up is coral, down is green, unchanged is Ink Tertiary with no arrow.
- **Quota bars:** a 6px rounded track on Graphite Raised High with an Action Blue fill and a tabular percentage.

### Heat Strip
Twelve month cells in a 3px-gap grid, filled with Action Blue at an intensity proportional to the value; months without data are hatched, the current month carries a 2px blue inset baseline, and each cell is clickable to that month.

### Detail Drawer
Transaction detail opens in a right-side drawer (up to 560px, full height) that slides 32px in over 260ms on `cubic-bezier(.2,.8,.2,1)`, with a sticky head and a definition grid of fields; raw values in the last section are set in mono.

### Help Layer
A 32px lilac circle in the topbar opens a right-hand panel on Help Ground with lilac accents, serif reading text, numbered lilac pins placed over the page, and a lilac focus outline. It is the only place lilac and serif appear.

### Loading and Notices
Loading shows skeleton blocks (a strip and two panels) shimmering between Graphite Surface and Graphite Raised; never a lone spinner for whole screens. Notices are amber-washed rows with an SVG alert icon for partial data; the info variant is neutral with a blue icon.

## Do's and Don'ts

### Do:
- **Do** lead each screen with its answer (KPI strip or ordered list), then change or pending checks, then the transaction table.
- **Do** make every aggregate (metric, bar, column, heat cell) open the transactions that compose it.
- **Do** use Action Blue for every interactive accent and the primary series; tint it lighter for a second series.
- **Do** set money with de-emphasised "R$" and cents, a true minus sign and tabular numerals.
- **Do** draw missing or partial data explicitly: hatched cells, amber notices, "parcial" in the total label.
- **Do** use the single-stroke SVG icon set (24×24, 1.75 stroke, currentColor) at 16px.
- **Do** separate table totals from the body with the 18px gap and the Graphite Raised band.
- **Do** keep 44px targets on touch and honour reduced motion.

### Don't:
- **Don't** use amber for spending increases; it is reserved for partial data and pending review.
- **Don't** give a bank or merchant a green or red identity colour.
- **Don't** let lilac or the help serif leak into data surfaces, or data colours into the help layer.
- **Don't** return to bordered mint cards, uppercase eyebrow labels above titles, or Unicode glyphs as icons.
- **Don't** add shadows to panels or the KPI strip.
- **Don't** open detail in a centred modal; use the side drawer.
- **Don't** add a light theme or non-Portuguese copy.
- **Don't** show real financial data in any design artefact or capture.
