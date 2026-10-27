"""El plan como grafo: nodos con dependencias, no un paso suelto que el modelo inventa cada turno.

El fallo que arregla: el planificador devolvia **un** paso por iteracion. Asi no se puede razonar sobre
dependencias, ni detectar que dos pasos se contradicen, ni saber que dos tareas son independientes. Un
plan de un paso es una reaccion, no un plan.

Aqui un plan es `{"nodes": [{"id": "n1", "step": "...", "depends_on": []}]}`, con tres garantias:

* **Sin ciclos.** Si el modelo se contradice (`n1 -> n2 -> n1`), el grafo se rechaza y se dice; no se
  ejecuta medio plan imposible.
* **Techo de nodos.** `MAX_NODES = 7`: un plan de veinte nodos no es ambicioso, es incomprobable.
* **Orden topologico en olas.** `waves()` dice que se puede hacer a la vez y que tiene que esperar.
  La ejecucion de una ola es secuencial a proposito: dos escrituras en el mismo arbol compiten, y ese
  es exactamente el fallo que el gate existe para cazar. La ola describe el paralelismo; el worktree
  por rama es lo que lo hara seguro.

Nada de esto llama a un modelo: se puede probar con un dict.
"""
import json
import re
from dataclasses import dataclass, field

MAX_NODES = 7
ID = re.compile(r"^[A-Za-z0-9_.-]{1,24}$")


@dataclass
class Node:
    """Un paso con nombre, dependencias y (opcionalmente) los ficheros que toca."""

    id: str
    step: str
    depends_on: list = field(default_factory=list)
    files: list = field(default_factory=list)

    def as_dict(self):
        return {"id": self.id, "step": self.step, "depends_on": list(self.depends_on),
                "files": list(self.files)}


class GraphError(ValueError):
    """Un plan que no se puede ejecutar: ciclo, ids repetidos o demasiados nodos."""


def _json_object(text):
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _clean_id(value, index):
    text = str(value or "").strip()
    return text if ID.match(text) else "n%d" % (index + 1)


def parse_graph(text):
    """`{nodes, step, done, why, new_criterion}` desde la respuesta del Director.

    Acepta el formato viejo (`{"step": "..."}`) porque un planificador conectado a un modelo pequeno
    seguira contestando asi, y degradar a un nodo es mejor que no planificar.
    """
    data = _json_object(text)
    if data is None:
        line = next((row.strip() for row in str(text or "").splitlines() if row.strip()), "")
        nodes = [Node("n1", line)] if line else []
        return {"nodes": nodes, "step": line, "done": False, "why": "plan sin JSON: primera linea",
                "new_criterion": None}
    raw_nodes = data.get("nodes") or data.get("steps") or []
    nodes, seen = [], set()
    for index, item in enumerate(raw_nodes if isinstance(raw_nodes, list) else []):
        if not isinstance(item, dict):
            continue
        step = str(item.get("step") or item.get("title") or "").strip()
        if not step:
            continue
        node_id = _clean_id(item.get("id"), index)
        if node_id in seen:
            node_id = "n%d" % (index + 1)
        seen.add(node_id)
        deps = [str(one) for one in (item.get("depends_on") or item.get("deps") or [])
                if str(one).strip()]
        files = [str(one) for one in (item.get("files") or []) if str(one).strip()]
        nodes.append(Node(node_id, step[:400], deps, files))
        if len(nodes) >= MAX_NODES:
            break
    if not nodes and data.get("step"):
        nodes = [Node("n1", str(data.get("step")).strip()[:400])]
    criterion = data.get("new_criterion")
    if not isinstance(criterion, dict) or not str(criterion.get("command") or "").strip():
        criterion = None
    else:
        criterion = {"title": str(criterion.get("title") or criterion["command"])[:160],
                     "command": str(criterion["command"]).strip(),
                     "expect_exit": int(criterion.get("expect_exit") or 0)}
    done = bool(data.get("done")) and not nodes
    return {"nodes": nodes, "step": nodes[0].step if nodes else "", "done": done,
            "why": "plan del director" if nodes else ("sin pasos" if done else "plan vacio"),
            "new_criterion": criterion}


def as_nodes(items):
    """Normaliza `Node` o dicts a `Node`. Un planificador inyectado puede devolver dicts crudos."""
    rows = []
    for index, item in enumerate(items or []):
        if isinstance(item, Node):
            rows.append(item)
            continue
        if not isinstance(item, dict):
            continue
        step = str(item.get("step") or item.get("title") or "").strip()
        if not step:
            continue
        rows.append(Node(_clean_id(item.get("id"), index), step[:400],
                         [str(one) for one in (item.get("depends_on") or item.get("deps") or [])],
                         [str(one) for one in (item.get("files") or [])]))
        if len(rows) >= MAX_NODES:
            break
    return rows


def validate(nodes):
    """Comprueba que el grafo se puede ejecutar. Devuelve los nodos o lanza `GraphError`."""
    nodes = as_nodes(nodes)
    ids = [node.id for node in nodes]
    if len(set(ids)) != len(ids):
        raise GraphError("ids repetidos: %s" % ", ".join(sorted(ids)))
    known = set(ids)
    for node in nodes:
        missing = [dep for dep in node.depends_on if dep not in known]
        if missing:
            raise GraphError("%s depende de %s, que no esta en el plan" % (node.id, ", ".join(missing)))
    _topology(nodes)   # un ciclo es un plan imposible: se detecta al validar, no al ejecutar
    return nodes


def _topology(nodes):
    """Kahn puro: `[[ids]]` por ola. Lanza `GraphError` si quedan nodos sin poder ordenarse."""
    pending = {node.id: set(node.depends_on) for node in nodes}
    order = [node.id for node in nodes]
    result, done = [], set()
    while pending:
        ready = [node_id for node_id in order if node_id in pending and pending[node_id] <= done]
        if not ready:
            raise GraphError("ciclo entre: %s" % ", ".join(sorted(pending)))
        result.append(ready)
        for node_id in ready:
            done.add(node_id)
            pending.pop(node_id)
    return result


def waves(nodes):
    """`[[ids]]` por ola topologica. Lanza `GraphError` si hay un ciclo."""
    return _topology(validate(nodes))


def ready(nodes, done_ids):
    """Los nodos que se pueden ejecutar YA, en el orden en que el plan los declaro."""
    nodes = as_nodes(nodes)
    finished = {str(one) for one in (done_ids or ())}
    return [node for node in nodes
            if node.id not in finished and set(node.depends_on) <= finished]


def summarise(nodes):
    """Una linea para el hilo: cuantos nodos, cuantas olas y si hay algo bloqueado."""
    nodes = as_nodes(nodes)
    try:
        plan = waves(nodes)
    except GraphError as exc:
        return {"ok": False, "reason": str(exc), "nodes": len(nodes), "waves": 0}
    return {"ok": True, "nodes": len(nodes), "waves": len(plan),
            "wave_sizes": [len(one) for one in plan]}
