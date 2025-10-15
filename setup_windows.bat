@echo off
REM Script de instalacion y configuracion del proyecto Lohas (Windows)
REM Requisitos: Python 3.9+, Git (ejecuta setup_dependencies_windows.ps1 si no los tienes)

echo.
echo 🚀 Configurando proyecto Lohas (Windows)...
echo.

REM 1. Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python 3 no esta instalado.
    echo    Ejecuta primero: setup_dependencies_windows.ps1
    pause
    exit /b 1
)

echo ✅ Python encontrado:
python --version

REM Verificar version de Python (minimo 3.9)
python -c "import sys; exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  Se requiere Python 3.9 o superior
    echo    Ejecuta: setup_dependencies_windows.ps1
    pause
    exit /b 1
)

echo.
echo 📦 Creando entorno virtual...
python -m venv .venv

echo.
echo 🔧 Activando entorno virtual...
call .venv\Scripts\activate.bat

echo.
echo ⬆️  Actualizando pip...
python -m pip install --upgrade pip

echo.
echo 📥 Instalando dependencias...
pip install -r requirements.txt

echo.
echo 📁 Creando carpetas necesarias...
if not exist "run_logs" mkdir run_logs
if not exist "transfer_logs" mkdir transfer_logs
if not exist "descargas" mkdir descargas

echo.
echo ✅ ¡Configuracion completada!
echo.
echo 📋 Proximos pasos:
echo 1. Activa el entorno virtual: .venv\Scripts\activate
echo 2. Inicia el servidor Flask: set PORT=5001 ^&^& python flask_server.py
echo 3. Abre tu navegador en: http://localhost:5001
echo.
echo 🤖 Bots disponibles:
echo    • Bot Transferencias: Ejecuta transferencias desde CSV
echo    • Bot CSV: Exporta datos a CSV
echo.
pause

