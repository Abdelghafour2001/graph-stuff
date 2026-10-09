---
name: web-design-guidelines
description: Review UI code for Web Interface Guidelines compliance (accessibility, focus, forms, motion, typography, copy). Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or before shipping any change to ui/ or docs/media/.
metadata:
  author: vercel (rules), adapted for this repo
  version: "1.0.0"
  argument-hint: <file-or-pattern>
---

# Web Interface Guidelines

Review the given files against the rules in `guidelines.md` (next to this file). The rules are a local copy of
vercel-labs/web-interface-guidelines `command.md` (MIT, see `LICENSE`, commit 434b7f9). Use the local copy; do not fetch
a newer one at review time. To update it, replace `guidelines.md` deliberately and review the diff.

## How it works

1. Read `guidelines.md`.
2. Read the files to review (default for this repo: `ui/app.py` and `docs/media/*.html`).
3. Check each rule. Rules written for React/Tailwind map to their plain equivalents: Streamlit widgets already provide
   labels, focus rings and keyboard handling, so for `ui/app.py` look at copy, number formatting, empty states,
   destructive actions and long content; for the HTML pages apply every rule.
4. Also check the file against `DESIGN.md` at the repo root (tokens, type, corners, one accent colour).
5. Output findings in the terse `file:line - issue` format, grouped by file, `✓ pass` for clean files.
