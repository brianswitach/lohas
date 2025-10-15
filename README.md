# 🤖 Lohas Bot - Automatización de Transferencias

Sistema de automatización para transferencias bancarias y exportación de datos.

## 📋 Requisitos

- Python 3.9 o superior
- Google Chrome
- Visual Studio Code (recomendado)
- Git
- GitHub Desktop (opcional)

## 🚀 Instalación Rápida

### Opción 1: Instalación Completa Desde Cero (macOS)

Si **NO TIENES NADA INSTALADO** (primera vez):

```bash
# 1. Descargar el repositorio como ZIP desde GitHub
#    https://github.com/brianswitach/lohas
#    Descomprime el ZIP

# 2. Abrir Terminal y navegar a la carpeta
cd ~/Downloads/lohas-main  # (ajusta la ruta según dónde lo descargaste)

# 3. Instalar TODO (Python, Git, VS Code, GitHub Desktop, Chrome)
chmod +x setup_dependencies.sh
./setup_dependencies.sh

# 4. Configurar el proyecto
chmod +x setup.sh
./setup.sh
```

### Opción 2: Ya Tengo Python/Git Instalado

```bash
# Clonar el repositorio
git clone https://github.com/brianswitach/lohas.git
cd lohas

# Ejecutar script de instalación
chmod +x setup.sh
./setup.sh
```

### Opción 3: Instalación Manual

```bash
# Clonar el repositorio
git clone https://github.com/brianswitach/lohas.git
cd lohas

# Crear entorno virtual
python3 -m venv .venv

# Activar entorno virtual
source .venv/bin/activate  # En macOS/Linux
# o
.venv\Scripts\activate     # En Windows

# Instalar dependencias
pip install -r requirements.txt

# Crear carpetas necesarias
mkdir -p run_logs transfer_logs descargas
```

## 🎯 Uso

### Iniciar el Servidor

```bash
# Activar entorno virtual (si no está activado)
source .venv/bin/activate

# Iniciar servidor Flask
PORT=5001 python3 flask_server.py
```

### Acceder a la Interfaz Web

Abre tu navegador en: **http://localhost:5001**

## 🤖 Bots Disponibles

### 1. Bot Transferencias

**Función**: Ejecuta transferencias bancarias automáticamente desde un archivo CSV.

**Flujo**:
1. Click en "Bot Transferencias"
2. Seleccionar archivo CSV con las transferencias
3. El bot:
   - Hace login automático
   - Maneja 2FA con OTP de Gmail
   - Verifica saldo de cuentas origen
   - Ejecuta cada transferencia
   - Guarda historial en `transfer_logs/`

**Formato del CSV**:
```csv
ID,CBU_ORIGEN,CBU_DESTINO,DOCUMENTO,NOMBRE,MONTO,REFERENCIA
1,0000156005165448957004,0000003100163899509815,27309744670,Ana Alicia Diaz,20000.00,refund
```

### 2. Bot CSV

**Función**: Exporta datos filtrados de la plataforma a CSV.

**Flujo**:
1. Click en "Bot CSV"
2. Seleccionar cuenta y rango de fechas
3. El bot:
   - Hace login automático
   - Aplica filtros seleccionados
   - Exporta datos a CSV
   - Guarda archivo en `descargas/`

## 📁 Estructura del Proyecto

```
lohas/
├── bot.py                 # Bot de transferencias
├── bot_csv.py            # Bot de exportación CSV
├── flask_server.py       # Servidor web
├── requirements.txt      # Dependencias Python
├── setup.sh             # Script de instalación
├── run_logs/            # Logs de ejecución
├── transfer_logs/       # Historial de transferencias
└── descargas/           # Archivos CSV exportados
```

## 📝 Historial de Transferencias

Cada ejecución crea un archivo de log en `transfer_logs/` con formato:

```
================================================================================
HISTORIAL DE TRANSFERENCIAS - 15/01/2025 14:30:52
================================================================================

Transferencia #1: COMPLETADA
  CBU de ORIGEN:  0000155300000000000871
  CBU de DESTINO: 0000003100163899509815
  MONTO:          $20000.00
  Fecha/Hora:     15/01/2025 14:31:15
--------------------------------------------------------------------------------
```

## 🔧 Configuración

Las credenciales y configuraciones están hardcodeadas en `bot.py` y `bot_csv.py`. Para modificarlas, edita las siguientes líneas:

```python
# Login
USER_B = "tu_usuario"
PASS_B = "tu_contraseña"

# Gmail (para OTP)
GMAIL_USER = "tu_email@gmail.com"
GMAIL_PASS = "tu_app_password"
```

## 🌿 Ramas

- **main**: Rama principal con desarrollo activo
- **demo-version**: Rama estable congelada para demos

Para cambiar de rama:
```bash
git checkout demo-version  # Para demo
git checkout main          # Para desarrollo
```

## 🐛 Troubleshooting

### Error: "ChromeDriver not found"
Solución: El paquete `webdriver-manager` lo descarga automáticamente. Si falla, verifica tu conexión a internet.

### Error: "No se pudo conectar a Gmail"
Solución: Verifica que uses una **App Password** de Gmail, no tu contraseña normal.

### Error: "Port already in use"
Solución: Cambia el puerto: `PORT=5002 python3 flask_server.py`

## 📞 Soporte

Para problemas o preguntas, contacta al desarrollador.

## 📄 Licencia

Proyecto privado - Todos los derechos reservados.

