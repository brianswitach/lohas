# Script de instalación de dependencias del sistema (Windows)
# Instala: Chocolatey, Python, Git, GitHub Desktop, Visual Studio Code, Google Chrome
# Ejecutar como Administrador: PowerShell -ExecutionPolicy Bypass -File setup_dependencies_windows.ps1

Write-Host "🚀 Instalando dependencias del sistema (Windows)..." -ForegroundColor Green
Write-Host ""

# 1. Verificar si se ejecuta como administrador
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "⚠️  Este script debe ejecutarse como Administrador" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Pasos:" -ForegroundColor Cyan
    Write-Host "1. Clic derecho en 'Windows PowerShell'"
    Write-Host "2. Seleccionar 'Ejecutar como administrador'"
    Write-Host "3. Ejecutar: Set-ExecutionPolicy Bypass -Scope Process -Force"
    Write-Host "4. Ejecutar: .\setup_dependencies_windows.ps1"
    Write-Host ""
    Read-Host "Presiona Enter para salir"
    exit 1
}

# 2. Instalar Chocolatey (gestor de paquetes para Windows)
Write-Host "📦 Verificando Chocolatey..." -ForegroundColor Cyan
if (!(Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "Instalando Chocolatey..." -ForegroundColor Yellow
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    Write-Host "✅ Chocolatey instalado" -ForegroundColor Green
} else {
    Write-Host "✅ Chocolatey ya está instalado" -ForegroundColor Green
}

# Refrescar variables de entorno
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# 3. Instalar Python 3.9
Write-Host ""
Write-Host "🐍 Instalando Python 3.9..." -ForegroundColor Cyan
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    choco install python39 -y
    Write-Host "✅ Python 3.9 instalado" -ForegroundColor Green
    # Refrescar PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
} else {
    $pythonVersion = python --version
    Write-Host "✅ Python ya está instalado: $pythonVersion" -ForegroundColor Green
}

# 4. Instalar Git
Write-Host ""
Write-Host "📝 Instalando Git..." -ForegroundColor Cyan
if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    choco install git -y
    Write-Host "✅ Git instalado" -ForegroundColor Green
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
} else {
    $gitVersion = git --version
    Write-Host "✅ Git ya está instalado: $gitVersion" -ForegroundColor Green
}

# 5. Instalar Visual Studio Code
Write-Host ""
Write-Host "💻 Instalando Visual Studio Code..." -ForegroundColor Cyan
if (!(Test-Path "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe")) {
    choco install vscode -y
    Write-Host "✅ Visual Studio Code instalado" -ForegroundColor Green
} else {
    Write-Host "✅ Visual Studio Code ya está instalado" -ForegroundColor Green
}

# 6. Instalar GitHub Desktop
Write-Host ""
Write-Host "🐙 Instalando GitHub Desktop..." -ForegroundColor Cyan
if (!(Test-Path "$env:LOCALAPPDATA\GitHubDesktop\GitHubDesktop.exe")) {
    choco install github-desktop -y
    Write-Host "✅ GitHub Desktop instalado" -ForegroundColor Green
} else {
    Write-Host "✅ GitHub Desktop ya está instalado" -ForegroundColor Green
}

# 7. Instalar Google Chrome
Write-Host ""
Write-Host "🌐 Instalando Google Chrome..." -ForegroundColor Cyan
if (!(Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe")) {
    choco install googlechrome -y
    Write-Host "✅ Google Chrome instalado" -ForegroundColor Green
} else {
    Write-Host "✅ Google Chrome ya está instalado" -ForegroundColor Green
}

Write-Host ""
Write-Host "✅ ¡Todas las dependencias del sistema están instaladas!" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Software instalado:" -ForegroundColor Cyan
Write-Host "   • Chocolatey (gestor de paquetes)"
Write-Host "   • Python 3.9"
Write-Host "   • Git"
Write-Host "   • Visual Studio Code"
Write-Host "   • GitHub Desktop"
Write-Host "   • Google Chrome"
Write-Host ""
Write-Host "🎯 Próximos pasos:" -ForegroundColor Yellow
Write-Host "1. Cierra y abre una nueva ventana de PowerShell (para refrescar PATH)"
Write-Host "2. Abre GitHub Desktop"
Write-Host "3. Clona el repositorio: https://github.com/brianswitach/lohas"
Write-Host "4. Abre la carpeta del proyecto en VS Code"
Write-Host "5. En la terminal de VS Code ejecuta: .\setup_windows.bat"
Write-Host ""
Read-Host "Presiona Enter para salir"

