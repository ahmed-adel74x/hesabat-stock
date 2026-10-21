"""بيبني HesabatStock.exe بـ PyInstaller. نفس الأمر بيستخدمه GitHub Actions و build_windows.bat.

    pip install -r requirements.txt pyinstaller
    python tools/build_exe.py            ← الناتج: dist/HesabatStock.exe
(لازم يتشغّل على ويندوز عشان الناتج يشتغل على ويندوز.)"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# وحدات Qt كبيرة ومش بنستخدمها (بتصغّر حجم الـ exe)
EXCLUDES = ["QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "Qt3DCore", "Qt3DRender", "Qt3DInput",
            "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras", "QtMultimedia", "QtMultimediaWidgets", "QtQuick",
            "QtQml", "QtCharts", "QtDataVisualization"]


def build_command(root=ROOT):
    sep = os.pathsep  # ";" على ويندوز
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
           "--windowed",                                        # من غير نافذة سوداء
           "--name", "HesabatStock",
           "--icon", os.path.join(root, "hesabat", "assets", "icon.ico"),
           "--add-data", f"{os.path.join(root, 'hesabat', 'assets')}{sep}{os.path.join('hesabat', 'assets')}"]
    for m in EXCLUDES:
        cmd += ["--exclude-module", f"PySide6.{m}"]
    cmd.append(os.path.join(root, "main.py"))
    return cmd


if __name__ == "__main__":
    sys.exit(subprocess.call(build_command(), cwd=ROOT))
