# PyInstaller build of "osu Hit Analyzer.exe" (single file, no console). Run ./build.ps1.
import re
from pathlib import PureWindowsPath

# Python modules the app never uses
EXCLUDES = ["PyQt5", "PyQt6", "PySide2", "matplotlib", "PIL", "IPython", "pytest",
            "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtPdf"]

# Qt / OpenSSL files collected by the PySide6 hooks but not needed by a widgets app: dropping
# them makes the exe smaller and faster to unpack at every start
UNUSED_BINARY = re.compile(
    r"(opengl32sw|d3dcompiler_\d+|Qt6(Quick|Qml|Pdf|Network|OpenGL|VirtualKeyboard|Svg)\w*"
    r"|q(direct2d|minimal|offscreen|pdf|svg|tiff|webp|icns|tga|wbmp)|qtvirtualkeyboardplugin"
    r"|q\w*(backend|networklistmanager)|lib(crypto|ssl)-3-x64)\.(dll|pyd)", re.IGNORECASE)


def unused(dest):
    parts = PureWindowsPath(dest).parts
    return bool(UNUSED_BINARY.fullmatch(parts[-1])) or "translations" in parts


a = Analysis(
    ["gui.py"],
    datas=[("assets/icon.ico", "assets")],
    excludes=EXCLUDES,
)
a.binaries = [b for b in a.binaries if not unused(b[0])]
a.datas = [d for d in a.datas if not unused(d[0])]
pyz = PYZ(a.pure)

# Shown while the exe unpacks; the app's loading screen then takes its place (tools/make_splash.py)
splash = Splash(
    "assets/splash.png",
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    minify_script=True,
    always_on_top=True,
    center="active",
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name="osu Hit Analyzer",
    console=False,
    upx=False,
    icon=["assets/icon.ico"],
)
