"""Contador de tokens: la estimacion y el factor medido, con sus bordes.

El presupuesto del arnes (poda al 55 %, relevo al 70 %) depende de este numero. Si miente, el arnes
decide tarde o temprano, y en los dos casos paga.
"""
from ..platform import tokenizer


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_module_selftest(failures):
    for problem in tokenizer.selftest():
        failures.append("tokenizer.selftest: %s" % problem)


def test_the_estimate_grows_with_the_text(failures):
    short = "def add(a, b):\n    return a + b\n"
    check("mas codigo, mas tokens", tokenizer.estimate(short * 3) > tokenizer.estimate(short),
          True, failures)
    check("vacio es cero", tokenizer.estimate(""), 0, failures)
    check("una sola letra cuesta uno", tokenizer.estimate("x"), 1, failures)
    check("el texto no ascii tambien cuenta", tokenizer.estimate("ñ" * 50) >= 1, True, failures)


def test_a_message_costs_more_than_its_text(failures):
    from ..core.message import Message
    text = "hola mundo"
    body = tokenizer.count(text)
    messages = [Message(role="user", content=text), Message(role="assistant", content=text)]
    check("el envoltorio de rol se paga", tokenizer.count_messages(messages) > body * 2, True,
          failures)


def test_an_uncalibrated_model_is_not_corrected(failures):
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix="tok-") as workspace:
        cal = tokenizer.Calibration(Path(workspace) / "c.json")
        check("sin muestras no hay factor", cal.factor("m"), 1.0, failures)
        check("y el conteo es la estimacion", tokenizer.count("abc def", "m", cal),
              tokenizer.estimate("abc def"), failures)
        for _sample in range(10):
            cal.observe("m", 100, 80)
        check("un modelo que gasta menos baja el conteo",
              tokenizer.count("x " * 100, "m", cal) < tokenizer.estimate("x " * 100), True, failures)


def test_a_model_without_a_name_gets_no_correction(failures):
    """Una clave vacia no es "todos los modelos": es un modelo sin nombre, y no se corrige.

    El fichero de calibracion de esta maquina tenia una fila `""` con factor 0,4 (sesgo medido en otro
    tokenizer). Aplicada al compactor, el presupuesto se creia con un 60 % mas de sitio del real: justo
    el fallo por el que el prompt acababa en un 400.
    """
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix="tok-sin-nombre-") as workspace:
        path = Path(workspace) / "c.json"
        path.write_text('{"": {"factor": 0.4, "samples": 9}}', encoding="utf-8")
        cal = tokenizer.Calibration(path)
        check("sin nombre no hay factor", cal.factor(""), 1.0, failures)
        check("y no se escribe una muestra sin nombre", cal.observe("", 100, 300), 1.0, failures)
        check("el conteo de un modelo sin nombre es la estimacion",
              tokenizer.count("abc def", "", cal), tokenizer.estimate("abc def"), failures)


def run():
    failures = []
    test_module_selftest(failures)
    test_the_estimate_grows_with_the_text(failures)
    test_a_message_costs_more_than_its_text(failures)
    test_an_uncalibrated_model_is_not_corrected(failures)
    test_a_model_without_a_name_gets_no_correction(failures)
    return failures
