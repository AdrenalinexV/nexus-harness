# Nexus-Harness, explicado para personas normales

> Congelado en `5e83a9a`: las cifras de este documento retratan ese árbol, no el de hoy.

*Qué es, por qué existe, en qué se diferencia y qué le falta. Escrito para quien no programa.*

---

## 1. La frase de una línea

**Nexus-Harness es un programa que hace que una inteligencia artificial trabaje como un empleado con
supervisor: no puede decir "ya está" si un inspector no firma que está.**

Todo lo demás de este documento es consecuencia de esa frase.

---

## 2. El problema que resuelve (y que casi nadie resuelve)

Las inteligencias artificiales actuales son muy buenas escribiendo cosas. El problema es otro:

> **No sabes cuándo mienten sin querer.** Dicen "he terminado, funciona" y no has visto nada.

Es el mismo problema que tendrías con un fontanero que te llama por teléfono y te dice "la fuga está
arreglada, no hace falta que vengas a mirar". A veces es verdad. A veces vuelve el agua a los dos días y
ya ha cobrado.

Hoy existe una categoría de programas, los **"agentes de programación"** (Claude Code, Aider, Codex,
OpenCode, Devin, OpenHands…), que hacen que la IA *toque* los archivos de un proyecto en vez de solo
charlar. Son potentísimos. Pero casi todos comparten el mismo punto débil: **el final del trabajo es una
opinión del propio interesado.**

Nexus-Harness ataca exactamente eso.

---

## 3. Cómo funciona, con una analogía

Imagina una obra pequeña y cuatro figuras:

| En la obra | En Nexus-Harness | Qué hace |
|---|---|---|
| **El jefe de obra** | el *Director* | Lee el encargo, lo convierte en un plan de pasos y reparte el trabajo. |
| **El albañil** | el *Obrero* | Es el que pone ladrillos: escribe y modifica los archivos de verdad. |
| **El inspector de obra** | el *Gate* | Programa automático, sin IA, sin opinión. Mide: ¿el proyecto compila?, ¿las pruebas pasan?, ¿se respetó el límite de tamaño de archivo? |
| **El aparejador** | el *Juez* | Una **segunda** IA, distinta de la que hizo el trabajo, que responde una sola pregunta: *¿esto que se ha hecho responde al encargo?* |

Y la regla que lo cambia todo:

> **Si el inspector no firma, el albañil vuelve a trabajar. Y si al final no hay firma, el trabajo no se
> da por bueno: se para y se dice por qué.**

El *Gate* no es una IA opinando. Es una **medición**. Devuelve un número: `0` = verde, `10` = rojo,
`20` = no se pudo medir. Ese número queda escrito como recibo del turno.

En la analogía: el inspector no "cree" que la pared está recta. Pone el nivel.

---

## 4. Sus cualidades, una por una

### 4.1 El trabajo no se cierra con palabras, se cierra con un recibo
Cada turno deja una línea en un libro (`ledger.jsonl`): qué se intentó, qué herramientas se usaron,
qué costó, y **el código de salida de cada comprobación**. Es la diferencia entre "me dijo que está
bien" y "aquí está el papel firmado".

### 4.2 Dos inteligencias que no se creen la una a la otra
El que trabaja y el que juzga **son modelos distintos a propósito**. Un modelo tiende a aprobar lo que
él mismo acaba de escribir. Separarlos es lo que evita el "aprobado por el propio alumno".

### 4.3 Si no hay copia de seguridad, no se toca nada
Antes de empezar un ciclo de trabajo automático, el programa guarda una foto del proyecto (una etiqueta
de Git o un zip). **Si no puede guardarla, no edita.** El orden es sagrado: copia → plan → trabajar →
verificar → guardar avance. Nunca al revés.

### 4.4 Tiene memoria, y la memoria se paga
Las IAs tienen un límite de "cuánto texto pueden mirar a la vez" (como una mesa de trabajo: cabe lo que
cabe). Nexus mide ese espacio, lo administra, y cuando la sesión se llena **se pasa el relevo a una
sesión limpia** sin perder lo esencial. No se reinicia: se releva, como en una carrera.

### 4.5 Sabe cuánto cuesta, antes y después
Cada llamada tiene un precio. El programa calcula el gasto por turno y puede poner un techo. Además
lleva una contabilidad de *cuánto se ha ahorrado* al no reenviar contexto innecesario.

### 4.6 Cabe en tu ordenador, con tus modelos, sin nube obligatoria
Funciona con modelos locales (LM Studio, Ollama) y con seis proveedores en la nube. Cambiar de
proveedor es cambiar una línea de configuración. **No hay secuestro de proveedor.**

### 4.7 Se instala como una app normal
Hay un instalador de Windows de ~20 MB. El motor va dentro, congelado: **el ordenador de destino no
necesita tener Python instalado ni saber qué es Python.**

### 4.8 Cero dependencias externas
No usa librerías de terceros. Suena a detalle técnico; en la práctica significa que **no se rompe porque
otro cambió su pieza**, no arrastra virus de paquetes, y se puede leer entero.

### 4.9 Trabaja de noche
Tiene un modo autónomo: dejas tareas en una bandeja, y un demonio las coge, las convierte en criterios
comprobables, trabaja, verifica y avisa por Discord/Telegram/notificación al móvil. Se puede parar con
un botón y se para solo por criterios, no por reloj.

### 4.10 Rechaza órdenes peligrosas por diseño
Hay una lista de comandos que se niega a ejecutar (borrados masivos, formateos, escrituras fuera del
proyecto). Y "rechaza" no es un aviso en un diálogo: es una puerta que no abre.

---

## 5. En qué se diferencia de lo que hay

Comparación honesta, sin marketing. La columna de la competencia resume su diseño público; la nuestra,
lo que este repositorio mide con sus propios comandos.

| | Herramientas típicas (Aider, Claude Code, Codex, Devin, OpenHands) | Nexus-Harness |
|---|---|---|
| **Cómo termina un trabajo** | El agente declara que ha terminado | Un programa mide y devuelve `exit 0`; sin eso no hay final |
| **Quién juzga** | El mismo modelo que trabajó | Un segundo modelo distinto, obligado a un veredicto corto |
| **Prueba del resultado** | Hay que creérselo o leer el chat | Queda un recibo por turno, con códigos |
| **Antes de editar** | Normalmente no hay red | Sin copia de seguridad no se edita |
| **Límite de tamaño de archivo** | Ninguno | 400 líneas, impuesto por la herramienta de escritura (hoy: 0 infracciones en 167 archivos) |
| **Después de un fallo** | Reintenta y espera que salga | Reintenta en un entorno aparte y solo lo incorpora si queda verde |
| **Sesión llena** | Se pierde contexto o se resume "a ojo" | Relevo automático a sesión limpia con estado verificado |
| **Modelos** | Suele empujar a su nube | Locales primero, seis proveedores, cambiar es config |
| **Dependencias** | Muchas | Ninguna |
| **Coste** | Estimado | Medido y con techo |

**La diferencia que más importa, dicha de forma llana:** las demás herramientas son *empleados muy
listos*. Esta es un *empleado muy listo con un inspector que no cobra de la obra*.

### Y lo que la competencia hace mejor (honestidad)
- **Aislamiento real del proceso.** Ellos encierran el trabajo en contenedores. Aquí todavía no: un
  comando malicioso dentro de una política abierta sería el agujero más grande. Está identificado.
- **Asistentes de código (LSP).** Ellos entienden el proyecto como un IDE. Aquí se usa un mapa del
  código, más simple.
- **Ecosistema y comunidad.** Ellos tienen miles de usuarios probándolos a diario. Esto es un trabajo
  serio, pero de un solo autor y un solo ordenador.
- **Volumen de pruebas de calidad.** Aquí hay 7 tareas de referencia ejecutadas de verdad. Para comparar
  modelos en serio harían falta unas 20 con dificultad graduada.

---

## 6. Qué NO es

- **No es un chat.** Hay chat, pero el chat es la puerta de entrada, no el producto.
- **No es "IA que programa sola y tú te vas".** Es IA que trabaja y **rinde cuentas**. Tú sigues siendo
  quien decide qué se encarga.
- **No es perfecto.** Los límites del apartado anterior son reales y están escritos en su propia
  documentación. Eso, en este sector, ya es raro.

---

## 7. Los números de hoy (medidos, no estimados)

Ejecutado en esta máquina el 2026-10-28 con `python tools/verify.py`:

```
lint      exit 0   files=167  findings=0   max_lines=400
selftest  exit 0   suites=48  failures=0
verify: GREEN
```

| Dato | Valor |
|---|---|
| Archivos de código | 152 en Python |
| Líneas totales | ~27.500 |
| Media por archivo | ~180 líneas |
| Archivo más largo | 399 líneas (el techo es 400) |
| Infracciones de estilo | **0** |
| Pruebas automáticas | 48 suites, 0 fallos |
| Dependencias de terceros | **0** |
| Proveedores de IA soportados | 6 |
| Herramientas que la IA puede usar | 16 |
| Instalador | `NexusHarness-Setup-1.0.0.exe` (~20 MB) |
| Versión | 1.0.0 |

Ese `verify: GREEN` es, literalmente, la prueba. No es una captura de pantalla: es lo que devolvió el
comando.

---

## 8. Las cuatro formas de usarlo

1. **Ventana de escritorio** — se instala como cualquier programa. Doble clic.
2. **Cabina en el navegador** (`http://127.0.0.1:8765`) — se ve el plan, cada herramienta que se usa,
   la barra de presupuesto y el veredicto del juez, en vivo.
3. **Terminal** — para quien le guste: `run`, `chat`, `gate`, `daemon`.
4. **Desde el móvil** — se deja una tarea en una cola y el motor en casa la ejecuta.

---

## 9. Lo que le falta (auditoría interna, sin adornos)

Ordenado por lo que más duele:

1. **Aislamiento del proceso.** El árbol de trabajo está aislado; el proceso, no. Es el pendiente #1.
2. **Documentos desfasados.** El README dice "28 suites" cuando hay 48. La arquitectura dice 161
   archivos cuando hay 152. Nada roto, pero en un proyecto cuya bandera es "lo que no se mide no se
   afirma", un número viejo en la portada es la peor carta de presentación.
3. **Sin licencia.** Dice ser open source y no hay fichero `LICENSE`. Legalmente, sin licencia, nadie
   puede usarlo con seguridad.
4. **Sin integración continua.** El "verde" se comprueba en este ordenador, a mano. Si mañana se rompe,
   nadie se entera hasta que se ejecute.
5. **Cuatro módulos al borde del techo** (399, 397, 395 líneas). El techo de 400 es una virtud, pero
   tocarlo con los dedos significa que la próxima función lo rompe. Toca dividir por responsabilidad.
6. **Sin historial de versiones** (CHANGELOG). Hay seis instaladores y ninguna lista de qué cambió.
7. **Restos de sesión en la raíz** (`MORNING_REPORT.md`, `NIGHT_REPORT.md`, logs vacíos). Ruido de
   trabajo mezclado con el producto.

---

## 10. Tres ideas que aportarían de verdad

1. **El recibo visible.** Hoy el recibo existe pero es un archivo de texto técnico. Convertirlo en una
   página legible (o un PDF de una hoja) — *esto se hizo, con este resultado, estas comprobaciones,
   este coste* — sería la mejor demostración del producto para alguien que no programa. Enseñar el
   recibo vende más que cualquier explicación.
2. **Un botón "demuéstramelo".** Un proyecto de ejemplo incluido en el instalador que se rompe a
   propósito y se arregla delante del usuario. La diferencia se entiende en 90 segundos, no en 20
   párrafos.
3. **Publicar los números que ya tiene.** Ese `findings=0` en 167 archivos y 48 suites en verde es
   exactamente lo que un programador busca antes de confiar en una herramienta. Está calculado y no se
   está usando como argumento.

---

*Documento generado el 2026-10-28. Todas las cifras de la sección 7 provienen de la ejecución de
`python tools/verify.py` en esta máquina, cuyo resultado se archiva solo en `docs/VERIFICATION.md`.*
