#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot_csv.py – Login + 2-FA OTP y filtrado de la grilla de movimientos
con fechas provistas por el usuario (DATE_FROM / DATE_TO).

Modo SCAN_ONLY=1  → solamente extrae el listado de cuentas (JSON por stdout).
HEADLESS          → si está en 0 / false / no ⇒ abre navegador visible;
                    en cualquier otro valor ⇒ headless (default).

Flujo normal (incluye todas las pausas solicitadas)
──────────────────────────────────────────────────────────────────────────────
1.  Abre https://app.lohas.eco/app_Login
2.  Completa usuario y contraseña y pulsa “Ingresar”
3.  Espera la pantalla de 2-FA
4.  Lee el OTP desde Gmail (IMAP) y lo pega
5.  Pausa 3 s y pulsa “Aceptar” (ID sc_submit_ajax_bot)
6.  Pausa 3 s y vuelve a pulsar **el mismo** “Aceptar”
7.  Pausa 3 s y navega a /grid_movimientos_cuenta_usuario/
8.  Pausa 15 s para que la grilla cargue
9.  Pausa 3 s y rellena los 6 campos de fecha (*Desde* y *Hasta*)
10. Pausa 5 s y termina — **no** pulsa “Búsqueda”
"""

from __future__ import annotations

import builtins
import email, imaplib, os, re, sys, time, json
from typing import Callable, Optional, Tuple

from selenium import webdriver
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

from bot import get_latest_otp_gmail

# ───────────────────────── PRINT MÍNIMO ──────────────────────────────────────
import sys

_orig_print = builtins.print
def _minimal_print(*a, **kw):
    if a and str(a[0]).startswith(("TRANSFE_START:", "TRANSFE_DONE:", "TRANSFE_FAILED:", "DEBUG:")):
        # Para logs DEBUG, usar sys.stdout.write con flush forzado
        if str(a[0]).startswith("DEBUG:"):
            message = ' '.join(str(x) for x in a)
            sys.stdout.write(message + '\n')
            sys.stdout.flush()
        else:
            _orig_print(*a, **kw)
builtins.print = _minimal_print

# ─────────────────────────
#  CONFIG & CONSTANTES WEB ───────────────────────────
URL_B            = "https://app.lohas.eco/app_Login"
USER_B           = "briansw"
PASS_B           = "lJ63STxqrXulcuhwizX3"
FIELD_LOGIN_ID   = "id_sc_field_login"
FIELD_PASS_ID    = "id_sc_field_pswd"
LOGIN_BTN_CSS    = "input.button[onclick*='nm_atualiza']"

OTP_FIELD_ID     = "id_sc_field_code"
OTP_FIELD_NAME   = "code"

ACCEPT_BTN_ID    = "sc_submit_ajax_bot"
TRANSFER_URL     = "https://app.lohas.eco/grid_movimientos_cuenta_usuario/"

# IDs de los 6 inputs de fecha
DIA_DESDE  = "SC_fecha_hora_dia"
MES_DESDE  = "SC_fecha_hora_mes"
ANO_DESDE  = "SC_fecha_hora_ano"
DIA_HASTA  = "SC_fecha_hora_input_2_dia"
MES_HASTA  = "SC_fecha_hora_input_2_mes"
ANO_HASTA  = "SC_fecha_hora_input_2_ano"

# HEADLESS configurable por entorno  (default: sí es headless)
HEADLESS = os.getenv("HEADLESS", "0").lower() not in ("0", "false", "no")

# ───────────────────────── CONSTANTES IMAP ───────────────────────────────────
GMAIL_IMAP_HOST  = "imap.gmail.com"
GMAIL_USER       = "brianswitach@gmail.com"
GMAIL_PASS       = "nlrsuamujfrictoh"
KNOWN_SENDER     = "sistema@lohas.eco"

OTP_PHRASE_RE  = re.compile(r"su\s+c[oó]digo\s+de\s+inicio\s+de\s+sesi[oó]n\s+es\s*[:\s,-]*?(\d{4,8})", re.I)
OTP_DIGITS_RE  = re.compile(r"\b(\d{4,8})\b")

# Selector CSS para el <select> de cuentas
ACCOUNTS_SELECTOR = os.getenv(
    "ACCOUNTS_SELECTOR",
    "select#account, select[name='account'], select.accounts, select[id*='cuenta']"
)

# ──────────────────────────── IMAP HELPERS ───────────────────────────────────
def imap_connect() -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST)
    m.login(GMAIL_USER, GMAIL_PASS)
    m.select("INBOX")
    return m

def uid_fetch_text(m: imaplib.IMAP4_SSL, uid: int) -> Tuple[str, str]:
    _, data = m.uid("FETCH", str(uid), "(RFC822)")
    raw = data[0][1]
    msg = email.message_from_bytes(raw)
    subj = str(email.header.make_header(email.header.decode_header(msg.get("Subject", ""))))
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp  = (part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in disp:
                body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                break
            if ctype == "text/html" and not body:
                html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                body = re.sub(r"(?s)<[^>]+>", " ", html)
    else:
        body = (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", "ignore")
    return subj, body

def extract_otp(subj: str, body: str) -> Optional[str]:
    m = OTP_PHRASE_RE.search(body) or OTP_PHRASE_RE.search(subj)
    if m:
        return m.group(1)
    m = OTP_DIGITS_RE.search(body) or OTP_DIGITS_RE.search(subj)
    return m.group(1) if m else None

def wait_for_otp(since_uid: int, timeout: int = 120, poll: float = 2.0) -> str:
    m = imap_connect()
    start = time.time()
    try:
        while time.time() - start < timeout:
            _, data = m.uid("SEARCH", None, 'UNSEEN', 'FROM', f'"{KNOWN_SENDER}"')
            uids = [int(x) for x in (data[0] or b"").split()][::-1]
            if not uids:
                _, data = m.uid("SEARCH", None, "ALL")
                uids = [int(x) for x in (data[0] or b"").split()][::-1]
            for uid in uids:
                if uid <= since_uid:
                    break
                subj, body = uid_fetch_text(m, uid)
                otp = extract_otp(subj, body)
                if otp:
                    return otp
            time.sleep(poll)
            m.select("INBOX")
        raise TimeoutError("OTP timeout")
    finally:
        try: m.logout()
        except: pass

# ─────────────────────────── SELENIUM HELPERS ───────────────────────────────
def _find_in_shadow_dom(drv: Chrome, css: str):
    js = """
    const sel = arguments[0];
    function deep(node){
      if(node.querySelector && node.querySelector(sel)) return node.querySelector(sel);
      for(const c of node.children||[]){
        const r = deep(c.shadowRoot||c) || deep(c);
        if(r) return r;
      }
      return null;
    }
    return deep(document);
    """
    try:    return drv.execute_script(js, css)
    except: return None

def _recursive_frames(drv: Chrome, finder: Callable[[], Optional[object]], depth=0, maxd=5):
    try:
        el = finder()
        if el: return el
    except: pass
    if depth >= maxd: return None
    for fr in drv.find_elements(By.TAG_NAME, "iframe"):
        try:
            drv.switch_to.frame(fr)
            el = _recursive_frames(drv, finder, depth+1, maxd)
            drv.switch_to.parent_frame()
            if el: return el
        except:
            try: drv.switch_to.default_content()
            except: pass
    return None

def locate(drv: Chrome, by: By, val: str, timeout=10):
    limit = time.time() + timeout
    while time.time() < limit:
        drv.switch_to.default_content()
        el = _recursive_frames(drv, lambda: drv.find_element(by, val))
        if el: return el
        el = _find_in_shadow_dom(drv, val)
        if el: return el
        time.sleep(0.3)
    return None

def safe_click(drv: Chrome, el):
    try:
        el.click(); return True
    except:
        try: drv.execute_script("arguments[0].click()", el); return True
        except: return False

def find_otp_input_and_debug(driver: webdriver.Chrome, wait: WebDriverWait, timeout: int = 10):
    print(f"DEBUG: Iniciando búsqueda de OTP con timeout={timeout}")
    print(f"DEBUG: OTP_FIELD_ID = '{OTP_FIELD_ID}'")
    print(f"DEBUG: OTP_FIELD_NAME = '{OTP_FIELD_NAME}'")
    print(f"DEBUG: URL actual: {driver.current_url}")
    
    # 1) Buscar por ID
    print(f"DEBUG: 1) Buscando OTP por ID: '{OTP_FIELD_ID}'")
    try:
        el = driver.find_element(By.ID, OTP_FIELD_ID)
        print(f"DEBUG: Elemento encontrado por ID: {el}")
        print(f"DEBUG: Elemento visible: {el.is_displayed()}")
        print(f"DEBUG: Elemento habilitado: {el.is_enabled()}")
        if el and el.is_displayed():
            print("DEBUG: ✅ OTP encontrado por ID y visible")
            return el
        else:
            print("DEBUG: ❌ OTP encontrado por ID pero no visible")
    except Exception as e:
        print(f"DEBUG: ❌ Error buscando OTP por ID: {e}")

    # 2) Buscar por NAME
    print(f"DEBUG: 2) Buscando OTP por NAME: '{OTP_FIELD_NAME}'")
    try:
        el = driver.find_element(By.NAME, OTP_FIELD_NAME)
        print(f"DEBUG: Elemento encontrado por NAME: {el}")
        print(f"DEBUG: Elemento visible: {el.is_displayed()}")
        print(f"DEBUG: Elemento habilitado: {el.is_enabled()}")
        if el and el.is_displayed():
            print("DEBUG: ✅ OTP encontrado por NAME y visible")
            return el
        else:
            print("DEBUG: ❌ OTP encontrado por NAME pero no visible")
    except Exception as e:
        print(f"DEBUG: ❌ Error buscando OTP por NAME: {e}")

    # 3) Buscar en iframes
    print("DEBUG: 3) Buscando OTP en iframes")
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"DEBUG: Encontrados {len(iframes)} iframes")
        for i, fr in enumerate(iframes):
            print(f"DEBUG: Procesando iframe {i+1}/{len(iframes)}")
            try:
                driver.switch_to.frame(fr)
                print(f"DEBUG: Cambiado a iframe {i+1}")
                
                # Buscar por ID en iframe
                try:
                    el = driver.find_element(By.ID, OTP_FIELD_ID)
                    print(f"DEBUG: OTP encontrado por ID en iframe {i+1}: {el}")
                    if el and el.is_displayed():
                        print("DEBUG: ✅ OTP encontrado por ID en iframe y visible")
                        driver.switch_to.default_content()
                        return el
                except Exception as e:
                    print(f"DEBUG: ❌ Error buscando OTP por ID en iframe {i+1}: {e}")
                
                # Buscar por NAME en iframe
                try:
                    el = driver.find_element(By.NAME, OTP_FIELD_NAME)
                    print(f"DEBUG: OTP encontrado por NAME en iframe {i+1}: {el}")
                    if el and el.is_displayed():
                        print("DEBUG: ✅ OTP encontrado por NAME en iframe y visible")
                        driver.switch_to.default_content()
                        return el
                except Exception as e:
                    print(f"DEBUG: ❌ Error buscando OTP por NAME en iframe {i+1}: {e}")
                
                # Buscar inputs genéricos en iframe
                try:
                    cand = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='tel'], input[inputmode='numeric'], input[type='number']")
                    print(f"DEBUG: Encontrados {len(cand)} inputs genéricos en iframe {i+1}")
                    for j, el in enumerate(cand):
                        try:
                            if el.is_displayed():
                                print(f"DEBUG: ✅ Input genérico {j+1} visible en iframe {i+1}: {el}")
                                driver.switch_to.default_content()
                                return el
                        except Exception as e:
                            print(f"DEBUG: ❌ Error verificando input genérico {j+1} en iframe {i+1}: {e}")
                            continue
                except Exception as e:
                    print(f"DEBUG: ❌ Error buscando inputs genéricos en iframe {i+1}: {e}")
                
                driver.switch_to.default_content()
                print(f"DEBUG: Regresado a contenido principal desde iframe {i+1}")
            except Exception as e:
                print(f"DEBUG: ❌ Error procesando iframe {i+1}: {e}")
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
    except Exception as e:
        print(f"DEBUG: ❌ Error general en búsqueda de iframes: {e}")

    # 4) Heurística JavaScript
    print("DEBUG: 4) Ejecutando heurística JavaScript")
    js = r"""
    (function(){
      const inputs = Array.from(document.querySelectorAll('input'));
      console.log('Total inputs encontrados:', inputs.length);
      
      function score(el){
        const type = (el.getAttribute('type')||'').toLowerCase();
        const max  = el.getAttribute('maxlength')||'';
        const name = (el.getAttribute('name')||'').toLowerCase();
        const id   = (el.getAttribute('id')||'').toLowerCase();
        const ph   = (el.getAttribute('placeholder')||'').toLowerCase();
        let s = 0;
        
        if(type==='tel' || type==='text' || type==='') s += 1;
        if(/\b(otp|token|codigo|código|code|clave|pin)\b/.test(name)) s += 6;
        if(/\b(otp|token|codigo|código|code|clave|pin)\b/.test(id))   s += 6;
        if(/\b(otp|token|codigo|código|code|clave|pin)\b/.test(ph))   s += 6;
        if(max==='6' || max==='8' || max==='4') s += 3;
        try{const rect = el.getBoundingClientRect(); if(rect.width > 0 && rect.height > 0) s += 2;}catch(e){}
        if(type==='hidden') s -= 100;
        if(/\bcsrf\b/.test(name) || /\bcsrf\b/.test(id)) s -= 100;
        
        return s;
      }
      
      const scored = inputs.map(i => ({el: i, sc: score(i)})).sort((a,b)=>b.sc - a.sc);
      console.log('Top 5 inputs con mejor score:');
      scored.slice(0, 5).forEach((item, idx) => {
        const el = item.el;
        console.log(`${idx+1}. Score: ${item.sc}, Type: ${el.type}, ID: ${el.id}, Name: ${el.name}, Placeholder: ${el.placeholder}`);
      });
      
      if(scored.length === 0) return null;
      return scored[0].sc > 0 ? scored[0].el : null;
    })();
    """
    try:
        print("DEBUG: Ejecutando script JavaScript...")
        el = driver.execute_script(js)
        print(f"DEBUG: Script JS ejecutado, resultado: {el}")
        if el:
            try:
                print(f"DEBUG: Elemento JS encontrado: {el}")
                print(f"DEBUG: Elemento JS visible: {el.is_displayed()}")
                if el.is_displayed():
                    print("DEBUG: ✅ OTP encontrado por heurística JS y visible")
                    return el
                else:
                    print("DEBUG: ❌ OTP encontrado por heurística JS pero no visible")
            except Exception as e:
                print(f"DEBUG: ❌ Error verificando elemento JS: {e}")
        else:
            print("DEBUG: ❌ Heurística JS no encontró ningún elemento")
    except Exception as e:
        print(f"DEBUG: ❌ Error ejecutando heurística JS: {e}")

    # 5) Listar todos los inputs disponibles
    print("DEBUG: 5) Listando todos los inputs disponibles en la página")
    try:
        all_inputs = driver.find_elements(By.TAG_NAME, "input")
        print(f"DEBUG: Total de inputs encontrados: {len(all_inputs)}")
        for i, inp in enumerate(all_inputs[:10]):  # Solo los primeros 10
            try:
                print(f"DEBUG: Input {i+1}: type='{inp.get_attribute('type')}', id='{inp.get_attribute('id')}', name='{inp.get_attribute('name')}', placeholder='{inp.get_attribute('placeholder')}', visible={inp.is_displayed()}")
            except Exception as e:
                print(f"DEBUG: Error obteniendo atributos del input {i+1}: {e}")
    except Exception as e:
        print(f"DEBUG: ❌ Error listando inputs: {e}")

    # último recurso: devolver None (no preguntar al usuario)
    print("DEBUG: ❌ No se encontró input OTP en ningún método")
    raise TimeoutException("No se encontró input OTP automáticamente")

def click_accept_button(drv: Chrome, wait, timeout=15.0):
    try:
        el = wait.until(EC.element_to_be_clickable((By.ID, ACCEPT_BTN_ID)))
        el.click()
        return True
    except Exception:
        return False

def click_confirm_button(drv: Chrome, wait, timeout=15.0):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        # 1) Intento en el contexto principal
        try:
            drv.switch_to.default_content()
            el = WebDriverWait(drv, 2).until(EC.element_to_be_clickable((By.ID, "sub_form_b")))
            el.click(); return True
        except Exception as e:
            last_error = e

        # 2) Intentar en iframe específico TB_iframeContent
        try:
            drv.switch_to.default_content()
            for fr in drv.find_elements(By.TAG_NAME, "iframe"):
                try:
                    fid = (fr.get_attribute("id") or "") + " " + (fr.get_attribute("name") or "")
                    src = fr.get_attribute("src") or ""
                    if ("TB_iframeContent" in fid) or ("app_logged" in src):
                        drv.switch_to.frame(fr)
                        try:
                            el = WebDriverWait(drv, 3).until(EC.element_to_be_clickable((By.ID, "sub_form_b")))
                            el.click(); drv.switch_to.default_content(); return True
                        except Exception as e2:
                            last_error = e2
                        finally:
                            try: drv.switch_to.default_content()
                            except Exception: pass
                except Exception as e:
                    last_error = e

        except Exception as e:
            last_error = e

        # 3) Intentar en cualquier iframe (barrido general)
        try:
            drv.switch_to.default_content()
            iframes = drv.find_elements(By.TAG_NAME, "iframe")
            for fr in iframes:
                try:
                    drv.switch_to.frame(fr)
                    try:
                        el = WebDriverWait(drv, 2).until(EC.element_to_be_clickable((By.ID, "sub_form_b")))
                        el.click(); drv.switch_to.default_content(); return True
                    except Exception as e3:
                        last_error = e3
                    finally:
                        try: drv.switch_to.default_content()
                        except Exception: pass
                except Exception as e:
                    last_error = e
        except Exception as e:
            last_error = e

        time.sleep(0.2)

    return False

# ───────────────────────────── SCAN_ONLY MODE ───────────────────────────────
def scan_accounts(timeout=30):
    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    _use_headless = os.getenv("HEADLESS", "0").lower() not in ("0", "false", "no")
    if _use_headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # Fix ChromeDriver timeout issues by using a stable version
    drv = webdriver.Chrome(executable_path=ChromeDriverManager().install(), options=opts)
    drv.set_page_load_timeout(60)
    drv.implicitly_wait(10)
    try:
        wait = WebDriverWait(drv, 30)
        drv.get(URL_B)
        # login rápido si aparece
        try:
            wait.until(EC.presence_of_element_located((By.ID, FIELD_LOGIN_ID))).send_keys(USER_B)
            wait.until(EC.presence_of_element_located((By.ID, FIELD_PASS_ID))).send_keys(PASS_B)
            time.sleep(2)  # Esperar 2 segundos después de pegar user y pass
            try: drv.find_element(By.CSS_SELECTOR, LOGIN_BTN_CSS).click()
            except: pass
            time.sleep(6)  # Esperar 6 segundos después de presionar botón
            time.sleep(3)
        except Exception:
            pass  # posiblemente ya logueado

        # COMENTADO TEMPORALMENTE - navegar a la grilla
        # try: drv.get(TRANSFER_URL)
        # except: pass
        # time.sleep(5)

        sel, selectors = None, [s.strip() for s in ACCOUNTS_SELECTOR.split(",") if s.strip()]
        deadline = time.time() + timeout
        while time.time() < deadline and not sel:
            for s in selectors:
                try:
                    el = drv.find_element(By.CSS_SELECTOR, s)
                    if el: sel = el; break
                except: continue
            if not sel: time.sleep(0.5)

        accounts = []
        if sel:
            try:
                js = """
                  const sel = arguments[0];
                  return Array.from(sel.options).map(o=>({value:o.value, text:o.text}));
                """
                accounts = drv.execute_script(js, sel) or []
            except Exception:
                try:
                    for o in sel.find_elements(By.TAG_NAME, "option"):
                        accounts.append({"value": o.get_attribute("value") or o.text,
                                         "text":  o.text})
                except: pass

        print(json.dumps({"accounts": accounts}, ensure_ascii=False))
        return 0
    finally:
        try: drv.quit()
        except: pass

# ───────────────────────────── FLUJO PRINCIPAL ──────────────────────────────
def login_otp() -> bool:
    # Las fechas son opcionales para el proceso de OTP
    # Se usarán después para filtrar la grilla de movimientos
    date_from = os.getenv("DATE_FROM")      # YYYY-MM-DD (opcional)
    date_to   = os.getenv("DATE_TO")        # YYYY-MM-DD (opcional)
    
    # Solo procesar fechas si están disponibles
    if date_from and date_to:
        df_y, df_m, df_d = date_from.split("-")
        dt_y, dt_m, dt_d = date_to.split("-")
        print(f"DEBUG: Fechas configuradas: {date_from} a {date_to}")
    else:
        print("DEBUG: No se configuraron fechas - solo proceso OTP")

    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    if HEADLESS:
        opts.add_argument("--headless=new")
    # Fix ChromeDriver timeout issues by using a stable version
    drv = webdriver.Chrome(executable_path=ChromeDriverManager().install(), options=opts)
    drv.set_page_load_timeout(60)
    drv.implicitly_wait(10)
    try:
        wait = WebDriverWait(drv, 30)

        # 1) Login
        print("DEBUG: Iniciando proceso de login...")
        print(f"DEBUG: Navegando a URL: {URL_B}")
        drv.get(URL_B)
        print(f"DEBUG: URL actual después de navegar: {drv.current_url}")
        
        print(f"DEBUG: Buscando campo de usuario: {FIELD_LOGIN_ID}")
        user_field = wait.until(EC.presence_of_element_located((By.ID, FIELD_LOGIN_ID)))
        print(f"DEBUG: Campo de usuario encontrado: {user_field}")
        user_field.send_keys(USER_B)
        print(f"DEBUG: Usuario ingresado: {USER_B}")
        
        print(f"DEBUG: Buscando campo de contraseña: {FIELD_PASS_ID}")
        pass_field = wait.until(EC.presence_of_element_located((By.ID, FIELD_PASS_ID)))
        print(f"DEBUG: Campo de contraseña encontrado: {pass_field}")
        pass_field.send_keys(PASS_B)
        print("DEBUG: Contraseña ingresada")
        
        time.sleep(2)  # Esperar 2 segundos después de pegar user y pass
        print("DEBUG: Buscando botón de login...")
        login_btn = drv.find_element(By.CSS_SELECTOR, LOGIN_BTN_CSS)
        print(f"DEBUG: Botón de login encontrado: {login_btn}")
        login_btn.click()
        print("DEBUG: Click en botón de login realizado")
        time.sleep(6)  # Esperar 6 segundos después de presionar botón
        print(f"DEBUG: URL actual después del login: {drv.current_url}")

        # 2) Esperar posible redirección al 2FA
        print("DEBUG: Esperando redirección al 2FA...")
        print(f"DEBUG: URL actual antes de esperar 2FA: {drv.current_url}")
        try:
            wait.until(EC.url_contains("app_control_2fa"))
            print("DEBUG: ✅ Redirección a 2FA confirmada")
        except Exception as e:
            print(f"DEBUG: ❌ No se detectó redirección a 2FA: {e}")
            # no necesariamente fatal, seguir intentando encontrar OTP
            pass
        
        print(f"DEBUG: URL actual después de esperar 2FA: {drv.current_url}")

        # 3) Buscar campo OTP (si no hay -> fallo)
        print("DEBUG: Iniciando búsqueda de campo OTP...")
        try:
            otp_input = find_otp_input_and_debug(drv, wait, timeout=10)
            print("DEBUG: ✅ Campo OTP encontrado exitosamente")
        except Exception as e:
            print(f"DEBUG: ❌ Error buscando campo OTP: {e}")
            # no se encontró campo OTP -> considerar transferencia fallida
            return False

        # 4) Buscar todos los emails de lohas en la última hora
        print("DEBUG: Buscando todos los emails de lohas en la última hora...")
        if GMAIL_USER and GMAIL_PASS:
            print(f"DEBUG: Credenciales Gmail disponibles: {GMAIL_USER}")
            try:
                m = imap_connect()
                
                # Buscar emails de lohas en la última hora
                import datetime
                now = datetime.datetime.now()
                one_hour_ago = now - datetime.timedelta(hours=1)
                date_str = one_hour_ago.strftime("%d-%b-%Y")
                
                print(f"DEBUG: Buscando emails desde: {date_str}")
                
                # Buscar emails de lohas desde hace 1 hora
                typ, data = m.uid("SEARCH", None, 'SINCE', date_str, 'FROM', f'"{KNOWN_SENDER}"')
                if typ == 'OK' and data and data[0]:
                    uids = [int(x) for x in data[0].split()]
                    print(f"DEBUG: Encontrados {len(uids)} emails de {KNOWN_SENDER} en la última hora")
                    
                    # Procesar cada email encontrado
                    for i, uid in enumerate(uids[-5:]):  # Solo los últimos 5
                        try:
                            subj, body = uid_fetch_text(m, uid)
                            print(f"DEBUG: Email {i+1} (UID {uid}):")
                            print(f"DEBUG:   Asunto: {subj}")
                            print(f"DEBUG:   Cuerpo (primeros 200 chars): {body[:200]}...")
                            
                            # Intentar extraer OTP
                            otp = extract_otp(subj, body)
                            if otp:
                                print(f"DEBUG:   ✅ OTP encontrado: {otp}")
                            else:
                                print(f"DEBUG:   ❌ No se encontró OTP en este email")
                        except Exception as e:
                            print(f"DEBUG:   ❌ Error procesando email {uid}: {e}")
                else:
                    print(f"DEBUG: ❌ No se encontraron emails de {KNOWN_SENDER} en la última hora")
                
                # También buscar emails recientes sin filtro de fecha
                print("DEBUG: Buscando emails recientes de lohas (sin filtro de fecha)...")
                typ, data = m.uid("SEARCH", None, 'FROM', f'"{KNOWN_SENDER}"')
                if typ == 'OK' and data and data[0]:
                    all_uids = [int(x) for x in data[0].split()]
                    print(f"DEBUG: Total de emails de {KNOWN_SENDER} encontrados: {len(all_uids)}")
                    
                    # Mostrar los últimos 3 emails
                    for i, uid in enumerate(all_uids[-3:]):
                        try:
                            subj, body = uid_fetch_text(m, uid)
                            print(f"DEBUG: Email reciente {i+1} (UID {uid}):")
                            print(f"DEBUG:   Asunto: {subj}")
                            print(f"DEBUG:   Cuerpo (primeros 200 chars): {body[:200]}...")
                            
                            # Intentar extraer OTP
                            otp = extract_otp(subj, body)
                            if otp:
                                print(f"DEBUG:   ✅ OTP encontrado: {otp}")
                            else:
                                print(f"DEBUG:   ❌ No se encontró OTP en este email")
                        except Exception as e:
                            print(f"DEBUG:   ❌ Error procesando email {uid}: {e}")
                else:
                    print(f"DEBUG: ❌ No se encontraron emails de {KNOWN_SENDER}")
                
                m.logout()
                
            except Exception as e:
                print(f"DEBUG: ❌ Error buscando emails de lohas: {e}")
        else:
            print("DEBUG: ❌ No hay credenciales Gmail disponibles")
        
        # 5) Preparar búsqueda de OTP con baseline UID del último email
        print("DEBUG: Preparando búsqueda de OTP con baseline UID...")
        since_uid = None
        if GMAIL_USER and GMAIL_PASS:
            try:
                m = imap_connect()
                # Obtener el UID más alto como baseline
                typ, data = m.uid("SEARCH", None, "ALL")
                if typ == 'OK' and data and data[0]:
                    all_uids = [int(x) for x in data[0].split()]
                    since_uid = max(all_uids) if all_uids else 0
                    print(f"DEBUG: Baseline UID establecido: {since_uid}")
                else:
                    since_uid = 0
                    print("DEBUG: No se encontraron emails, baseline UID = 0")
                m.logout()
            except Exception as e:
                print(f"DEBUG: Error estableciendo baseline UID: {e}")
                since_uid = None

        # 5) Usar el último OTP encontrado directamente
        print("DEBUG: Usando el último OTP encontrado...")
        otp_code = ""
        try:
            if GMAIL_USER and GMAIL_PASS:
                # Buscar el último OTP de lohas
                m = imap_connect()
                typ, data = m.uid("SEARCH", None, 'FROM', f'"{KNOWN_SENDER}"')
                if typ == 'OK' and data and data[0]:
                    all_uids = [int(x) for x in data[0].split()]
                    if all_uids:
                        # Tomar el UID más alto (más reciente)
                        latest_uid = max(all_uids)
                        print(f"DEBUG: Último UID encontrado: {latest_uid}")
                        
                        # Obtener el contenido del último email
                        subj, body = uid_fetch_text(m, latest_uid)
                        print(f"DEBUG: Último email (UID {latest_uid}):")
                        print(f"DEBUG:   Asunto: {subj}")
                        print(f"DEBUG:   Cuerpo (primeros 200 chars): {body[:200]}...")
                        
                        # Extraer OTP
                        otp_code = extract_otp(subj, body)
                        if otp_code:
                            print(f"DEBUG: ✅ Código OTP obtenido del último email: {otp_code}")
                        else:
                            print("DEBUG: ❌ No se pudo extraer OTP del último email")
                    else:
                        print("DEBUG: ❌ No se encontraron emails de lohas")
                else:
                    print("DEBUG: ❌ No se encontraron emails de lohas")
                
            if GMAIL_USER and GMAIL_PASS:
                m.logout()
                if not otp_code:
                    print("DEBUG: ❌ No se obtuvo código OTP")
                    return False
            else:
                print("DEBUG: ❌ Sin credenciales gmail -> no puede operar")
                return False
                return False
        except Exception as e:
            print(f"DEBUG: ❌ Error obteniendo OTP: {e}")
            return False

        # 6) Pegar OTP
        print("DEBUG: Iniciando proceso de pegar OTP...")
        print("DEBUG: Limpiando campo OTP...")
        try:
            otp_input.clear()
            print("DEBUG: ✅ Campo OTP limpiado")
        except Exception as e:
            print(f"DEBUG: ❌ Error limpiando campo OTP: {e}")
            pass

        print(f"DEBUG: Pegando código OTP: {otp_code}")
        # Intentar diferentes métodos de pegar OTP
        try:
            # Método 1: JavaScript directo (evitar formato automático)
            drv.execute_script("""
                var el = arguments[0];
                var value = arguments[1];
                el.value = value;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            """, otp_input, otp_code)
            print("DEBUG: ✅ Código OTP pegado con JavaScript (sin formato)")
        except Exception as e:
            print(f"DEBUG: ❌ Error con JavaScript: {e}")
            try:
                # Método 2: send_keys normal
                otp_input.send_keys(otp_code)
                print("DEBUG: ✅ Código OTP pegado con send_keys")
            except Exception as e2:
                print(f"DEBUG: ❌ Error con send_keys: {e2}")
                try:
                    # Método 3: Clear y send_keys
                    otp_input.clear()
                    otp_input.send_keys(otp_code)
                    print("DEBUG: ✅ Código OTP pegado con clear + send_keys")
                except Exception as e3:
                    print(f"DEBUG: ❌ Error con clear + send_keys: {e3}")
                    return False
        
        # Verificar que se pegó correctamente
        try:
            field_value = otp_input.get_attribute("value")
            print(f"DEBUG: Valor actual del campo: '{field_value}'")
            
            # Verificar si el código se pegó correctamente (con o sin hyphens)
            field_digits = field_value.replace("-", "").replace(" ", "")
            otp_digits = otp_code.replace("-", "").replace(" ", "")
            
            if field_digits == otp_digits:
                print("DEBUG: ✅ Verificación: código pegado correctamente (con formato automático)")
            elif field_value == otp_code:
                print("DEBUG: ✅ Verificación: código pegado correctamente (sin formato)")
            else:
                print(f"DEBUG: ❌ Verificación: código no se pegó correctamente")
                print(f"DEBUG:   Esperado: '{otp_code}'")
                print(f"DEBUG:   Obtenido: '{field_value}'")
                print(f"DEBUG:   Dígitos esperados: '{otp_digits}'")
                print(f"DEBUG:   Dígitos obtenidos: '{field_digits}'")
        except Exception as e:
            print(f"DEBUG: ❌ Error verificando valor del campo: {e}")
                
        except Exception as e:
            print(f"DEBUG: ❌ Error pegando OTP: {e}")
            # no se pudo pegar OTP -> fallo
            return False

        # 6.1) Pausa breve antes de confirmar (igual que bot.py)
        try:
            print("DEBUG: Esperando 1s antes de confirmar/aceptar...")
            time.sleep(1.0)
        except Exception:
            pass

        # 7) Aceptar dos veces (con 1s entre clicks), luego esperar y navegar
        print("DEBUG: Buscando y clickeando botón Aceptar (1/2)...")
        try:
            result1 = click_accept_button(drv, wait, timeout=20)
            if result1:
                print("DEBUG: ✅ Click en botón Aceptar 1/2 exitoso")
            else:
                print("DEBUG: ❌ No se pudo hacer click en botón Aceptar 1/2")
                return False
        except Exception as e:
            print(f"DEBUG: ❌ Error en botón Aceptar 1/2: {e}")
            return False

        try:
            time.sleep(1.0)
        except Exception:
            pass

        print("DEBUG: Buscando y clickeando botón Aceptar (2/2, id=sub_form_b)...")
        try:
            ok_confirm = click_confirm_button(drv, wait, timeout=20)
            if ok_confirm:
                print("DEBUG: ✅ Click en botón Aceptar 2/2 (sub_form_b) exitoso")
            else:
                print("DEBUG: ❌ No se pudo hacer click en botón Aceptar 2/2 (sub_form_b)")
                return False
        except Exception as e:
            print(f"DEBUG: ❌ Error en botón Aceptar 2/2 (sub_form_b): {e}")
            return False

        # Intentar confirmar que salimos de 2FA (no bloqueante)
        try:
            print("DEBUG: Verificando salida de 2FA...")
            WebDriverWait(drv, 10).until(lambda d: "app_control_2fa" not in d.current_url)
            print(f"DEBUG: URL tras aceptar: {drv.current_url}")
        except Exception as e:
            print(f"DEBUG: Aviso: no se pudo confirmar salida de 2FA: {e}")

        # Esperar 4s y navegar a la grilla
        try:
            print("DEBUG: Esperando 4s antes de ir a la grilla...")
            time.sleep(4)
        except Exception:
            pass
        try:
            print(f"DEBUG: Navegando a grilla: {TRANSFER_URL}")
            drv.get(TRANSFER_URL)
            print("DEBUG: Esperando 3s para que cargue la grilla...")
            time.sleep(3)
            
            # Leer cuentas del dropdown
            print("DEBUG: Buscando dropdown de cuentas...")
            try:
                # Intentar abrir el dropdown haciendo click
                dropdown = drv.find_element(By.CSS_SELECTOR, "span.select2-selection.select2-selection--single")
                print(f"DEBUG: Dropdown encontrado: {dropdown}")
                dropdown.click()
                time.sleep(1)
                
                # Leer todas las opciones disponibles
                options = drv.find_elements(By.CSS_SELECTOR, "li.select2-results__option")
                accounts = []
                print(f"DEBUG: Encontradas {len(options)} opciones en el dropdown")
                
                for i, option in enumerate(options):
                    try:
                        text = option.text
                        value = option.get_attribute("data-select2-id") or text
                        if text and text.strip():
                            accounts.append({"value": value, "text": text.strip()})
                            print(f"DEBUG: Cuenta {i+1}: {text.strip()}")
                    except Exception as e:
                        print(f"DEBUG: Error leyendo opción {i+1}: {e}")
                        continue
                
                print(f"DEBUG: Total de cuentas leídas: {len(accounts)}")
                
                # Guardar las cuentas para retornarlas
                if accounts:
                    print("DEBUG: ✅ Cuentas leídas exitosamente")
                    # Emite una línea marcadora fácil de parsear por Flask
                    try:
                        payload = json.dumps({"accounts": accounts}, ensure_ascii=True)
                        _orig_print("ACCOUNTS_JSON:" + payload)
                    except Exception as _e:
                        # Fallback: imprime JSON simple (por compatibilidad)
                        _orig_print(json.dumps({"accounts": accounts}, ensure_ascii=True))
                else:
                    print("DEBUG: ❌ No se encontraron cuentas en el dropdown")
                    
            except Exception as e:
                print(f"DEBUG: ❌ Error leyendo dropdown de cuentas: {e}")
                
        except Exception as e:
            print(f"DEBUG: ❌ Error navegando a grilla: {e}")

        print("DEBUG: Retornando True - flujo post-OTP completado")
        return True
        
        # COMENTADO TEMPORALMENTE - Todo el proceso posterior al OTP
        # time.sleep(55)

        # COMENTADO TEMPORALMENTE - Todo el proceso posterior al OTP
        # # 9) Rellenar fechas
        # time.sleep(3)
        # for _id, _val in [
        #     (DIA_DESDE, df_d), (MES_DESDE, df_m), (ANO_DESDE, df_y),
        #     (DIA_HASTA, dt_d), (MES_HASTA, dt_m), (ANO_HASTA, dt_y)
        # ]:
        #     el = locate(drv, By.ID, _id, 8)
        #     if el:
        #         try: el.clear()
        #         except: pass
        #         el.send_keys(_val)
        # 
        # # seleccionar cuenta elegida (opcional)
        # account_sel = os.getenv("ACCOUNT_SEL")
        # if account_sel:
        #     try:
        #         js = """
        #           const v = arguments[0], sels = arguments[1];
        #           for(const q of sels){
        #             const sel=document.querySelector(q); if(!sel) continue;
        #             for(const o of sel.options){
        #               if(o.value==v || o.text.trim()==v){
        #                 sel.value=o.value; sel.dispatchEvent(new Event('change'));
        #                 return true;
        #               }
        #             }
        #           } return false;
        #         """
        #         drv.execute_script(js, account_sel, [s.strip() for s in ACCOUNTS_SELECTOR.split(",") if s.strip()])
        #     except: pass
        # 
        # time.sleep(5)
        
        # Solo retornar True después del OTP exitoso
        print("DEBUG: Retornando True - proceso OTP completado")
        return True

    except Exception as e:
        print(f"Error en login_otp: {e}")
        return False

    finally:
        try: drv.quit()
        except: pass

# ───────────────────────────── CLI ENTRYPOINT ───────────────────────────────
def main():
    print("DEBUG: ===== INICIANDO FUNCIÓN main =====")
    print("DEBUG: SCAN_ONLY =", os.getenv("SCAN_ONLY"))
    print("DEBUG: DATE_FROM =", os.getenv("DATE_FROM"))
    print("DEBUG: DATE_TO =", os.getenv("DATE_TO"))
    print("DEBUG: HEADLESS =", os.getenv("HEADLESS"))
    print("DEBUG: ACCOUNT_SEL =", os.getenv("ACCOUNT_SEL"))
    print("DEBUG: PYTHONUNBUFFERED =", os.getenv("PYTHONUNBUFFERED"))
    
    if os.getenv("SCAN_ONLY") == "1":      # sólo listar cuentas
        print("DEBUG: Modo SCAN_ONLY activado")
        try: sys.exit(scan_accounts())
        except Exception as e:
            print(json.dumps({"error": str(e)})); sys.exit(1)

    # modo normal
    print("DEBUG: Modo normal - iniciando transferencia")
    print("TRANSFE_START:1")
    try:
        print("DEBUG: Llamando a login_otp()...")
        print("DEBUG: ===== INICIANDO PROCESO DE LOGIN OTP =====")
        ok = login_otp()
        print(f"DEBUG: login_otp() retornó: {ok}")
        print("TRANSFE_DONE:1" if ok else "TRANSFE_FAILED:1")
    except Exception as e:
        print(f"DEBUG: ❌ Error en main: {e}")
        print("TRANSFE_FAILED:1"); _orig_print("Error:", e); sys.exit(1)

if __name__ == "__main__":
    main()
