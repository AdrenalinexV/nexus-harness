"""La herramienta con la que el Director decide aprender: `forge_or_update_skill`.

Sin ella, la forja automatica solo reacciona a fallos. Con ella el agente puede escribir la regla
cuando entiende algo critico, que es justo lo que un especialista hace y un reintento no.

Dos decisiones que la mantienen segura:

* **No pisa una skill existente** salvo que se pida con `overwrite=True`, y entonces lo dice en el
  resultado. Una herramienta que sobrescribe conocimiento en silencio es una herramienta que borra.
* **Devuelve la ruta y el sha256**, no un "ok". Lo que no se puede comprobar no se declara.
"""
from .. import skill_forge


def forge_or_update_skill(root, args, config=None):
    topic = str((args or {}).get("topic") or "").strip()
    if not topic:
        raise ValueError("falta `topic`: describe el dominio o el stack que hay que cubrir")
    reason = str((args or {}).get("reason") or "").strip()
    observations = (args or {}).get("observations") or []
    if isinstance(observations, str):
        observations = [line.strip() for line in observations.splitlines() if line.strip()]
    result = skill_forge.forge(root, topic, reason=reason, observations=observations,
                               overwrite=bool((args or {}).get("overwrite")))
    text = ("%s %s · sha256=%s · origen=%s%s\n%s"
            % ("actualizada" if result["created"] else "ya existia", result["name"],
               result["sha256"][:16], result["ledger"],
               " (no se toco: pide overwrite para reescribirla)" if not result["created"] else "",
               result["path"]))
    return text, {"files": [result["path"]], "skill": result["name"], "sha256": result["sha256"],
                  "created": result["created"]}


HANDLERS = {"forge_or_update_skill": forge_or_update_skill}
