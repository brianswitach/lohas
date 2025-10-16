#!/bin/bash
# Script de instalación para servidor Ubuntu en la nube (Huawei Cloud ECS)
# Ejecutar como root o con sudo

echo "☁️  Configurando Lohas Bot en Huawei Cloud ECS..."
echo ""

# 1. Verificar que estamos en Ubuntu/Debian
if ! command -v apt &> /dev/null; then
    echo "❌ Este script es para Ubuntu/Debian"
    exit 1
fi

# 2. Actualizar sistema
echo "📦 Actualizando sistema..."
sudo apt update
sudo apt upgrade -y

# 3. Instalar Python 3.9+
echo ""
echo "🐍 Instalando Python..."
sudo apt install -y python3 python3-pip python3-venv

# 4. Instalar Git
echo ""
echo "📝 Instalando Git..."
sudo apt install -y git

# 5. Instalar Google Chrome
echo ""
echo "🌐 Instalando Google Chrome..."
if ! command -v google-chrome &> /dev/null; then
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt install -y ./google-chrome-stable_current_amd64.deb
    rm google-chrome-stable_current_amd64.deb
    echo "✅ Google Chrome instalado"
else
    echo "✅ Google Chrome ya está instalado"
fi

# 6. Instalar dependencias de Chrome/Selenium
echo ""
echo "🔧 Instalando dependencias de Selenium..."
sudo apt install -y chromium-chromedriver
sudo apt install -y xvfb libxi6 libgconf-2-4 libnss3 libxss1 libappindicator3-1 libatk-bridge2.0-0 libgtk-3-0 libgbm1 libasound2

# 7. Configurar entorno virtual del proyecto
echo ""
echo "📂 Configurando proyecto..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate

# 8. Instalar dependencias Python
echo ""
echo "📥 Instalando dependencias Python..."
pip install --upgrade pip
pip install -r requirements.txt

# 9. Crear carpetas necesarias
echo ""
echo "📁 Creando carpetas..."
mkdir -p run_logs transfer_logs descargas

# 10. Configurar Xvfb para que inicie automáticamente
echo ""
echo "🖥️  Configurando display virtual (Xvfb)..."
sudo tee /etc/systemd/system/xvfb.service > /dev/null <<EOF
[Unit]
Description=X Virtual Frame Buffer Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable xvfb
sudo systemctl start xvfb

# 11. Crear servicio systemd para Flask
echo ""
echo "⚙️  Creando servicio Flask..."
CURRENT_DIR=$(pwd)
sudo tee /etc/systemd/system/lohas-flask.service > /dev/null <<EOF
[Unit]
Description=Lohas Flask Server
After=network.target xvfb.service

[Service]
Type=simple
User=root
WorkingDirectory=$CURRENT_DIR
Environment="PATH=$CURRENT_DIR/.venv/bin"
Environment="PORT=5001"
Environment="HEADLESS=1"
Environment="DISPLAY=:99"
ExecStart=$CURRENT_DIR/.venv/bin/python3 $CURRENT_DIR/flask_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable lohas-flask

echo ""
echo "✅ ¡Instalación completada!"
echo ""
echo "📋 Servicios creados:"
echo "   • xvfb.service - Display virtual para Chrome"
echo "   • lohas-flask.service - Servidor Flask"
echo ""
echo "🎯 Comandos útiles:"
echo ""
echo "# Iniciar servidor:"
echo "sudo systemctl start lohas-flask"
echo ""
echo "# Ver estado:"
echo "sudo systemctl status lohas-flask"
echo ""
echo "# Ver logs en tiempo real:"
echo "sudo journalctl -u lohas-flask -f"
echo ""
echo "# Reiniciar servidor:"
echo "sudo systemctl restart lohas-flask"
echo ""
echo "# Detener servidor:"
echo "sudo systemctl stop lohas-flask"
echo ""
echo "🌐 Acceso:"
echo "http://$(curl -s ifconfig.me):5001"
echo ""
echo "💡 Tip: Guarda esa URL para acceder desde cualquier navegador"
echo ""

