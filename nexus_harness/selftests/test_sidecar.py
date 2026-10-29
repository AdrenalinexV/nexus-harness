"""The sidecar contract: an engine launched by the shell does not outlive it.

The whole point of this file is that the *accidental* exit path (a crash, a Task Manager kill) leaves no
process holding the engine's own `.exe`, because that is what silently blocks the next install.
"""
from ..tools import sidecar


def run():
    return list(sidecar.selftest())
