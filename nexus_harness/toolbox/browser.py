"""Navegador nativo: llegar donde `fetch_url` no llega, sin quemar contexto.

La diferencia con un `curl`:

* **Hay un navegador de verdad** (Edge/Chrome instalado, o Chromium de Playwright): ejecuta JavaScript,
  guarda cookies y ve lo que veria un usuario. `fetch_url` se queda en el HTML del servidor.
* **Perfil persistente**: `.nexus/browser/profile` conserva la sesion, asi que una web con login se abre
  una vez y sigue abierta en el siguiente turno.
* **DOM -> texto, no screenshots**: se extrae el texto visible y los enlaces, que es lo que el modelo
  necesita. Una captura cuesta ~0,8 s de codificacion y solo muestra lo que cabe en pantalla.
* **Contexto con recibo**: el texto se recorta a `max_chars` y se dice cuanto se dejo fuera.
* **Bloqueo declarado**: un 403/429 o un "Just a moment" devuelve error con el motivo, no un texto de
  12 caracteres que parece una respuesta.

**El navegador vive en su propio hilo.** Playwright sincrono se niega a arrancar dentro de un bucle de
asyncio, y el arnes corre dentro de uno. Un worker por raiz resuelve las dos cosas: la sesion persiste
entre llamadas y el llamante no necesita saber nada de asyncio.

Playwright se importa de forma dinamica: el motor congelado no lo lleva dentro (pesa centenares de MB) y
una herramienta ausente debe declararse, no romper el binario.
"""
import importlib
import queue
import threading
from pathlib import Path

MAX_CHARS = 12000
HARD_CAP = 40000
LINKS = 40
COMMAND_TIMEOUT = 120
BLOCK_MARKERS = ("just a moment", "attention required", "checking your browser", "captcha",
                 "access denied", "enable javascript and cookies", "cf-chl", "are you a robot")
_WORKERS = {}


class BrowserError(RuntimeError):
    """El navegador no esta disponible o la accion no se pudo completar."""


def _engine():
    """El modulo de Playwright, o una excepcion que dice como arreglarlo."""
    try:
        return importlib.import_module("playwright.sync_api")
    except Exception as exc:  # noqa: BLE001 -- sin playwright hay `fetch_url`, y se dice
        raise BrowserError("playwright no esta instalado (%s). Instala un motor: Edge/Chrome del "
                           "sistema o `playwright install chromium`." % type(exc).__name__)


def _channels():
    import os
    preferred = os.environ.get("NEXUS_BROWSER_CHANNEL") or ""
    order = [preferred] if preferred else []
    return [name for name in order + ["msedge", "chrome", None] if name != ""]


def _user_agent():
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0")


def _clean(text):
    """Espacios colapsados y lineas vacias fuera: el DOM trae ruido y todo se paga en tokens."""
    lines = [" ".join(row.split()) for row in str(text or "").splitlines()]
    return "\n".join(row for row in lines if row)


def _truncate(text, cap):
    body = str(text or "")
    if len(body) <= cap:
        return body, False
    return body[:cap] + "\n[...recortado: %d chars de %d. Afina con extract o pide otro rango]" % (
        len(body) - cap, len(body)), True


def _blocked(status, text):
    """Un muro anti-bot se declara: devolver su texto como si fuera la pagina es peor que fallar."""
    body = str(text or "").lower()
    if status and int(status) in (401, 403, 429, 503):
        return "http %s" % status
    for marker in BLOCK_MARKERS:
        if marker in body:
            return "muro anti-bot (%r)" % marker
    return ""


def _links(page, limit=LINKS):
    try:
        rows = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => [e.innerText || '', e.href]).slice(0, %d)" % limit)
    except Exception:  # noqa: BLE001 -- sin enlaces queda el texto, que es lo importante
        return []
    return [{"text": " ".join(str(row[0]).split())[:80], "href": str(row[1])}
            for row in rows if str(row[1]).startswith("http")]


def _text(page):
    try:
        return _clean(page.inner_text("body"))
    except Exception:  # noqa: BLE001 -- una pagina sin body (pdf, imagen) no es texto
        return ""


def _link_block(page):
    rows = _links(page)
    if not rows:
        return ""
    lines = ["", "## Enlaces"]
    lines.extend("- [%s](%s)" % (row["text"] or row["href"], row["href"]) for row in rows[:15])
    return "\n".join(lines)


class _Worker(threading.Thread):
    """Dueño del navegador: arranca Playwright en SU hilo y ejecuta comandos de uno en uno."""

    def __init__(self, root, headless=True):
        super().__init__(name="nexus-browser", daemon=True)
        self.root = Path(root)
        self.headless = bool(headless)
        self.commands = queue.Queue()
        self.ready = threading.Event()
        self.failure = None
        self.browser = None
        self.playwright = None
        self.page = None

    def run(self):
        try:
            self._start()
        except Exception as exc:  # noqa: BLE001 -- el fallo se entrega a quien pregunte
            self.failure = exc
            self.ready.set()
            return
        self.ready.set()
        while True:
            item = self.commands.get()
            if item is None:
                break
            action, args, box, done = item
            try:
                box["value"] = self._dispatch(action, args)
            except Exception as exc:  # noqa: BLE001 -- se devuelve al llamante
                box["error"] = exc
            done.set()
        self._stop()

    def _start(self):
        sync = _engine()
        self.playwright = sync.sync_playwright().start()
        problems = []
        for channel in _channels():
            try:
                self.browser = (self.playwright.chromium.launch(headless=self.headless,
                                                                channel=channel)
                                if channel else
                                self.playwright.chromium.launch(headless=self.headless))
                break
            except Exception as exc:  # noqa: BLE001 -- siguiente motor
                problems.append("%s: %s" % (channel or "chromium", str(exc)[:100]))
        if self.browser is None:
            self.playwright.stop()
            raise BrowserError("ningun motor de navegador arranco (%s)" % " | ".join(problems))
        context = self.browser.new_context(user_agent=_user_agent(), locale="es-ES",
                                           viewport={"width": 1366, "height": 900})
        self.page = context.new_page()
        self.page.set_default_timeout(20000)

    def _stop(self):
        for closer in (getattr(self.page, "close", None), getattr(self.browser, "close", None),
                       getattr(self.playwright, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:  # noqa: BLE001 -- cerrar nunca lanza hacia el turno
                continue

    def submit(self, action, args):
        if not self.ready.wait(45):
            raise BrowserError("el navegador no arranco en 45 s")
        if self.failure is not None:
            raise self.failure
        box, done = {}, threading.Event()
        self.commands.put((action, dict(args or {}), box, done))
        if not done.wait(COMMAND_TIMEOUT):
            raise BrowserError("el navegador no respondio en %s s (%s)" % (COMMAND_TIMEOUT, action))
        if "error" in box:
            raise box["error"]
        return box["value"]

    def stop(self):
        self.commands.put(None)
        self.join(10)

    def _dispatch(self, action, args):
        page = self.page
        cap = max(500, min(HARD_CAP, int(args.get("max_chars") or MAX_CHARS)))
        if action in ("goto", "open"):
            url = str(args.get("url") or "").strip()
            if not url:
                raise ValueError("goto necesita `url`")
            response = page.goto(url, wait_until="domcontentloaded")
            status = getattr(response, "status", None)
            text = _text(page)
            wall = _blocked(status, text)
            if wall:
                raise ValueError("%s: la pagina no se puede leer (%s). Prueba otra url, el perfil "
                                 "persistente o `fetch_url`." % (wall, page.url))
            body, cut = _truncate(text, cap)
            title = page.title()
            head = "# %s\n%s\nhttp %s\n" % (title or "(sin titulo)", page.url, status)
            return head + body + _link_block(page), {
                "files": [], "url": page.url, "title": title, "status": status,
                "chars": len(text), "truncated": cut, "blocked": "", "links": _links(page)[:10]}
        if action == "extract":
            needle = str(args.get("text") or "").strip().lower()
            text = _text(page)
            if not needle:
                body, cut = _truncate(text, cap)
                return body, {"files": [], "chars": len(text), "truncated": cut}
            keep = [line for line in text.splitlines() if needle in line.lower()]
            if not keep:
                return ("no hay lineas con %r (la pagina tiene %d chars; usa `goto` para verla)"
                        % (needle, len(text))), {"files": [], "matches": 0}
            body, cut = _truncate("\n".join(keep), cap)
            return body, {"files": [], "matches": len(keep), "chars": len(text), "truncated": cut}
        if action == "click":
            selector = str(args.get("selector") or "").strip()
            if not selector:
                raise ValueError("click necesita `selector`")
            page.click(selector)
            page.wait_for_load_state("domcontentloaded")
            body, cut = _truncate(_text(page), cap)
            return body, {"files": [], "url": page.url, "truncated": cut,
                          "links": _links(page)[:10]}
        if action == "fill":
            selector = str(args.get("selector") or "").strip()
            if not selector:
                raise ValueError("fill necesita `selector`")
            page.fill(selector, str(args.get("text") or ""))
            return "campo rellenado: %s" % selector, {"files": []}
        if action == "press":
            page.keyboard.press(str(args.get("text") or "Enter"))
            page.wait_for_load_state("domcontentloaded")
            body, cut = _truncate(_text(page), cap)
            return body, {"files": [], "url": page.url, "truncated": cut}
        if action == "links":
            rows = _links(page, limit=int(args.get("max_chars") or LINKS))
            text = "\n".join("- [%s](%s)" % (row["text"], row["href"]) for row in rows)
            return text or "(sin enlaces)", {"files": [], "links": len(rows)}
        if action == "screenshot":
            name = (str(args.get("text") or "pagina")[:40].replace(" ", "-") or "pagina") + ".png"
            page.screenshot(path=str(Path(self.root) / name), full_page=False)
            return "captura guardada: %s" % name, {"files": [name]}
        raise ValueError("accion desconocida %r (goto, extract, click, fill, press, links, "
                         "screenshot, close, restart)" % action)


def _worker(root, headless=True):
    key = str(Path(root).resolve())
    current = _WORKERS.get(key)
    if current is None or not current.is_alive():
        current = _Worker(root, headless=headless)
        current.start()
        _WORKERS[key] = current
    return current


def close(root):
    """Cierra el navegador de esa raiz. Devuelve `True` si habia uno abierto."""
    worker = _WORKERS.pop(str(Path(root).resolve()), None)
    if worker is None:
        return False
    worker.stop()
    return True


def available():
    """¿Hay motor? Se arranca uno de verdad y se cierra: barato y sin red."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="browser-probe-") as workspace:
        try:
            worker = _worker(workspace)
            worker.ready.wait(45)
            return worker.failure is None
        finally:
            close(workspace)


def run(root, args, config=None):
    """La herramienta. `args`: `{action, url, text, selector, max_chars}`."""
    action = str(args.get("action") or "goto").strip().lower()
    if action == "close":
        return ("navegador cerrado" if close(root) else "no habia navegador abierto"), {"files": []}
    if action == "restart":
        close(root)
        action = "goto"
    headless = bool(getattr(config, "browser_headless", True))
    return _worker(root, headless=headless).submit(action, args)


def selftest():
    """Con motor: extraccion, recorte y muros. Sin motor: se declara y no se finge."""
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    check("el texto se limpia", _clean("  a \n\n b  "), "a\nb")
    body, cut = _truncate("x" * 100, 10)
    check("el recorte avisa", cut, True)
    check("y dice cuanto sobra", "90" in body, True)
    check("un 403 es muro", bool(_blocked(403, "")), True)
    check("y 'Just a moment' tambien", bool(_blocked(200, "Just a moment...")), True)
    check("una pagina normal no", _blocked(200, "hola mundo"), "")

    with tempfile.TemporaryDirectory(prefix="browser-self-") as workspace:
        page = Path(workspace) / "hola.html"
        page.write_text("<html><head><title>Hola</title></head><body><p>texto</p></body></html>",
                        encoding="utf-8")
        try:
            text, meta = run(workspace, {"action": "goto", "url": page.as_uri()})
        except BrowserError as exc:
            problems.append("no hay motor de navegador: %s" % exc)
            return problems
        finally:
            close(workspace)
        check("una pagina local se lee", "texto" in text, True)
        check("y su titulo viaja", meta.get("title"), "Hola")
    return problems


HANDLERS = {"browser": run}
