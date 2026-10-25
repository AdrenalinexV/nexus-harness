"""`nexus` from this repository's root is a POINTER to the governor, not a copy of it.

`python -m nexus.harness.adapters` has to resolve with this repository as the working directory, and
vendoring the protocol to make that work would leave two definitions of every rule on this machine.
So this package extends its own search path to the real one: one definition, one place to fix, and
nothing to keep in step by hand. `NEXUS_PROTOCOL` overrides the location, exactly as
`nexus_harness/bridge.py` and the rest of the repository already do.

Nothing else lives here, on purpose. A rule written in this file would be a rule the governor
cannot grade.
"""
import os
from pathlib import Path

SOURCE = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol") / "nexus"
if SOURCE.is_dir():
    __path__ = [str(SOURCE)]
