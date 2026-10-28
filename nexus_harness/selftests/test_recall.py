"""Memoria por capas: core siempre (con techo), historia solo cuando se pregunta.

Lo que se mide:
* un `fact` sin evidencia NO se guarda (una preferencia inventada envenena todos los turnos);
* la misma frase no entra dos veces;
* `search` encuentra por término (FTS5 o LIKE) y respeta el presupuesto de caracteres;
* `core` viaja al prefijo del chat, y un episodio relevante se recupera por la consulta;
* `recall`/`remember` son herramientas del modelo, y `remember` exige evidencia.
"""
import tempfile
from pathlib import Path

from .fakes import FakeGate, FakeRouter, ScriptedProvider, TempProject, reply
from ..chat import Chat
from ..config import HarnessConfig
from ..recall import Recall, episode_text, remember_turn
from ..tools import default_registry


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_layers_and_evidence(failures):
    with TempProject() as root:
        memory = Recall(root)
        refused = memory.add("fact", "prefiere respuestas cortas")
        check("un hecho sin evidencia no entra", refused["ok"], False, failures)
        kept = memory.add("fact", "prefiere respuestas cortas",
                          evidence="lo dijo el 2026-10-28 en el chat")
        check("con evidencia si", kept["ok"], True, failures)
        again = memory.add("fact", "prefiere respuestas cortas", evidence="otra vez")
        check("y no se duplica", again.get("duplicate"), True, failures)
        check("capa desconocida se rechaza", memory.add("sueño", "x")["ok"], False, failures)
        memory.add("core", "El operador es desarrollador de FiveM.")
        check("el core se lee", "FiveM" in memory.core(), True, failures)


def test_search_finds_and_respects_the_budget(failures):
    with TempProject() as root:
        memory = Recall(root)
        memory.add("episode", "objetivo: renombrar add a suma | exit: 0 | ficheros: calc.py",
                   evidence="turno cerrado")
        memory.add("episode", "objetivo: montar la web del panel | exit: 10",
                   evidence="turno cerrado")
        rows = memory.search("renombrar")
        check("encuentra el episodio", len(rows), 1, failures)
        check("y dice la capa", rows[0]["kind"], "episode", failures)
        check("una consulta sin terminos no trae nada", memory.search("de la"), [], failures)
        memory.add("episode", "x" * 600 + " renombrar", evidence="turno cerrado")
        cramped = memory.search("renombrar", budget=120)
        check("el presupuesto corta", len(cramped) <= 1, True, failures)
        check("y devuelve algo", len(cramped) >= 1, True, failures)


def test_core_has_a_ceiling(failures):
    with TempProject() as root:
        memory = Recall(root)
        for index in range(12):
            memory.add("core", "hecho estable numero %d %s" % (index, "x" * 120))
        block = memory.core()
        check("el core no crece sin freno", len(block) <= 800, True, failures)
        check("pero hay contenido", len(block) > 0, True, failures)


def test_an_episode_is_written_and_found(failures):
    with TempProject() as root:
        row = remember_turn(root, "arregla la suma de calc.py", 10, ["calc.py"], repairs=1,
                            project="Alpha")
        check("el episodio se apunta", row["ok"], True, failures)
        text = episode_text("arregla la suma", 10, ["calc.py"], 1)
        check("y su texto dice el exit", "exit: 10" in text, True, failures)
        found = Recall(root).search("suma")
        check("se recupera por el objetivo", len(found), 1, failures)


def test_prune_forgets_old_episodes_only(failures):
    with TempProject() as root:
        memory = Recall(root)
        memory.add("episode", "episodio viejo sobre renombrar", evidence="test")
        memory.add("fact", "hecho que no caduca", evidence="test")
        with memory.connect() as connection:
            connection.execute("UPDATE rows SET at = '2020-01-01T00:00:00Z' WHERE kind = 'episode'")
            connection.commit()
        gone = memory.prune(days=30)
        check("se borra el episodio viejo", gone, 1, failures)
        check("el hecho se queda", len(memory.search("caduca")), 1, failures)


def test_the_chat_prompt_carries_only_what_matters(failures):
    with TempProject() as root:
        memory = Recall(root)
        memory.add("core", "El operador trabaja en AXV y prefiere respuestas cortas.")
        memory.add("episode", "objetivo: renombrar add a suma en calc | exit: 0",
                   evidence="turno cerrado")
        worker = ScriptedProvider([reply("Hola.")])
        config = HarnessConfig(default_root=root, max_steps=2, temperature=0.0, secrets={},
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"})
        chat = Chat(FakeRouter(workers=worker), config, default_registry(root, config), FakeGate(),
                    None)
        chat.new("memoria")
        chat.send("¿recuerdas el renombrado de calc?")
        system = worker.calls[0]["messages"][0]["content"]
        check("el core viaja", "AXV" in system, True, failures)
        check("y lo relevante se recupera", "renombrar" in system, True, failures)
        check("pero no se manda todo", "montar la web" not in system, True, failures)


def test_the_tools_are_in_the_arsenal(failures):
    with TempProject() as root:
        registry = default_registry(root, HarnessConfig(default_root=root))
        check("el modelo ve recall", "recall" in registry.names(), True, failures)
        check("y remember", "remember" in registry.names(), True, failures)
        saved = registry.call("remember", {"text": "el operador prefiere ramas master",
                                           "evidence": "lo dijo en el chat"})
        check("remember guarda con evidencia", saved.ok, True, failures)
        refused = registry.call("remember", {"text": "sin pruebas"})
        check("sin evidencia es un fallo visible", refused.ok, False, failures)
        found = registry.call("recall", {"query": "ramas master"})
        check("y recall lo encuentra", "master" in found.text, True, failures)


def run():
    failures = []
    test_layers_and_evidence(failures)
    test_search_finds_and_respects_the_budget(failures)
    test_core_has_a_ceiling(failures)
    test_an_episode_is_written_and_found(failures)
    test_prune_forgets_old_episodes_only(failures)
    test_the_chat_prompt_carries_only_what_matters(failures)
    test_the_tools_are_in_the_arsenal(failures)
    return failures
