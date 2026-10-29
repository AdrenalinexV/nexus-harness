---
name: nexus-layout-skins
description: "Design layouts (skins) for the Nexus cockpit."
license: MIT
keywords: "diseño layout skin terminal minimal hud documento composición tipografía densidad"
compatibility: hermes, claude-code, agents, codex
version: 1.0.0
author: Nexus Harness
metadata:
  nexus:
    specialty: design
    globs:
      - "nexus_harness/web/skins.css"
      - "nexus_harness/ui_theme.py"
      - "nexus_harness/settings_theme.py"
  hermes:
    tags: [design, layout, skins, ui, typography]
    related_skills: [nexus-visual-identity, nexus-ui-surgeon, nexus-ui-taste]
allowed-tools: [read_file, write_file, patch, terminal, search_files, browser_exec]
---

# Nexus layout skins

Use when the cockpit needs a **different composition** — not a different colour. Colour lives in
`nexus-visual-identity`; here the type, the density, where the state lives and how a message is drawn.

Two independent axes, learned from how others do it:

- **Hermes** separates *skin* (borders, banner, character) from *personality* (tone), and ships named
  skins (`/skin`, `display.skin`).
- **OpenCode** keeps themes as token files with a directory hierarchy; **Crush** exposes layout
  switches (`compact`, `diff unified|split`, `transparent`) apart from colour.
- Conclusion: **composition and colour are different decisions.** 4 skins × 6 pantones = 24 valid
  combinations, each skin with a recommended palette (a recommendation, never a lock).

## The six that ship (three groups: one main, two special, three alternates)

| group | key | composition | recommended palette |
|---|---|---|---|
| **main** | `main` | serif titles, folios in the margin, 1px rules, ruled composer | `paper` |
| **special** | `matrix` | retro terminal: phosphor, scanlines, narrow column, dotted separators, `0x` folio | `crt` |
| **special** | `glossy` | 2000s: gradient bar, beveled glossy buttons, rounded bubbles, inset fields | `paper` |
| alternate | `terminal` | everything monospace, dashed separators, `#` title, `›`/`·` prefixes, dense | `crt` |
| alternate | `minimal` | no folios, no rules, one accent dot, air, sans only, rounded composer | `riso` |
| alternate | `neon` | uppercase, `::` labels, corner brackets, glow, framed message panels | `neon` |

There is also a **font axis** (`ui_font`: `system`, `serif`, `mono`, `condensed`) that changes the
voice without touching the composition — `[data-font="…"]` rules live at the end of `skins.css`.

What each one changes (and a new one must change all four): **type role** (`--serif` vs `--mono` in
titles), **geometry** (radius, rule style, padding), **density** (message rhythm, sidebar width) and
**message shape** (row with folio → panel with brackets → plain paragraph).

## How a skin is built

1. `[data-skin="key"]` block in `web/skins.css` (or `web/skins-special.css` for the specials). The base
   (`main`) has no block: it is the default.
2. Override concrete properties of existing selectors — `.masthead`, `.title`, `.app`, `.msg`,
   `.composer`, `.sfield`, `.sessions`, `.settings-*`. Do not add DOM: the same HTML must serve all four.
3. Keep the contract: folio/gate/judge stay visible (a skin may restyle them, never hide meaning);
   the four state tones keep their meaning; the composer still sends with Ctrl+Enter.
4. Add the row to `ui_theme.SKINS` (key, name, note, recommended palette). Unknown keys fall back to
   `document`; `onboarding.save_settings({"ui_skin": …})` refuses anything not in `SKIN_KEYS`.
5. Prove it: `run(['themes'])` checks that each skin has ≥10 rules and overrides type, grid, message and
   field; then screenshot the skin with 3 different palettes.

## Pitfalls paid for

- **Hiding a grid item with `display:none` collapses the columns.** In `minimal` (and `matrix`) the folio was hidden but
  the track `1.6rem` stayed, so the *name* fell into that 25px column and every title became «ch…».
  Redefine `grid-template-columns` in the skin: `minmax(0,1fr) auto`.
- **Row actions that are `opacity:0` still take width.** Use `display:none` until `:hover`/`.active`.
- **A skin is not a palette.** If your change only touches `--seal`/`--paper`, it belongs in
  `themes.css`. The test fails a "skin" with fewer than ten structural rules.
- **Glow is a theme feature, not a skin feature.** `neon` the skin can request it, but the colour lives
  in the palette (`--glow`), so the same layout works on light paper without a fake halo.
- **Serif on a terminal skin is wrong by definition.** `terminal` and `neon` set `font-family: var(--mono)`
  on `body`; `minimal` removes the serif from titles deliberately.

## Verification

```bash
python -c "import sys;sys.path.insert(0,'.');from nexus_harness.selftests import run;print(run(['themes']))"
NEXUS_PROTOCOL='C:\Proyectos\NexusProtocol' python tools/verify.py   # exit 0
```

Plus a browser pass: switch the skin in `§ Apariencia`, reload (the skin must come back from
`harness.json`, server-rendered `data-skin`), and confirm the contract on every skin — folio or its
equivalent, gate/juez visible, composer sends.
