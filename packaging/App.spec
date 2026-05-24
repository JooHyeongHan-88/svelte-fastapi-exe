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
        # Agent guideline directories — backend/agent/registries/{prompts,skills}.py 가 MEIPASS 에서 읽음.
        (os.path.join(root, 'PROMPTS'), 'PROMPTS'),
        (os.path.join(root, 'SKILLS'), 'SKILLS'),
    ],
    hiddenimports=[
        '_version',
        'core',
        'core.config',
        'core.browser',
        'core.updater',
        'agent',
        'agent.config',
        'agent.harness',
        'agent.guard',
        'agent.models',
        'agent.stores.conversation',
        'agent.stores.agent_state',
        'agent.registries.prompts',
        'agent.registries.skills',
        'agent.registries.tools',
        'agent.providers.factory',
        'agent.providers.mock',
        'agent.providers.openai',
        'settings.config',
        'settings.models',
        'settings.store',
        'settings.masking',
        'api',
        'api.deps',
        'api.chat',
        'api.presence',
        'api.update',
        'api.settings',
        'api.skills',
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
