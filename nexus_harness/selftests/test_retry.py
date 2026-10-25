"""El reintento del transporte: acotado, con backoff, y solo en el estado que significa "ahora no".

Un 429 no es un error del trabajo ni del prompt: es el proveedor diciendo que vuelvas en un momento.
La distincion importa porque las dos politicas equivocadas se ven igual desde fuera: reintentar sin
limite deja el turno colgado, y no reintentar nada convierte un rate limit de diez segundos en "el
arnes no vale". Esta suite clava las cuatro promesas del transporte HTTP:

* un 429 o un 5xx se reintenta, y la respuesta que se devuelve es la del reintento;
* el numero de intentos esta acotado por `retries`: agotado, el error sale con su estado;
* el backoff crece, esta topado, y la escalera de esperas es la declarada;
* un estado que NO es "ahora no" (401, 400) no se reintenta: repetir un error permanente esconde la
  causa y lo paga dos veces el mismo turno.

Sin red y sin reloj: se sustituye el transporte por uno con guion y `sleep` por una lista. Lo que se
mide es la politica, que es exactamente lo que no se puede medir esperando de verdad.
"""
import types

from ..transports import http


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def _error(status, body="busy"):
    return http.TransportError("HTTP %s" % status, status=status, body=body)


def _scripted(script, calls):
    """Un `_request` con guion: el paso n-esimo de `script`, y el ultimo se repite si hace falta."""
    def fake(url, payload=None, headers=None, timeout=120, method=None):
        calls.append("%s %s" % (method or ("POST" if payload else "GET"), url))
        step = script[min(len(calls) - 1, len(script) - 1)]
        if isinstance(step, Exception):
            raise step
        return step
    return fake


def attempt(script, call):
    """Ejecuta `call` con el transporte y el reloj sustituidos. Devuelve (valor, esperas, llamadas, error)."""
    calls, sleeps, box = [], [], {}
    saved = (http._request, http.time)
    http._request = _scripted(script, calls)
    # `http.time` es el nombre del modulo DENTRO de http.py: sustituirlo aqui no toca el reloj real del
    # proceso, asi que una suite que corre en paralelo no ve dormir a nadie.
    http.time = types.SimpleNamespace(sleep=sleeps.append)
    try:
        box["value"] = call()
    except http.TransportError as exc:
        box["error"] = exc
    finally:
        http._request, http.time = saved
    return box.get("value"), sleeps, calls, box.get("error")


def test_a_429_is_retried_and_the_answer_is_the_retry(failures):
    result, sleeps, calls, error = attempt([_error(429, "slow down"), {"ok": True}],
                                           lambda: http.post_json("u", {"a": 1}))
    check("el reintento devuelve la respuesta del segundo intento", result, {"ok": True}, failures)
    check("y no queda error", error, None, failures)
    check("se intenta exactamente dos veces", len(calls), 2, failures)
    check("con el backoff declarado entre los dos", sleeps, [2], failures)


def test_the_ladder_grows_and_is_capped(failures):
    result, sleeps, calls, error = attempt([_error(503)] * 5,
                                           lambda: http.post_json("u", {}, retries=4))
    check("el backoff crece y se topa en 8s", sleeps, [2, 4, 8, 8], failures)
    check("los intentos son los pedidos mas el primero", len(calls), 5, failures)
    check("y el error sale cuando se agota", (error.status if error else None), 503, failures)
    check("sin devolver un valor inventado", result, None, failures)


def test_the_bound_is_a_bound(failures):
    _result, sleeps, calls, error = attempt([_error(429)] * 9,
                                            lambda: http.post_json("u", {}, retries=1))
    check("con retries=1 se intenta dos veces, no mas", len(calls), 2, failures)
    check("y una sola espera", len(sleeps), 1, failures)
    check("el error que sale es el del 429", (error.status if error else None), 429, failures)


def test_a_permanent_error_is_not_retried(failures):
    for status in (401, 400, 404):
        _result, sleeps, calls, error = attempt([_error(status)],
                                                lambda s=status: http.post_json("u", {}, retries=3))
        check("un %d no se reintenta" % status, len(calls), 1, failures)
        check("un %d no espera nada" % status, sleeps, [], failures)
        check("un %d sale tal cual" % status, (error.status if error else None), status, failures)


def test_get_json_follows_the_same_policy(failures):
    result, sleeps, calls, _error_ = attempt([_error(500), {"ok": "segundo"}],
                                             lambda: http.get_json("u"))
    check("get_json tambien se recupera de un 5xx", result, {"ok": "segundo"}, failures)
    check("con la misma espera unica", sleeps, [2], failures)
    check("y dos llamadas", len(calls), 2, failures)


def test_a_clean_call_never_waits(failures):
    result, sleeps, calls, _error_ = attempt([{"ok": True}], lambda: http.post_json("u", {}))
    check("una llamada limpia devuelve el valor", result, {"ok": True}, failures)
    check("sin esperas", sleeps, [], failures)
    check("y una sola llamada", len(calls), 1, failures)


def run():
    failures = []
    for test in (test_a_429_is_retried_and_the_answer_is_the_retry,
                 test_the_ladder_grows_and_is_capped,
                 test_the_bound_is_a_bound,
                 test_a_permanent_error_is_not_retried,
                 test_get_json_follows_the_same_policy,
                 test_a_clean_call_never_waits):
        test(failures)
    return failures
