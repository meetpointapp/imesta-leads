@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (where python >nul 2>nul && (set PY=python) || (
  echo Python bulunamadi. https://www.python.org/downloads/ adresinden kurun
  echo ve kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
  pause
  exit /b 1))
%PY% web.py --open
pause
