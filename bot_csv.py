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
from webdriver_manager.chrome import ChromeDriverManager

# ───────────────────────── PRINT MÍNIMO ──────────────────────────────────────
_orig_print = builtins.print
def _minimal_print(*a, **kw):
    if a and str(a[0]).startswith(("TRANSFE_START:", "TRANSFE_DONE:", "TRANSFE_FAILED:")):
        _orig_print(*a, **kw)
builtins.print = _minimal_print

# ───────────────────────── CONFIG & CONSTANTES WEB ───────────────────────────
URL_B            = "https://app.lohas.eco/app_Login"
USER_B           = "brianswitach@gmail.com"
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
HEADLESS = os.getenv("HEADLESS", "1").lower() not in ("0", "false", "no")

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

def click_accept_button(drv: Chrome, timeout=15.0):
    el = locate(drv, By.ID, ACCEPT_BTN_ID, timeout) \
         or locate(drv, By.CSS_SELECTOR, f"#{ACCEPT_BTN_ID}", 6) \
         or locate(drv, By.XPATH, "//a[contains(.,'Aceptar')]", 6)
    return safe_click(drv, el) if el else False

# ───────────────────────────── SCAN_ONLY MODE ───────────────────────────────
def scan_accounts(timeout=30):
    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    _use_headless = os.getenv("HEADLESS", "1").lower() not in ("0", "false", "no")
    if _use_headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    drv = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
    try:
        wait = WebDriverWait(drv, 30)
        drv.get(URL_B)
        # login rápido si aparece
        try:
            wait.until(EC.presence_of_element_located((By.ID, FIELD_LOGIN_ID))).send_keys(USER_B)
            wait.until(EC.presence_of_element_located((By.ID, FIELD_PASS_ID))).send_keys(PASS_B)
            try: drv.find_element(By.CSS_SELECTOR, LOGIN_BTN_CSS).click()
            except: pass
            time.sleep(3)
        except Exception:
            pass  # posiblemente ya logueado

        # navegar a la grilla
        try: drv.get(TRANSFER_URL)
        except: pass
        time.sleep(5)

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
    date_from = os.getenv("DATE_FROM")      # YYYY-MM-DD
    date_to   = os.getenv("DATE_TO")        # YYYY-MM-DD
    if not (date_from and date_to):
        raise RuntimeError("Se requieren DATE_FROM y DATE_TO en el entorno")
    df_y, df_m, df_d = date_from.split("-")
    dt_y, dt_m, dt_d = date_to.split("-")

    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    if HEADLESS:
        opts.add_argument("--headless=new")
    drv = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
    try:
        wait = WebDriverWait(drv, 30)

        # 1) Login
        drv.get(URL_B)
        wait.until(EC.presence_of_element_located((By.ID, FIELD_LOGIN_ID))).send_keys(USER_B)
        wait.until(EC.presence_of_element_located((By.ID, FIELD_PASS_ID))).send_keys(PASS_B)
        drv.find_element(By.CSS_SELECTOR, LOGIN_BTN_CSS).click()

        # 2) Esperar pantalla 2-FA
        wait.until(lambda d: "app_control_2fa" in d.current_url or d.find_elements(By.ID, OTP_FIELD_ID))

        # 3) Input OTP
        otp_input = locate(drv, By.ID, OTP_FIELD_ID, 10) or locate(drv, By.NAME, OTP_FIELD_NAME, 5)
        if not otp_input:
            raise TimeoutError("No se encontró input OTP automáticamente")

        # 4) UID base
        base_uid = 0
        try:
            m = imap_connect()
            _, data = m.uid("SEARCH", None, "ALL")
            base_uid = max([int(x) for x in (data[0] or b"").split()] or [0])
            m.logout()
        except: pass

        # 5) Esperar OTP
        otp_code = wait_for_otp(base_uid)
        otp_input.clear()
        otp_input.send_keys(otp_code)
        time.sleep(3)

        # 6-7) Aceptar (dos clics)
        if not click_accept_button(drv, 20): raise TimeoutError("Botón Aceptar (1)")
        time.sleep(3)
        if not click_accept_button(drv, 12): raise TimeoutError("Botón Aceptar (2)")
        time.sleep(3)

        # 8) Navegar grilla
        drv.get(TRANSFER_URL)
        time.sleep(55)

        # 9) Rellenar fechas
        time.sleep(3)
        for _id, _val in [
            (DIA_DESDE, df_d), (MES_DESDE, df_m), (ANO_DESDE, df_y),
            (DIA_HASTA, dt_d), (MES_HASTA, dt_m), (ANO_HASTA, dt_y)
        ]:
            el = locate(drv, By.ID, _id, 8)
            if el:
                try: el.clear()
                except: pass
                el.send_keys(_val)

        # seleccionar cuenta elegida (opcional)
        account_sel = os.getenv("ACCOUNT_SEL")
        if account_sel:
            try:
                js = """
                  const v = arguments[0], sels = arguments[1];
                  for(const q of sels){
                    const sel=document.querySelector(q); if(!sel) continue;
                    for(const o of sel.options){
                      if(o.value==v || o.text.trim()==v){
                        sel.value=o.value; sel.dispatchEvent(new Event('change'));
                        return true;
                      }
                    }
                  } return false;
                """
                drv.execute_script(js, account_sel, [s.strip() for s in ACCOUNTS_SELECTOR.split(",") if s.strip()])
            except: pass

        time.sleep(5)
        return True

    finally:
        try: drv.quit()
        except: pass

# ───────────────────────────── CLI ENTRYPOINT ───────────────────────────────
def main():
    if os.getenv("SCAN_ONLY") == "1":      # sólo listar cuentas
        try: sys.exit(scan_accounts())
        except Exception as e:
            print(json.dumps({"error": str(e)})); sys.exit(1)

    # modo normal
    print("TRANSFE_START:1")
    try:
        ok = login_otp()
        print("TRANSFE_DONE:1" if ok else "TRANSFE_FAILED:1")
    except Exception as e:
        print("TRANSFE_FAILED:1"); _orig_print("Error:", e); sys.exit(1)

if __name__ == "__main__":
    main()
