# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

fs_data, fs_binaries, fs_hidden = collect_all("flask_security")
# passlib loads its hash handlers by string name at runtime
# (passlib.handlers.bcrypt etc.), invisible to static scanning;
# without them the packaged exe dies inside Flask-Security init.
pl_data, pl_binaries, pl_hidden = collect_all("passlib")

a = Analysis(
    ["run_famquiz.py"],
    pathex=[],
    binaries=fs_binaries + pl_binaries,
    datas=fs_data + pl_data
    + [
        ("templates", "templates"),
        ("static", "static"),
        ("translations.json", "."),
    ],
    hiddenimports=fs_hidden + pl_hidden,
    excludes=["tests", "pytest", "pytest_cache"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FamQuiz",
    console=True,
    debug=False,
    upx=False,
)

# No COLLECT(): placing the EXE call last (without it) is what makes this
# a single-file (onefile) build. Data lands in the exe's temp folder,
# exactly where app.py and Flask look for it when frozen.