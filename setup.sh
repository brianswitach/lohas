#!/bin/bash
# Script de instalación y configuración del proyecto Lohas

echo "🚀 Configurando proyecto Lohas..."

# 1. Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 no está instalado. Por favor, instala Python 3.9 o superior."
    exit 1
fi

echo "✅ Python encontrado: $(python3 --version)"

# 2. Crear entorno virtual
echo "📦 Creando entorno virtual..."
python3 -m venv .venv

# 3. Activar entorno virtual
echo "🔧 Activando entorno virtual..."
source .venv/bin/activate

# 4. Actualizar pip
echo "⬆️  Actualizando pip..."
pip install --upgrade pip

# 5. Instalar dependencias
echo "📥 Instalando dependencias..."
pip install -r requirements.txt

# 6. Crear carpetas necesarias
echo "📁 Creando carpetas necesarias..."
mkdir -p run_logs
mkdir -p transfer_logs
mkdir -p descargas

echo ""
echo "✅ ¡Configuración completada!"
echo ""
echo "📋 Próximos pasos:"
echo "1. Activa el entorno virtual: source .venv/bin/activate"
echo "2. Inicia el servidor Flask: PORT=5001 python3 flask_server.py"
echo "3. Abre tu navegador en: http://localhost:5001"
echo ""
echo "🤖 Bots disponibles:"
echo "   • Bot Transferencias: Ejecuta transferencias desde CSV"
echo "   • Bot CSV: Exporta datos a CSV"
echo ""

