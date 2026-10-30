---
name: nexus-ui-surgeon
description: "Rework the Nexus-Harness cockpit UI to a document."
license: MIT
compatibility: hermes, claude-code, agents, codex
metadata:
  nexus:
    specialty: ui
    globs:
      - "nexus_harness/web/*"
      - "nexus_harness/ui.py"
      - "nexus_harness/ui_icons.py"
      - "nexus_harness/settings*.py"
      - "nexus_harness/panels.py"
      - "nexus_harness/charts.py"
allowed-tools: [read_file, write_file, patch, terminal, search_files, browser_exec]
---

# Nexus-Harness UI surgeon

Use when the cockpit (`/` chat, `/settings` manual, `/gov` governance — served by `ui.py`) has to be
fixed **or designed**. A UI change here is only done when a real browser returned the numbers and the
result reads like the written direction in `docs/DESIGN.md`.

## The only thing that separates a designed UI from slop

Every model was trained on the same corpus (shadcn, Tailwind, Vercel templates), so the default output
is the corpus average: dark mode, one blue accent, rounded cards, a sidebar. Switching model does not
change that — the variance is between *accepting the default* and *constraining it with a written
design system*. So this skill starts from `references/document-direction.md`, not from a screenshot.

Paletas y temas (los seis pantones, contraste WCAG, `§ Apariencia`): skill
`nexus-visual-identity`, que viaja en `nexus_harness/skills/`. Esta se ocupa de la ESTRUCTURA.

North star: **«Cuaderno de taller»** — the cockpit is a printed technical document. Folios, index,
1px rules, tabular figures, stamps for verdicts. No cards, no blue, no pills, no shadows.

## Protocol

1. **Read the direction** (`references/document-direction.md`) and the anti-slop table
   (`references/anti-slop.md`). If a screen cannot honour it, the direction wins or the direction is
   amended in `docs/DESIGN.md` — never silently broken.
2. **Measure three versions, not two.** Serve the starting commit and the previous delivery in
   worktrees on other ports, the new one on `:8799`, and run the SAME probe on all three: filled
   boxes, `border-radius > 2px` outside form fields, `box-shadow`, elements using the corpus blue,
   pills (`radius >= 100px`), emoji in `document.body`, `main + index === body`.
3. **Design in the tokens, not in the screen.** `web/tokens.css` owns the palette, the three type
   families and the rule thickness; screens only compose. A literal colour outside tokens is a bug
   (except inside `/gov`, a foreign document — see below).
4. **Compose**: masthead | index | document. Every message gets a folio; every figure is mono; every
   verdict carries its word. The composer is a ruled form line, not a box.
5. **Prove it**: screenshots of every screen before/after, side-by-side diff, and the numbers in
   `docs/UI_REWORK.md`.

## Laws of this cockpit

- **The token travels everywhere.** Every internal link and every `303 Location` carries `?token=`;
  pages expose it in `<meta name="nexus-token">`; `token.js` resolves URL → meta → `sessionStorage`
  and stamps internal links. Forms use the `nexus_token` cookie (a form cannot set a header).
- **One unit, one place.** Percent fields show `round(fraction*100)`; the config stores the fraction;
  `settings_kit.percent_to_fraction` normalises on save and rejects `>100 %`. Never multiply a value
  that may already be scaled (that was the `7000 %`).
- **Four tones, one meaning.** green = a decision was taken · amber = a human is awaited **or the
  verdict is not verifiable (gate exit 20/30)** · red = caught/broken · grey = no record. Colour never
  appears without its word: `mark`/`chip` carry text, not just a dot.
- **`/gov` is a foreign document.** Its HTML is the protocol's, with the protocol's `--accent` (blue).
  Harness cards injected there must use **literal** palette values, not `var(--accent)`.
- **400 lines is the law for .js/.css too.** Split by name before editing; never tighten comments.

## Verification (nothing is done without an exit code)

```bash
NEXUS_PROTOCOL='C:\Proyectos\NexusProtocol' python tools/verify.py   # exit 0
NEXUS_PROTOCOL=/nonexistent python tools/verify.py                   # exit 0, skipped=2
```

Plus: 0 filled boxes / 0 radius>2 / 0 shadows / 0 corpus-blue / 0 pills / 0 emoji on the two own
screens; `relay_threshold: 0.7` after saving 70 %; the 303 `Location` with the token; the 13 settings
destinations 200 with their own `h1`; and the before/after pair in `docs/ui/`.

## Pitfalls already paid for

- **A new `/settings` section is registered in several places and every miss is SILENT.** `SECTIONS` +
  `GROUPS` + `SEARCH_TERMS` in `settings_index.py`, the dispatch in `settings._render`, and the action
  branch in `settings_actions.py`. A name absent from `SECTIONS` is resolved to `modelos`; a name absent
  from `_render` falls through to `stats`. Both answer **200** with somebody else's `h1`, so only a
  check of the served title catches it. The index count the backlog quotes (`13 destinos`) is stale by
  construction: measure it (`len(destinations())`, or count `.settings-tree a` in the browser) instead
  of trusting the number in the task text.

- **A hidden banner swallows a grid row.** `body{display:grid; rows:auto auto 1fr}` with a `hidden`
  `#warn` leaves `.app` in row 2 and the page half-empty. Use `display:flex; height:100dvh` and
  `.app{flex:1 1 auto; min-height:0}`.
- **`hidden` loses against `button{display:inline-flex}`** — add `[hidden]{display:none!important}`.
- **The icon stroke must live in CSS** (`.icon{fill:none;stroke:currentColor;stroke-width:1.5}`):
  hand-written `<svg>` in the HTML has no inline style and inherits `fill:black` (a black blob).
- **A width rule for form fields turns a checkbox into a 26rem box** and pushes its label away:
  exclude `input[type=checkbox]`.
- **`fetch(…,{redirect:'manual'})` returns `opaqueredirect` without `Location`** — read the 303 with a
  non-following client.
- **A local variable can shadow a helper** (`verdict_word = …` inside `summary()` hid the function).
- **Selftests sometimes pin an emoji literal**: change the glyph, keep the assertion's meaning, say so
  in the commit.
- **To time a poll-driven banner, instrument `window.fetch`, not the DOM.** Wrap `fetch` pushing
  `[Date.now(), ok|http<code>|net, url]`, then derive the interval from the TAGS: «last `/api/state` ok
  → third failure» (7.50 s with a 2.5 s cadence). The visible `#warn` proves nothing about *when* it
  appeared: `js()` round-trips cost ~200 ms each and a same-call `reset → click → read` can read before
  the reset lands, so a `.click()` looks dead when it is not. Re-measure with a timestamp filter
  (`e[0] >= t0`) in a separate call.
- **The UI and the API are the same process.** «Engine off» = kill the served process (`process_manage
  kill`), never a second port; the already-loaded page keeps polling and must recover when it is
  relaunched on the SAME port.
- **`boot()` dies where the first `fetch` rejects.** Any `await api(...)` in the boot path (`checkEngine`)
  must catch: with `fetch` rejected the function threw, `boot` aborted, the intervals never started and
  no banner could ever appear. Reachable — prove it by blocking `*/api/health*` with
  `cdp('Network.setBlockedURLs')` and reloading (the rest of the page must still paint).
