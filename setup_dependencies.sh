#!/bin/bash
# Script de instalación de dependencias del sistema (macOS)
# Instala: Homebrew, Python, Git, GitHub Desktop, Visual Studio Code

echo "🚀 Instalando dependencias del sistema..."
echo ""

# 1. Verificar si estamos en macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "⚠️  Este script está diseñado para macOS"
    echo "   Para Windows/Linux, instala manualmente:"
    echo "   - Python 3.9+: https://www.python.org/downloads/"
    echo "   - Git: https://git-scm.com/downloads"
    echo "   - VS Code: https://code.visualstudio.com/"
    echo "   - GitHub Desktop: https://desktop.github.com/"
    exit 1
fi

# 2. Instalar Homebrew (si no está instalado)
if ! command -v brew &> /dev/null; then
    echo "📦 Instalando Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Configurar Homebrew en PATH
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "✅ Homebrew ya está instalado"
fi

# 3. Instalar Python 3.9
echo ""
echo "🐍 Instalando Python 3.9..."
if ! command -v python3.9 &> /dev/null; then
    brew install python@3.9
    echo "✅ Python 3.9 instalado"
else
    echo "✅ Python 3.9 ya está instalado"
fi

# 4. Instalar Git
echo ""
echo "📝 Instalando Git..."
if ! command -v git &> /dev/null; then
    brew install git
    echo "✅ Git instalado"
else
    echo "✅ Git ya está instalado: $(git --version)"
fi

# 5. Instalar Visual Studio Code
echo ""
echo "💻 Instalando Visual Studio Code..."
if ! command -v code &> /dev/null; then
    brew install --cask visual-studio-code
    echo "✅ Visual Studio Code instalado"
else
    echo "✅ Visual Studio Code ya está instalado"
fi

# 6. Instalar GitHub Desktop
echo ""
echo "🐙 Instalando GitHub Desktop..."
if [ ! -d "/Applications/GitHub Desktop.app" ]; then
    brew install --cask github
    echo "✅ GitHub Desktop instalado"
else
    echo "✅ GitHub Desktop ya está instalado"
fi

# 7. Instalar Google Chrome (necesario para Selenium)
echo ""
echo "🌐 Instalando Google Chrome..."
if [ ! -d "/Applications/Google Chrome.app" ]; then
    brew install --cask google-chrome
    echo "✅ Google Chrome instalado"
else
    echo "✅ Google Chrome ya está instalado"
fi

echo ""
echo "✅ ¡Todas las dependencias del sistema están instaladas!"
echo ""
echo "📋 Software instalado:"
echo "   • Homebrew (gestor de paquetes)"
echo "   • Python 3.9"
echo "   • Git"
echo "   • Visual Studio Code"
echo "   • GitHub Desktop"
echo "   • Google Chrome"
echo ""
echo "🎯 Próximos pasos:"
echo "1. Abre GitHub Desktop"
echo "2. Clona el repositorio: https://github.com/brianswitach/lohas"
echo "3. Abre la carpeta del proyecto en VS Code"
echo "4. En la terminal de VS Code ejecuta: ./setup.sh"
echo ""

