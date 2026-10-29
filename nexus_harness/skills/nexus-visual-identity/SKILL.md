---
name: nexus-visual-identity
description: "Design palettes and themes for the Nexus cockpit."
license: MIT
keywords: "diseño paleta pantón tema color contraste neón cyberpunk retro fósforo synthwave riso"

compatibility: hermes, claude-code, agents, codex
version: 1.0.0
author: Nexus Harness
metadata:
  nexus:
    specialty: design
    globs:
      - "nexus_harness/web/*.css"
      - "nexus_harness/ui_theme.py"
      - "nexus_harness/settings_theme.py"
      - "docs/DESIGN.md"
  hermes:
    tags: [design, palettes, themes, contrast, ui]
    related_skills: [nexus-ui-surgeon, nexus-ui-taste]
allowed-tools: [read_file, write_file, patch, terminal, search_files, browser_exec]
---

# Nexus visual identity

Use when the cockpit needs a **new colour** — a palette, a "pantón" — without redrawing the product.
For a different **composition** (type, density, message shape) the skill is `nexus-layout-skins`:
colour and layout are two independent axes (4 skins × 6 pantones = 24 combinations). The structure (masthead, index, folios, 1px rules, four tones) is law; what you change is the
dressing: colour, texture, glow. Six themes already ship; a seventh is a token set, not a stylesheet.

## Method (in this order)

1. **Name the quotation.** Every palette quotes a medium: a CRT, a print shop, a 1984 arcade, a lab
   notebook. If you cannot say what it quotes in one sentence, it is decoration, not an identity.
2. **Pick three colours, not ten.** Paper, ink, and one voltage (a *seal*). A neon theme may add a
   second hue as `--signal` for sigils only — that is the single declared exception to "one accent".
3. **Keep the four state tones.** Green/amber/red/grey keep their meaning in every theme; you may
   desaturate them, never re-purpose them.
4. **Measure contrast before it ships.** `ink/paper >= 7:1`, `ink-2/paper >= 4.5:1`, and
   `seal`, `ok`, `warn`, `bad` on paper `>= 3:1` — computed, not eyeballed (`ui_theme.ratio`).
   A pretty palette that cannot be read is a defect.
5. **Write the theme in two places, with one source:** `nexus_harness/ui_theme.py` (metadata +
   `TOKENS`, used by the picker and the contrast test) and `web/themes.css`
   (`[data-theme="key"] { --paper: … }`). The test fails if one of them lacks the other.
6. **Show it on both screens.** Screenshot the chat and the settings manual; a palette that works on a
   list but not on a form is half a palette.
7. **Ship the picker.** Themes are chosen in `§ Apariencia` (`settings_theme.py`), which posts
   `ui_theme` to `/api/settings` and gets a 303 back. Never a client-side toggle that forgets.

## The six that ship (pairs: paper / ink / seal)

| key | name | quotation | tokens |
|---|---|---|---|
| `neon` | Neón nocturno | cyberpunk retro: violeta-negro, magenta y cian | `#07060e` / `#eaf6ff` / `#ff2e88` (+ cyan `#22d3ee`) |
| `crt` | Fósforo | terminal CRT verde con líneas de barrido | `#050a06` / `#b8ffcb` / `#ffb000` |
| `synth` | Synthwave | SynthWave '84: ciruela, magenta y cian | `#1a0b2e` / `#f7edff` / `#ff3ea5` (+ `#21d4fd`) |
| `amber` | Ámbar | monocromo de fósforo ámbar | `#0b0805` / `#ffd7a3` / `#ff9a1f` |
| `riso` | Risográfica | papel crema y duotono de imprenta | `#f3efe4` / `#1b1913` / `#d93a10` (+ `#2b4bff`) |
| `paper` | Cuaderno | papel cálido y bermellón | `#f4f1ea` / `#191713` / `#b8431f` |

Numbers, hues and the reasoning behind each: `references/palettes.md`. How a theme is wired into the
server, the picker and the tests: `references/theme-system.md`.

## Anti-patterns of the neon genre (what makes it look cheap)

- **Pure black `#000` and pure cyan `#0ff` text.** Neon reads better on a tinted near-black
  (`#07060e`) with a slightly warm white ink; pure cyan vibrates and kills legibility.
- **Glow on everything.** One glow per screen, on the seal (primary action or the active item).
- **Scanlines over text.** If the theme has them, they are a full-viewport overlay at low opacity with
  `pointer-events: none`, never a background-image on the text container.
- **A fifth state colour.** Pink for "running", cyan for "queued"? No: those are not decisions.
- **Changing the composition with the palette.** No theme moves the masthead, the folios or the rules.

## Verification

```bash
python -c "import sys;sys.path.insert(0,'.');from nexus_harness.selftests import run;print(run(['themes']))"
NEXUS_PROTOCOL='C:\Proyectos\NexusProtocol' python tools/verify.py    # exit 0
```

Plus, in a real browser: switch to each theme in `§ Apariencia`, reload, and confirm the theme comes
back from `harness.json` (fresh, no flash), and 0 emojis / 0 pills / 0 shadows outside the declared
theme glow.
