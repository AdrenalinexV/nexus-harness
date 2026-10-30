# Hooks — los cuatro puntos donde el motor deja de ser un producto cerrado

> Un hook es **un programa tuyo** que el motor llama en un momento concreto. No hay lenguaje de plugins,
> no hay SDK que aprender y no hay versión de API que se rompa: hay un proceso, un JSON de entrada, una
> línea de salida y un código de salida. Es el mismo contrato que el gate ya usa para todo lo demás, a
> propósito: **un solo vocabulario**.

## Declararlos

En la raíz del proyecto que el motor trabaja, un `nexus_harness.toml`:

```toml
[[hook]]
at = "pre_verify"                        # before_turn | after_tool | before_commit | pre_verify
command = 'python tools/hooks/no_todo.py'
name = "sin-deuda"                       # opcional: así se llama en el informe
```

Varios hooks en el mismo punto se ejecutan **en el orden en que se declaran**. `command` se ejecuta con
`shell=True` y con el `cwd` del proyecto — el mismo modelo de confianza que el `test_command` del gate, el
de `Makefile` o el de `pre-commit`: el texto lo escribe quien declara el hook en su rama, no llega por una
petición.

## El contrato

**Entrada** (stdin, un JSON):

```json
{"point": "after_tool", "project": "/ruta/al/proyecto", "payload": {"tool": "edit", "ok": true, "files": ["a.py"]}}
```

**Salida**: la **última línea no vacía** de stdout es el mensaje que se enseña (máx. 400 caracteres). Lo
demás se ignora, así que un hook puede loguear lo que quiera.

**Código de salida** — no hay más:

| código | significado | qué hace el motor |
|---|---|---|
| **0** | pasó | sigue |
| **10** | rojo | **para**: el gate sale rojo, el turno se aborta, el commit no se hace |
| **20** | no se pudo medir | **para** igual (fail-closed): un hook roto no es un hook que aprueba |
| **30** | declarado no aplicable | se anota y **no** para |

Cualquier otro código se lee como **20**: un número que el contrato no define no puede aprobar nada.

## Los cuatro puntos

| punto | dónde corre | qué lleva en `payload` |
|---|---|---|
| `before_turn` | al empezar el turno, **antes** de gastar un token | `max_steps`, `at` |
| `after_tool` | tras cada herramienta ejecutada | `tool`, `ok`, `files`, `at` |
| `before_commit` | antes de `git commit` del paso | `message`, `at` |
| `pre_verify` | al principio del gate, antes del lint | `touched`, `at` |

## Fail-closed, y lo que eso significa aquí

- **Sin `nexus_harness.toml` no hay hooks y no cambia nada**: el motor es inerte. Ausencia de
  configuración no es una configuración vacía.
- **Un `toml` que existe y no se puede leer no se ignora.** Cada punto devuelve 20 con el motivo: un motor
  que se salta su configuración rota es peor que uno que no la tiene.
- **Un `at` inventado, un `command` vacío o un hook que no termina** (timeout de 60 s por defecto) son 20,
  nunca un verde silencioso.

## Ejemplo mínimo, ejecutable

`tools/hooks/no_todo.py` de este repo: falla si los ficheros que el turno tocó dejan un `TODO:`/`FIXME:`.

```
[[hook]]
at = "pre_verify"
command = 'python tools/hooks/no_todo.py'
```

## Qué NO hace (y por qué)

- **No aísla el código del hook.** Un hook corre con tus permisos, como tu `Makefile`. El sandbox de
  proceso es otro trabajo (backlog, brecha D), y fingir aislamiento aquí sería peor que no tenerlo.
- **No hay hooks asíncronos ni eventos de red.** Un punto, un proceso, un veredicto. Si necesitas algo
  más grande, tu hook puede hablar con lo que quiera por su cuenta.
- **No se ejecutan hooks de terceros automáticamente.** El `nexus_harness.toml` es del proyecto en el que
  trabajas, no un registro global del que alguien pueda colarte un comando.

## Verificación

`python -m nexus_harness selftest hooks` mide la matriz entera: inerte sin fichero, 0/10/20/30, código
fuera de contrato, timeout, `toml` roto, `at` inventado, los cuatro puntos, el gate obedeciendo
(`10 → exit 10`, `0 → exit 0`, `30 → no cambia el veredicto`) y un `before_commit` que **impide un commit
de verdad** en un repo temporal.
