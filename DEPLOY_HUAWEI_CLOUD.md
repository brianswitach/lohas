# ☁️ Despliegue en Huawei Cloud - Guía Completa

Esta guía te muestra cómo subir la aplicación Lohas Bot a Huawei Cloud para que esté disponible 24/7 y accesible desde cualquier navegador.

## 🎯 Arquitectura

```
Usuario → Internet → Huawei Cloud ECS → Flask Server (puerto 5001)
                            ↓
                       Chrome + Selenium
                            ↓
                       Archivos CSV en servidor
```

## 📋 Requisitos Previos

1. Cuenta de Huawei Cloud (https://www.huaweicloud.com/)
2. Tarjeta de crédito/débito para verificación
3. Acceso a la consola de Huawei Cloud

---

## 🚀 Paso a Paso - Configuración Inicial

### PASO 1: Crear Servidor ECS en Huawei Cloud

1. **Ingresar a Huawei Cloud Console**
   - Ve a: https://console.huaweicloud.com/
   - Inicia sesión con tu cuenta

2. **Ir a Elastic Cloud Server (ECS)**
   - En el menú superior: `Servicios` → `Cómputo` → `Elastic Cloud Server`
   - O busca "ECS" en el buscador

3. **Crear Nueva Instancia**
   - Click en `Buy ECS`
   - **Región**: Elige la más cercana (ej: LA-Santiago, LA-Mexico)
   
4. **Configuración Recomendada**:
   
   | Opción | Valor Recomendado |
   |--------|-------------------|
   | **Tipo** | General Computing (s6) |
   | **Especificación** | 2 vCPUs \| 4 GB RAM (mínimo para Chrome) |
   | **Sistema Operativo** | Ubuntu 22.04 LTS (64-bit) |
   | **Disco** | 40 GB SSD |
   | **Ancho de Banda** | 5 Mbps (ajustar según necesidad) |
   | **IP Pública** | ✅ Asignar IP Elástica |
   | **Grupo de Seguridad** | Crear nuevo (ver siguiente paso) |

5. **Configurar Grupo de Seguridad** (Firewall):
   
   Agregar estas reglas **Inbound** (entrantes):
   
   | Puerto | Protocolo | Origen | Descripción |
   |--------|-----------|--------|-------------|
   | 22 | TCP | 0.0.0.0/0 | SSH (administración) |
   | 5001 | TCP | 0.0.0.0/0 | Flask Server |
   | 80 | TCP | 0.0.0.0/0 | HTTP (opcional) |
   | 443 | TCP | 0.0.0.0/0 | HTTPS (opcional) |

6. **Crear Credenciales SSH**:
   - Selecciona "Crear nuevo par de claves"
   - Nombre: `lohas-key`
   - **IMPORTANTE**: Descarga el archivo `.pem` y guárdalo seguro

7. **Confirmar y Crear**:
   - Revisa el resumen
   - Click en `Submit`
   - Espera 2-3 minutos a que se cree

8. **Anotar IP Pública**:
   - Una vez creado, verás la IP pública (ej: `123.45.67.89`)
   - **Guarda esta IP**, la necesitarás

---

### PASO 2: Conectarse al Servidor

#### 🍎 Desde macOS / Linux:

```bash
# Dar permisos al archivo de clave
chmod 400 ~/Downloads/lohas-key.pem

# Conectarse vía SSH
ssh -i ~/Downloads/lohas-key.pem root@123.45.67.89
# (reemplaza 123.45.67.89 con tu IP pública)
```

#### 🪟 Desde Windows:

Opción A: **PuTTY** (más común)
1. Descargar PuTTY: https://www.putty.org/
2. Convertir `.pem` a `.ppk` con PuTTYgen
3. Conectarse con PuTTY usando la clave `.ppk`

Opción B: **PowerShell** (Windows 10+)
```powershell
ssh -i C:\Users\TuUsuario\Downloads\lohas-key.pem root@123.45.67.89
```

---

### PASO 3: Instalar Dependencias en el Servidor

Una vez conectado por SSH, ejecuta estos comandos:

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Python 3.9+
sudo apt install python3 python3-pip python3-venv -y

# Instalar Git
sudo apt install git -y

# Instalar Google Chrome (para Selenium)
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb -y

# Instalar ChromeDriver dependencies
sudo apt install -y chromium-chromedriver
sudo apt install -y xvfb libxi6 libgconf-2-4 libnss3 libxss1 libappindicator3-1 libatk-bridge2.0-0 libgtk-3-0 libgbm1

# Verificar instalación
python3 --version
google-chrome --version
git --version
```

---

### PASO 4: Clonar y Configurar el Proyecto

```bash
# Clonar repositorio
cd /home
git clone https://github.com/brianswitach/lohas.git
cd lohas

# Crear entorno virtual
python3 -m venv .venv

# Activar entorno virtual
source .venv/bin/activate

# Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt

# Crear carpetas necesarias
mkdir -p run_logs transfer_logs descargas
```

---

### PASO 5: Configurar Variables de Entorno

```bash
# Crear archivo de configuración
nano ~/.bashrc

# Agregar al final del archivo:
export HEADLESS=1
export DISPLAY=:99
export PORT=5001

# Guardar (Ctrl+O, Enter, Ctrl+X)

# Cargar configuración
source ~/.bashrc
```

---

### PASO 6: Iniciar Xvfb (Display Virtual para Chrome Headless)

```bash
# Instalar Xvfb si no está
sudo apt install xvfb -y

# Iniciar Xvfb en background
Xvfb :99 -screen 0 1920x1080x24 &

# Verificar que esté corriendo
ps aux | grep Xvfb
```

---

### PASO 7: Iniciar Flask Server

```bash
cd /home/lohas
source .venv/bin/activate

# Opción A: Ejecutar en foreground (para probar)
PORT=5001 python3 flask_server.py

# Opción B: Ejecutar en background con nohup (producción)
nohup PORT=5001 python3 flask_server.py > flask.log 2>&1 &

# Ver log en tiempo real
tail -f flask.log
```

---

### PASO 8: Mantener el Servidor Corriendo (Producción)

Para que el servidor se mantenga corriendo incluso si se cierra SSH, usa `systemd`:

```bash
# Crear servicio systemd
sudo nano /etc/systemd/system/lohas-flask.service
```

**Contenido del archivo**:
```ini
[Unit]
Description=Lohas Flask Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/lohas
Environment="PATH=/home/lohas/.venv/bin"
Environment="PORT=5001"
Environment="HEADLESS=1"
Environment="DISPLAY=:99"
ExecStart=/home/lohas/.venv/bin/python3 /home/lohas/flask_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Comandos para gestionar el servicio**:
```bash
# Recargar systemd
sudo systemctl daemon-reload

# Habilitar servicio (auto-inicio)
sudo systemctl enable lohas-flask

# Iniciar servicio
sudo systemctl start lohas-flask

# Ver estado
sudo systemctl status lohas-flask

# Ver logs
sudo journalctl -u lohas-flask -f

# Reiniciar servicio
sudo systemctl restart lohas-flask

# Detener servicio
sudo systemctl stop lohas-flask
```

---

### PASO 9: Acceder desde Internet

Una vez que el servidor esté corriendo:

1. **Encuentra tu IP Pública**:
   ```bash
   curl ifconfig.me
   # O verla en la consola de Huawei Cloud
   ```

2. **Accede desde tu navegador**:
   ```
   http://TU_IP_PUBLICA:5001
   ```
   
   Ejemplo: `http://123.45.67.89:5001`

3. **Compartir el link**:
   - Cualquiera puede acceder: `http://123.45.67.89:5001`
   - Ejecutar bots desde el navegador

---

## 🔒 Seguridad (IMPORTANTE)

### 1. Cambiar Credenciales Hardcodeadas

⚠️ **ANTES de subir a producción**, cambia las credenciales en el código:

```bash
cd /home/lohas
nano bot.py  # Editar credenciales
nano bot_csv.py  # Editar credenciales
```

### 2. Usar Variables de Entorno (Recomendado)

Crea un archivo `.env`:
```bash
nano /home/lohas/.env
```

Contenido:
```
USER_B=tu_usuario
PASS_B=tu_contraseña
GMAIL_USER=tu_email@gmail.com
GMAIL_PASS=tu_app_password
```

### 3. Agregar Autenticación al Flask

Para evitar que cualquiera acceda, agrega autenticación básica:

```bash
pip install flask-httpauth
```

### 4. Usar HTTPS (Opcional pero Recomendado)

Instala un certificado SSL con Let's Encrypt + Nginx.

---

## 💰 Costos Estimados (Huawei Cloud)

| Recurso | Especificación | Costo Mensual Aproximado |
|---------|----------------|--------------------------|
| ECS | 2 vCPUs, 4GB RAM | ~$15-25 USD |
| Disco | 40 GB SSD | ~$4-6 USD |
| Ancho de Banda | 5 Mbps | ~$5-10 USD |
| **TOTAL** | - | **~$25-40 USD/mes** |

💡 **Tip**: Huawei Cloud ofrece créditos gratis para nuevos usuarios (~$300 USD por 1 año).

---

## 🔄 Actualizar el Código en el Servidor

Cuando hagas cambios en GitHub:

```bash
# Conectarse al servidor
ssh -i ~/Downloads/lohas-key.pem root@TU_IP

# Ir al proyecto
cd /home/lohas

# Obtener últimos cambios
git pull origin main

# Reiniciar servicio
sudo systemctl restart lohas-flask
```

---

## 🐛 Troubleshooting

### Error: "Chrome crashed"
```bash
# Instalar dependencias faltantes
sudo apt install -y libgbm1 libasound2
```

### Error: "Cannot open display"
```bash
# Reiniciar Xvfb
killall Xvfb
Xvfb :99 -screen 0 1920x1080x24 &
```

### Error: "Port 5001 already in use"
```bash
# Ver qué proceso usa el puerto
sudo lsof -i :5001

# Matar proceso
sudo kill -9 <PID>
```

### Ver logs del servidor
```bash
# Logs del servicio systemd
sudo journalctl -u lohas-flask -f

# Logs de Flask
tail -f /home/lohas/flask.log
```

---

## 🌐 Dominio Personalizado (Opcional)

En lugar de `http://123.45.67.89:5001`, puedes tener `https://lohas.tudominio.com`:

1. Comprar dominio (ej: Namecheap, GoDaddy)
2. Configurar DNS apuntando a la IP del servidor
3. Instalar Nginx como proxy reverso
4. Instalar certificado SSL con Let's Encrypt

---

## 📊 Monitoreo

### Ver estado del servidor
```bash
# CPU y memoria
htop

# Espacio en disco
df -h

# Procesos de Python
ps aux | grep python
```

### Logs de transferencias
```bash
# Ver últimas transferencias
tail -20 /home/lohas/transfer_logs/transferencias_*.txt

# Ver logs de run
ls -lah /home/lohas/run_logs/
```

---

## ⚡ Quick Start (Resumen)

```bash
# 1. Crear ECS en Huawei Cloud (Ubuntu 22.04, 2vCPUs, 4GB RAM)
# 2. Conectarse
ssh -i lohas-key.pem root@TU_IP

# 3. Instalar todo
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git wget
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
sudo apt install -y xvfb libgbm1

# 4. Clonar proyecto
cd /home
git clone https://github.com/brianswitach/lohas.git
cd lohas

# 5. Configurar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 6. Iniciar Xvfb
Xvfb :99 -screen 0 1920x1080x24 &

# 7. Iniciar Flask
export DISPLAY=:99
export HEADLESS=1
nohup PORT=5001 python3 flask_server.py > flask.log 2>&1 &

# 8. Acceder desde navegador
# http://TU_IP_PUBLICA:5001
```

---

## 🎉 ¡Listo!

Ahora tu aplicación está en la nube y cualquiera con el link puede usarla:

- **URL**: `http://TU_IP_PUBLICA:5001`
- **Disponibilidad**: 24/7
- **Acceso**: Desde cualquier navegador, cualquier lugar

---

## 📞 Notas Importantes

1. **Credenciales**: Cambia usuario/contraseña hardcodeados en `bot.py` y `bot_csv.py`
2. **Seguridad**: Considera agregar autenticación al Flask server
3. **Backups**: Haz backup regular de `transfer_logs/` y configuraciones
4. **Monitoreo**: Revisa logs periódicamente para detectar errores
5. **Costos**: Monitorea el uso para controlar gastos

---

## 🔗 Links Útiles

- Huawei Cloud Console: https://console.huaweicloud.com/
- Documentación ECS: https://support.huaweicloud.com/ecs/index.html
- Calculadora de Precios: https://www.huaweicloud.com/pricing.html
- Soporte: https://console.huaweicloud.com/ticket/

---

## 🆘 Ayuda

Si necesitas ayuda durante el proceso:
1. Revisa la documentación oficial de Huawei Cloud
2. Contacta al soporte de Huawei Cloud (tienen chat 24/7)
3. Consulta los logs del servidor para debuggear problemas

¡Éxito con el despliegue! 🚀

