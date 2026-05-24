# -*- mode: python ; coding: utf-8 -*-
import os

# SPECPATH = directory of this spec file (packaging/)
# root     = project root (one level up)
root = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(root, 'backend', 'main.py')],
    pathex=[os.path.join(root, 'backend')],
    binaries=[],
    datas=[
        # source -> destination inside sys._MEIPASS
        (os.path.join(root, 'build', 'web'), 'web'),
        (os.path.join(root, 'build', 'updater', 'Updater.exe'), 'updater'),
    ],
    hiddenimports=[
        'browser',
        'config',
        'updater',
        '_version',
        'routers.api',
    ],
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
    name='MyAgent',  # <-- change this to rename the output EXE (e.g. 'MyTool')
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
