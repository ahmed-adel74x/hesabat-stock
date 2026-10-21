@echo off
rem Builds dist\HesabatStock.exe on a Windows PC (needs Python 3.10+ installed with "Add to PATH").
cd /d "%~dp0"
python -m venv .buildenv || goto :err
call .buildenv\Scripts\activate || goto :err
python -m pip install --upgrade pip || goto :err
pip install -r requirements.txt pyinstaller || goto :err
python tools\build_exe.py || goto :err
if exist "%TEMP%\hesabat_selftest.txt" del "%TEMP%\hesabat_selftest.txt"
start /wait "" dist\HesabatStock.exe --selftest "%TEMP%\hesabat_selftest.txt"
echo ---- self test result ----
type "%TEMP%\hesabat_selftest.txt"
echo --------------------------
echo Done: dist\HesabatStock.exe
pause
exit /b 0
:err
echo BUILD FAILED
pause
exit /b 1
