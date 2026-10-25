# -*- mode: python ; coding: utf-8 -*-
"""La receta del motor congelado, versionada: lo que se entrega no es el repositorio, es este .exe.

Vivia generada en `.build/` (ignorado por git) por una linea larga de banderas en la documentacion,
asi que un build no se podia repetir desde el repositorio y nadie podia ver que lleva dentro el
binario. Aqui es un fichero del proyecto, con los datos declarados uno a uno, y las rutas se
resuelven desde ESTE fichero (`SPECPATH`), no desde el directorio desde el que se lance.

    .build/venv/Scripts/pyinstaller.exe --noconfirm --distpath dist --workpath .build/pyi tools/engine.spec
"""
import sys
from pathlib import Path

REPO = Path(SPECPATH).resolve().parent           # SPECPATH es tools/ -> la raiz del repositorio
PROTOCOL = REPO.parent / "NexusProtocol"        # el gobernador: se importa, no se vende

# Antes de `collect_submodules`, y por una razon medida: esas llamadas IMPORTAN los paquetes para
# recorrerlos, y `pyinstaller.exe` no pone el directorio de trabajo en `sys.path` (a diferencia de
# `python -m PyInstaller`, que si). Sin esto, el mismo spec construia un motor sin los paquetes y sin
# las suites -- 17 suites fallando por "No module named" -- segun como se lanzara.
for entry in (str(REPO), str(PROTOCOL)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from PyInstaller.utils.hooks import collect_submodules  # noqa: E402  (el path se prepara arriba)

# Pillow se empaqueta a proposito: la app congelada tiene que poder redimensionar una captura pegada,
# y sin Pillow cada imagen grande se convierte en un rechazo en vez de una previsualizacion.
hiddenimports = (collect_submodules("PIL") + collect_submodules("nexus")
                 + collect_submodules("nexus_harness"))
# `webbrowser` viaja a mano, y se midio: la GUI del protocolo lo importa en el nivel del modulo
# (`nexus/gui.py`), y sin el el motor congelado contesta a las vistas de gobernanza con un "no es
# importable" perfectamente honesto -- y perfectamente inutil. Un dato o un modulo que solo existe en
# la maquina del build es la razon de que este spec este en el repositorio.
hiddenimports += ["webbrowser"]

a = Analysis(
    [str(REPO / "tools" / "engine_entry.py")],
    pathex=[str(PROTOCOL), str(REPO)],
    binaries=[],
    # `web` es la interfaz que el motor sirve; `tools/nightshift.py` esta aqui porque el motor
    # congelado pasa LA MISMA suite, y esa suite mide la maquina del turno de noche. Un dato que la
    # suite necesita y el .exe no lleva es una suite que solo puede pasar en la maquina del build.
    datas=[(str(REPO / "nexus_harness" / "web"), "web"),
           # El turno de noche y su cerrojo: los dos, porque el segundo es un modulo que el primero
           # importa. Medido: con solo `nightshift.py` dentro, la suite congelada moria con
           # "No module named 'nightshift_lock'" -- una suite que solo pasa en la maquina del build.
           (str(REPO / "tools" / "nightshift.py"), "tools"),
           (str(REPO / "tools" / "nightshift_lock.py"), "tools"),
           # Los datos del protocolo que su GUI lee EN CALIENTE (`fleet` lee el manifiesto de
           # instalacion, `gui_fixtures` sus ejemplos). Sin ellos, el motor congelado sirve las vistas
           # de gobernanza hasta que una de ellas necesita un fichero y se queda a medias.
           (str(PROTOCOL / "nexus" / "spec"), "nexus/spec"),
           (str(PROTOCOL / "nexus" / "fixtures"), "nexus/fixtures")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nexus-harness-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
