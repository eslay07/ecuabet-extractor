@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo No se encontro el entorno virtual .venv.
  pause
  exit /b 1
)
start "EcuabetExtractor" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -m src.gui
exit /b 0

