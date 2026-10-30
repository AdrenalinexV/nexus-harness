# Entrega nocturna — estado y cómo retomarlo

Escrito al cerrar la sesión del 2026-10-30 antes de dejar el bucle trabajando.

## Qué hay ahora (verificado)

| pieza | estado | cómo se comprueba |
|---|---|---|
| Cuatro ejes de aspecto: papel (`ui_mode`), composición (`ui_skin`), color (`ui_theme`), voz (`ui_font`) | listo | `python -c "…ui_theme…"` → `2 5 6 4` |
| 5 diseños: `main`, `editorial` (cinta + columna centrada, Sitka), `terminal`, `matrix`, `glossy` | listo | `run(['themes'])` OK |
| 12 juegos de color (6 pantones × 2 modos) con contraste WCAG medido | listo | `run(['themes'])` → `12/12` |
| `web/themes.css` generado desde `ui_theme.tokens` | listo | `python tools/gen_themes.py --check` |
| Tipografía con familias reales primero (Segoe UI Variable, Sitka, Palatino, Consolas) | listo | `run(['themes'])` → `test_stacks_name_a_real_family_first` |
| Responsive ≤900 px (índice como cinta superior) | listo | navegador 800×700 → una columna, sin scroll lateral |
| El hilo no se repinta si nada cambia (conserva selección y scroll) | listo | selección intacta tras 3,2 s |
| Sondeo pausado con la pestaña oculta | listo | `document.hidden` en `/api/state`, `/api/chat`, `/api/activity` |
| Copiar mensaje (con caída a `execCommand`) | listo | clic real → `copiado` |
| Hoja de atajos con `?` | listo | tecla real → `dialog[open]`, Esc cierra |
| Accesibilidad: salto al hilo, `prefers-reduced-motion`, `role=status`, favicon inline, `color-scheme` | listo | CSS + HTML servido |
| `verify.py` | verde, `suites=54` | `NEXUS_PROTOCOL=… python tools/verify.py` |

## Qué queda en la cola (la consume el bucle)

`docs/UI_BACKLOG.md`, una tarea por pasada, con aceptación y comando:

- **U-02** banda de reintento cuando el motor no responde (3 fallos).
- **U-03** exportar el hilo a Markdown (Blob, sin servidor).
- **U-04** sección `§11 Acerca de` (versión, api, host, raíz, uptime, botón de salud).
- **U-06** densidad (`ui_density`: normal / compacta).
- **U-07** teclado en el índice (`role=option`, flechas, Enter).
- **U-08** copiar bloques de código (`pre` con `tab-size` y botón).
- **U-09** `docs/UI_GUIDE.md` (uso de los ejes, atajos, accesibilidad).
- **U-10** revisar estados vacíos de los paneles de configuración.

## El bucle

- Trabajo de Hermes `cabina-autonoma` (`job_id 9c489bc9a5a3`), **cada 45 min**, `workdir` el repo,
  `continuity` activo (cada pasada ve el resultado de la anterior), entrega en esta conversación.
- Cada pasada: árbol limpio → primera tarea → implementar → `verify.py` → commit + push → marcar `[x]`
  con el hash. Si falla: `git checkout -- .`, marcar BLOQUEADA y terminar sin tocar nada más.
- Pararlo: pedir «pausa el job cabina-autonoma» (o `cronjob_manage pause 9c489bc9a5a3`).
- Revisarlo: `git log --oneline -20` y el propio backlog (las `[x]` llevan hash).

## Lo que el bucle NO va a hacer

- Empaquetar una tipografía con licencia (implica binarios en el repo): decisión humana.
- Tocar `/gov` más allá de lo inyectado: es HTML del protocolo.
- Traducir la cabina: hay `lang` en config, pero es un trabajo aparte.

## Backups

- `backup-pre-autonomous` (antes de esta tanda), `ui-backup-2026-10-30`.
- `~/AppData/Local/hermes/profiles/nexus-harness/cache/scratch/backups/nexus-harness-ui-2026-10-30.zip`
  (web + docs). El historial de git es el backup real: cada commit es reversible.
