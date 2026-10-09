---
version: alpha
name: ocp-graph-agent
description: "Product UI for finance and planning analysts, built on IBM Carbon tokens (from docs/design/ibm-carbon.DESIGN.md). White and gray surfaces, charcoal type, one blue accent, square corners, dense tables with tabular figures. Numbers are the content: the chrome stays quiet so the numbers can be read."
source: "VoltAgent/awesome-design-md design-md/ibm (MIT, commit 13be5c0), adapted from marketing pages to a data product"

colors:
  primary: "#0f62fe"
  primary-hover: "#0050e6"
  primary-pressed: "#002d9c"
  ink: "#161616"
  ink-muted: "#525252"
  ink-subtle: "#6f6f6f"
  canvas: "#ffffff"
  surface-1: "#f4f4f4"
  surface-2: "#e0e0e0"
  hairline: "#e0e0e0"
  hairline-strong: "#8d8d8d"
  focus: "#0f62fe"
  success: "#24a148"
  warning: "#f1c21b"
  error: "#da1e28"
  llm: "#8a3ffc"

colors-dark:
  primary: "#4589ff"
  ink: "#f4f4f4"
  ink-muted: "#c6c6c6"
  ink-subtle: "#a8a8a8"
  canvas: "#161616"
  surface-1: "#262626"
  surface-2: "#393939"
  hairline: "#393939"
  focus: "#ffffff"
  success: "#42be65"
  warning: "#f1c21b"
  error: "#fa4d56"
  llm: "#a56eff"

typography:
  family: "IBM Plex Sans, Helvetica Neue, Arial, sans-serif"
  mono: "IBM Plex Mono, ui-monospace, Menlo, monospace"
  page-title: { size: 32px, weight: 300, lineHeight: 1.25 }
  section: { size: 20px, weight: 400, lineHeight: 1.4 }
  body: { size: 14px, weight: 400, lineHeight: 1.43, letterSpacing: 0.16px }
  label: { size: 12px, weight: 400, lineHeight: 1.33, letterSpacing: 0.32px }
  table: { size: 14px, weight: 400, numeric: tabular-nums }
  emphasis: { size: 14px, weight: 600 }

rounded: { default: 0px, badge: 2px, pill: 9999px }
spacing: { base: 4px, xs: 8px, sm: 12px, md: 16px, lg: 24px, xl: 32px }
---

# OCP graph agent: design system

The visual rules for everything a person looks at in this repo: the Streamlit app (`ui/app.py`), the HTML pages in
`docs/media/`, and the figures in `docs/figures/`. The base is IBM's Carbon as captured in
`docs/design/ibm-carbon.DESIGN.md`. That file describes Carbon's marketing pages. This one keeps its tokens and adapts
them to a product surface where most of the screen is tables of numbers. The Streamlit theme in
`.streamlit/config.toml` carries these tokens.

## Who reads this UI

Finance and planning analysts, at a desk, on a large screen, comparing branch submissions and market prices. They read
numbers, not marketing. Dense is good; decoration is noise. Every screen answers one question: "what moved, why, and
what do I approve?"

## Colour

- One accent, `primary` blue: primary button, links, the selected tab, the focus ring. Nothing else is blue.
- Surfaces: `canvas` for the page, `surface-1` for inputs, sidebars and alternate bands, `hairline` for borders. No
  shadows. No gradients.
- Status colours (`success`, `warning`, `error`) only for state: a check passed, a value is missing, a check failed.
  Never as decoration, never for "the number went down" on its own: a falling cost is good news.
- `llm` purple marks the one thing an LLM produced (a ranking, a narrative). Everything deterministic stays neutral.
  This is how the reader tells computed numbers from model output at a glance.
- Dark mode uses the `colors-dark` set (Carbon Gray 100). Both modes must pass WCAG AA contrast for body text.

## Type

- IBM Plex Sans for everything, IBM Plex Mono for code, formulas, cell references and IDs.
- Page title at weight 300. Section titles at 400. Do not bold headings; weight 600 is for one emphasised value or the
  selected tab.
- Sentence case everywhere. No all-caps tracked eyebrows.
- Body text 14px with 0.16px tracking; table text 14px; labels and captions 12px.

## Numbers

- `font-variant-numeric: tabular-nums` on every table and every number that sits beside another number.
- Right-align numeric columns. Units go in the column header (`M$`, `$/t`, `kt`), not in every cell.
- Minus sign `−` for negatives, a sign on every change (`+21.1`, `−27.9`), one decimal for M$, none for $/t.
- Format with the locale (`Intl.NumberFormat` in HTML, a single formatter in Python), never by hand in many places.
- A missing value is shown as `n/a` with a reason on hover, never as `0`.
- Anything not from OCP data carries the label "Illustrative, not OCP data." next to it.

## Shape and space

- Square corners (`rounded.default` 0px) on buttons, inputs, cards, tables. 2px only for small badges.
- 4px grid. 16px gaps between controls, 24px between sections, 32px around page content.
- Separate sections with a hairline or a `surface-1` band, not with large empty gaps.

## Components

- **Primary button**: blue fill, white text, square, 40px high. One per view; it is the action the view exists for
  (Diagnose, Save decision, Approve). Secondary actions are ghost or outline buttons.
- **Destructive or irreversible actions** (approve a merge, approve a spec) state what will happen in the label and
  ask for confirmation, or offer undo.
- **Tables**: hairline rows, `surface-1` header, no zebra stripes unless the table is wider than 8 columns.
- **Tabs**: text tabs with a 2px blue underline on the selected one.
- **Empty states**: one sentence saying what is missing and the next step ("No diagnoses yet. Ask the agent why a
  metric moved."). Never an empty table.
- **Loading**: say what is happening and end with `…` ("Agent working, tool calls can take a minute…").

## Motion

- Motion only to show flow (data moving along an edge in a pipeline diagram). No decorative motion.
- Animate `transform` and `opacity` only. Honour `prefers-reduced-motion`: no autoplay, no moving packets.
- Anything that plays for more than 5 seconds has pause, previous and next controls, all reachable by keyboard.

## Copy

- Active voice, second person, specific button labels ("Save decision", not "Submit").
- Errors say what failed and what to do next.
- No em dashes in UI copy; use a comma, a colon or two sentences.
- `…` not `...`, curly quotes in prose.

## How to use this file

- Before building or changing UI, read this file. For a redesign of a docs or landing page, also use the
  `design-taste-frontend` skill (`.claude/skills/taste-skill/`); it is written for landing pages and redesigns, not for
  data tables, so for the Streamlit app this file wins where they disagree.
- Before shipping a UI change, run the `web-design-guidelines` skill (`.claude/skills/web-design-guidelines/`) on the
  changed files and fix what it reports.
- Other ready-made styles live in VoltAgent/awesome-design-md. To switch style, replace the tokens above and the theme in
  `.streamlit/config.toml` together, and keep the Numbers, Copy and Motion sections: they come from the product, not
  the brand.
