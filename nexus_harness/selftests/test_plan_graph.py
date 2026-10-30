"""El plan como grafo: nodos, dependencias, olas y ciclos.

Lo que se mide: que un plan de un solo paso se acepte (degradar), que un grafo con dependencias se
ordene, que un ciclo se RECHAce en vez de ejecutarse a medias, y que el techo de nodos se respete.
"""
from ..autonomy import plan_graph


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_legacy_single_step_still_works(failures):
    plan = plan_graph.parse_graph('{"done": false, "step": "arreglar calc.py"}')
    check("hay un nodo", len(plan["nodes"]), 1, failures)
    check("con su paso", plan["nodes"][0].step, "arreglar calc.py", failures)
    check("y el paso de siempre", plan["step"], "arreglar calc.py", failures)


def test_a_graph_with_dependencies_is_ordered(failures):
    text = ('{"nodes": [{"id": "a", "step": "escribe el test"}, '
            '{"id": "b", "step": "arregla calc", "depends_on": ["a"]}, '
            '{"id": "c", "step": "documenta", "depends_on": []}]}')
    plan = plan_graph.parse_graph(text)
    check("tres nodos", [node.id for node in plan["nodes"]], ["a", "b", "c"], failures)
    check("dos olas: a y c a la vez, b despues", plan_graph.waves(plan["nodes"]), [["a", "c"], ["b"]],
          failures)
    check("listos al principio: a y c", [node.id for node in plan_graph.ready(plan["nodes"], [])],
          ["a", "c"], failures)
    check("tras a, solo b", [node.id for node in plan_graph.ready(plan["nodes"], ["a", "c"])],
          ["b"], failures)
    check("el resumen dice las olas", plan_graph.summarise(plan["nodes"])["waves"], 2, failures)


def test_a_cycle_is_refused(failures):
    text = '{"nodes": [{"id": "a", "step": "x", "depends_on": ["b"]}, {"id": "b", "step": "y", "depends_on": ["a"]}]}'
    nodes = plan_graph.parse_graph(text)["nodes"]
    try:
        plan_graph.waves(nodes)
        failures.append("un ciclo no puede ordenarse y no lanzo")
    except plan_graph.GraphError as exc:
        check("el ciclo se explica", "ciclo" in str(exc), True, failures)
    check("y el resumen lo declara rojo", plan_graph.summarise(nodes)["ok"], False, failures)


def test_a_dependency_outside_the_plan_is_refused(failures):
    nodes = plan_graph.parse_graph('{"nodes": [{"id": "a", "step": "x", "depends_on": ["zz"]}]}')["nodes"]
    try:
        plan_graph.validate(nodes)
        failures.append("una dependencia inexistente no lanzo")
    except plan_graph.GraphError as exc:
        check("dice cual falta", "zz" in str(exc), True, failures)


def test_the_node_ceiling_is_respected(failures):
    nodes = [{"id": "n%d" % index, "step": "paso %d" % index} for index in range(20)]
    plan = plan_graph.parse_graph('{"nodes": %s}' % __import__("json").dumps(nodes))
    check("no pasa de siete", len(plan["nodes"]), plan_graph.MAX_NODES, failures)


def test_ids_are_cleaned_and_unique(failures):
    text = ('{"nodes": [{"id": "con espacio", "step": "uno"}, {"id": "n2", "step": "dos"}, '
            '{"id": "n2", "step": "tres"}]}')
    plan = plan_graph.parse_graph(text)
    ids = [node.id for node in plan["nodes"]]
    check("los ids son validos", all(" " not in one for one in ids), True, failures)
    check("y no se repiten", len(set(ids)), len(ids), failures)


def test_new_criterion_is_parsed_only_with_a_command(failures):
    good = plan_graph.parse_graph('{"nodes": [{"id": "a", "step": "x"}], "new_criterion": '
                                  '{"title": "la api responde", "command": "python -c print(1)"}}')
    check("el criterio entra", good["new_criterion"]["title"], "la api responde", failures)
    bad = plan_graph.parse_graph('{"nodes": [{"id": "a", "step": "x"}], "new_criterion": '
                                 '{"title": "sin comando"}}')
    check("sin comando no hay criterio", bad["new_criterion"], None, failures)


def test_done_only_when_there_are_no_nodes(failures):
    check("done con nodos no cierra", plan_graph.parse_graph(
        '{"done": true, "nodes": [{"id": "a", "step": "x"}]}')["done"], False, failures)
    check("done sin nodos si cierra", plan_graph.parse_graph('{"nodes": [], "done": true}')["done"],
          True, failures)


def run():
    failures = []
    test_legacy_single_step_still_works(failures)
    test_a_graph_with_dependencies_is_ordered(failures)
    test_a_cycle_is_refused(failures)
    test_a_dependency_outside_the_plan_is_refused(failures)
    test_the_node_ceiling_is_respected(failures)
    test_ids_are_cleaned_and_unique(failures)
    test_new_criterion_is_parsed_only_with_a_command(failures)
    test_done_only_when_there_are_no_nodes(failures)
    return failures
