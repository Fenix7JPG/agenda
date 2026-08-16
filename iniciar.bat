@echo off
cd /d "%~dp0"
echo Iniciando el servidor de tareas...
echo Cuando veas "Application startup complete", abre http://127.0.0.1:8000
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8000
.venv\Scripts\python.exe run.py
echo.
echo El servidor se detuvo. Puedes cerrar esta ventana.
pause
