#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot.py - Automación login + 2FA OTP (IMAP Gmail) con Selenium.
Versión modificada: cada transferencia en ventana/navegador independiente,
no pide inputs manuales: si OTP o código de transferencia no llegan -> marcar
esa transferencia como FALLIDA y seguir. Al final reintenta las fallidas hasta
que se completen (reintentos indefinidos por pasadas). Se asegura de cerrar ventanas y
esperar 3 segundos entre reintentos. Salida de logs mínima (solo ARRANCA /
COMPLETADA / FALLIDA por intento) + resumen al final de cada pasada.
"""
from __future__ import annotations
import builtins
import csv
import os
import re
import sys
import time
import imaplib
import email
import email.header
from email.utils import parsedate_to_datetime
from typing import List, Optional, Tuple, Callable, Dict, Any
from datetime import datetime
import json
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()



# Guardar print original
_orig_print = builtins.print

# Reemplazar print para SILENCIAR TODO salvo los mensajes especiales solicitados.
def _minimal_print(*args, sep=' ', end='\n', file=None, flush=False):
    """
    Solo permite imprimir mensajes especiales:
      - "TRANSFE_START:{n}"   -> "Arranca tranfe {n}"
      - "TRANSFE_DONE:{n}"    -> "Completada tranfe {n}"
      - "TRANSFE_FAILED:{n}"  -> "Fallida tranfe {n}"
      - "RESEND_PRESSED"      -> "Se apreta a reenviar código" (no usado ahora)
      - "RESEND_FAILED:{motivo}" -> "Reenvío falló en: {motivo}" (no usado ahora)
      - "PASADA_FINALIZADA:..." -> "Pasada finalizada — {payload}"
    Cualquier otro print queda silenciado.
    """
    if not args:
        return
    msg = sep.join(str(a) for a in args)
    if msg.startswith("TRANSFE_START:"):
        try:
            n = msg.split(":", 1)[1]
            _orig_print(f"Arranca la Transferencia #{n}", end=end, file=file, flush=flush)
        except Exception:
            pass
    elif msg.startswith("TRANSFE_DONE:"):
        try:
            n = msg.split(":", 1)[1]
            _orig_print(f"Completada la Transferencia #{n}", end=end, file=file, flush=flush)
        except Exception:
            pass
    elif msg.startswith("TRANSFE_FAILED:"):
        try:
            n = msg.split(":", 1)[1]
            _orig_print(f"Fallida la Transferencia #{n}", end=end, file=file, flush=flush)
        except Exception:
            pass
    elif msg.startswith("ERROR_DEBUG:"):
        try:
            debug_msg = msg.split(":", 1)[1]
            _orig_print(f"DEBUG: {debug_msg}", end=end, file=file, flush=flush)
        except Exception:
            pass
    elif msg == "RESEND_PRESSED":
        _orig_print("Se apreta a reenviar código", end=end, file=file, flush=flush)
    elif msg.startswith("RESEND_FAILED:"):
        try:
            reason = msg.split(":", 1)[1]
            _orig_print(f"Reenvío falló en: {reason}", end=end, file=file, flush=flush)
        except Exception:
            _orig_print("Reenvío falló en: motivo desconocido", end=end, file=file, flush=flush)
    elif msg.startswith("PASADA_FINALIZADA:"):
        try:
            payload = msg.split(":", 1)[1]
            _orig_print(f"Pasada finalizada — {payload}", end=end, file=file, flush=flush)
        except Exception:
            pass
    else:
        # silenciado: nada más se imprime
        return

builtins.print = _minimal_print

# Selenium + webdriver-manager
from selenium import webdriver
from selenium.webdriver.common.by import By
# from selenium.webdriver.chrome.service import Service as ChromeService  # Not available in Selenium 3.x
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver import ActionChains
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------
# CONFIG
# ---------------------------
URL_B = "https://app.lohas.eco/app_Login"

# Credenciales Lohas (desde .env - requeridas)
USER_B = os.getenv("USER_LOHAS", "")
PASS_B = os.getenv("PASS_LOHAS", "")

FIELD_LOGIN_ID = "id_sc_field_login"
FIELD_PASS_ID = "id_sc_field_pswd"
LOGIN_BTN_CSS = 'input.button[onclick*="nm_atualiza"]'

# OTP field en la página
OTP_FIELD_ID = "id_sc_field_code"
OTP_FIELD_NAME = "code"

# Botón Aceptar y Confirm
ACCEPT_BTN_ID = "sc_submit_ajax_bot"
CONFIRM_BTN_ID = "sub_form_b"

# Botón Reenviar código (ya no se usa)
RESEND_BTN_ID = "sc_resend_bot"

# URL destino final (reemplazo de clicks en "Transferencias")
TRANSFER_URL = "https://app.lohas.eco/form_transferencias/"

# Campo y botón dentro de la página de transferencias
CUENTA_FIELD_ID = "id_sc_field_cuenta"
CUENTA_TO_PASTE = "0000155300000000001362"
PRIMERO_BTN_ID = "sc_b_stepavc_b"  # "Próximo"

# Select2 combobox CSS (el span que abrimos)
SELECT2_COMBO_CSS = "span.select2-selection.select2-selection--single.css_idconcepto_bcra_obj"

# Token field & Confirm button after transfer confirmation-mail
TOKEN_FIELD_ID = "id_sc_field_token_cliente"
TOKEN_CONFIRM_BTN_ID = "sc_confirmar_bot"

# Gmail IMAP (desde .env - requeridas)
GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")

# Modo visible (sin headless)
HEADLESS = False

# regex para extraer OTP (frase exacta y fallback dígitos)
OTP_PHRASE_RE = re.compile(r"su\s+c[oó]digo\s+de\s+inicio\s+de\s+sesi[oó]n\s+es\s*[:\s,-]*?(\d{4,8})", re.I)
OTP_DIGITS_RE = re.compile(r"\b(\d{4,8})\b")

# regex para extraer código de confirmación de transferencia en el cuerpo
TRANSFER_CODE_RE = re.compile(r"Se\s+env[ií]a\s+el\s+c[oó]digo\s+para\s+confirmar\s+la\s+transferencia\s*[:\s-]*?(\d{4,8})", re.I)
TRANSFER_DIGITS_RE = re.compile(r"\b(\d{4,8})\b")

KNOWN_SENDER = "sistema@lohas.eco"

# ---------------------------
# UTIL
# ---------------------------
def now_ms() -> str:
    return str(int(time.time() * 1000))


def strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_email_date(date_header: Optional[str]) -> Optional[datetime]:
    if not date_header:
        return None
    try:
        dt = parsedate_to_datetime(date_header)
        return dt
    except Exception:
        return None


def message_time_matches_now(msg_date_dt: Optional[datetime]) -> bool:
    if not msg_date_dt:
        return False
    try:
        if msg_date_dt.tzinfo:
            now_local = datetime.now(msg_date_dt.tzinfo)
        else:
            now_local = datetime.now()
        m_hour = msg_date_dt.hour
        m_min = msg_date_dt.minute
        n_hour = now_local.hour
        n_min = now_local.minute
        if m_hour != n_hour:
            return False
        if m_min == n_min or m_min == ((n_min + 1) % 60):
            return True
        return False
    except Exception:
        return False


# ---------------------------
# IMAP helpers
# ---------------------------
def imap_connect(host: str, user: str, pwd: str) -> imaplib.IMAP4_SSL:
    M = imaplib.IMAP4_SSL(host)
    M.login(user, pwd)
    M.select("INBOX")
    return M


def uid_search_all(M: imaplib.IMAP4_SSL, criteria: str) -> List[int]:
    typ, data = M.uid("SEARCH", None, criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    return [int(x) for x in data[0].split()]


def uid_fetch_text(M: imaplib.IMAP4_SSL, uid: int) -> Tuple[str, str, Optional[str]]:
    typ, data = M.uid("FETCH", str(uid), "(RFC822)")
    if typ != "OK" or not data or not data[0]:
        return "", "", None
    raw = data[0][1]
    msg = email.message_from_bytes(raw)
    subj = email.header.make_header(email.header.decode_header(msg.get("Subject", "")))
    subject = str(subj)
    date_header = msg.get("Date", None)
    body_text = ""
    if msg.is_multipart():
        plaintexts = []
        htmltexts = []
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    plaintexts.append(payload.decode(charset, errors="ignore"))
                except Exception:
                    try:
                        plaintexts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
                    except Exception:
                        pass
            elif ctype == "text/html" and "attachment" not in disp:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    htmltexts.append(payload.decode(charset, errors="ignore"))
                except Exception:
                    try:
                        htmltexts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
                    except Exception:
                        pass
        if plaintexts:
            body_text = "\n\n".join(plaintexts)
        elif htmltexts:
            body_text = "\n\n".join(strip_tags(h) for h in htmltexts)
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload is None:
                body_text = ""
            else:
                charset = msg.get_content_charset() or "utf-8"
                body_text = payload.decode(charset, errors="ignore")
                if "<html" in body_text.lower():
                    body_text = strip_tags(body_text)
        except Exception:
            try:
                body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            except Exception:
                body_text = ""
    return subject, body_text, date_header


def imap_search_utf8(M: imaplib.IMAP4_SSL, *parts: str):
    try:
        need_utf8 = any(any(ord(c) > 127 for c in p) for p in parts if isinstance(p, str))
        if need_utf8:
            return M.uid('SEARCH', 'CHARSET', 'UTF-8', *parts)
        else:
            return M.uid('SEARCH', None, *parts)
    except Exception:
        ascii_parts = []
        for p in parts:
            if isinstance(p, str):
                try:
                    p_ascii = p.encode('ascii', 'ignore').decode('ascii')
                except Exception:
                    p_ascii = p
                ascii_parts.append(p_ascii)
            else:
                ascii_parts.append(p)
        try:
            return M.uid('SEARCH', None, *ascii_parts)
        except Exception:
            return "NO", []


# ---------------------------
# EXTRACCION OTP y CÓDIGO TRANSFERENCIA
# ---------------------------
def extract_otp_from_text(subject: str, body: str) -> Optional[str]:
    if not body and not subject:
        return None
    m = OTP_PHRASE_RE.search(body or "") or OTP_PHRASE_RE.search(subject or "")
    if m:
        return m.group(1)
    m2 = OTP_DIGITS_RE.search(body or "") or OTP_DIGITS_RE.search(subject or "")
    if m2:
        return m2.group(1)
    return None


def extract_transfer_code_from_text(subject: str, body: str) -> Optional[str]:
    if not body and not subject:
        return None
    m = TRANSFER_CODE_RE.search(body or "") or TRANSFER_CODE_RE.search(subject or "")
    if m:
        return m.group(1)
    m2 = TRANSFER_DIGITS_RE.search(body or "") or TRANSFER_DIGITS_RE.search(subject or "")
    if m2:
        return m2.group(1)
    return None


def get_latest_otp_gmail(user: str, pwd: str, timeout_sec: int = 120, poll_every: float = 2.0, since_uid: Optional[int] = None) -> Tuple[str, int]:
    start = time.time()
    M = None
    try:
        M = imap_connect(GMAIL_IMAP_HOST, user, pwd)
        if since_uid is None:
            all_uids = uid_search_all(M, "ALL")
            since_uid = max(all_uids) if all_uids else 0
        attempt = 0
        while time.time() - start < timeout_sec:
            attempt += 1
            # Buscar mensajes del remitente
            try:
                typ, data = imap_search_utf8(M, 'ALL', 'FROM', f'"{KNOWN_SENDER}"')
                if typ == 'OK' and data and data[0]:
                    uids = [int(x) for x in data[0].split()]
                    uids = sorted(uids, reverse=True)
                else:
                    uids = []
            except Exception:
                uids = []

            for uid in uids:
                if since_uid and uid <= since_uid:
                    continue
                try:
                    subject, body, _ = uid_fetch_text(M, uid)
                    otp = extract_otp_from_text(subject, body)
                    if otp:
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return otp, uid
                except Exception:
                    continue

            # UNSEEN FROM
            try:
                typ, data = imap_search_utf8(M, 'UNSEEN', 'FROM', f'"{KNOWN_SENDER}"')
                if typ == 'OK' and data and data[0]:
                    uids_unseen = [int(x) for x in data[0].split()]
                    uids_unseen = sorted(uids_unseen, reverse=True)
                else:
                    uids_unseen = []
            except Exception:
                uids_unseen = []

            for uid in uids_unseen:
                if since_uid and uid <= since_uid:
                    continue
                try:
                    subject, body, _ = uid_fetch_text(M, uid)
                    otp = extract_otp_from_text(subject, body)
                    if otp:
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return otp, uid
                except Exception:
                    continue

            # Fallback UNSEEN generic
            try:
                typ, data = imap_search_utf8(M, 'UNSEEN')
                if typ == 'OK' and data and data[0]:
                    uids_generic = [int(x) for x in data[0].split()]
                    uids_generic = sorted(uids_generic, reverse=True)
                else:
                    uids_generic = []
            except Exception:
                uids_generic = []

            for uid in uids_generic:
                if since_uid and uid <= since_uid:
                    continue
                try:
                    subject, body, _ = uid_fetch_text(M, uid)
                    otp = extract_otp_from_text(subject, body)
                    if otp:
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return otp, uid
                except Exception:
                    continue

            time.sleep(poll_every)
            try:
                M.select("INBOX")
            except Exception:
                pass

        raise TimeoutError("OTP no llegó a tiempo a Gmail (timeout)")
    finally:
        if M:
            try:
                M.logout()
            except Exception:
                pass


def get_latest_transfer_code_gmail(user: str, pwd: str, subject_search: str = "Envío de código", timeout_sec: int = 180, poll_every: float = 3.0) -> Tuple[str, int]:
    """
    Búsqueda optimizada del código de transferencia (igual que antes, pero sin prints).
    """
    start = time.time()
    M = None
    generic_digits_re = re.compile(r"\b(\d{4,8})\b")
    try:
        M = imap_connect(GMAIL_IMAP_HOST, user, pwd)
        attempt = 0
        while time.time() - start < timeout_sec:
            attempt += 1
            time.sleep(0.5)
            # 1) UNSEEN + SUBJECT
            try:
                typ, data = imap_search_utf8(M, 'UNSEEN', 'SUBJECT', f'"{subject_search}"')
                if typ == 'OK' and data and data[0]:
                    uids = [int(x) for x in data[0].split()]
                    uids = sorted(uids, reverse=True)
                else:
                    uids = []
            except Exception:
                uids = []

            if uids:
                for uid in uids:
                    try:
                        subj, body, date_hdr = uid_fetch_text(M, uid)
                        msg_dt = parse_email_date(date_hdr)
                        code = extract_transfer_code_from_text(subj, body)
                        if not code:
                            m2 = generic_digits_re.search(body or "") or generic_digits_re.search(subj or "")
                            if m2:
                                code = m2.group(1)
                        if code and message_time_matches_now(msg_dt):
                            try:
                                M.logout()
                            except Exception:
                                pass
                            return code, uid
                    except Exception:
                        continue
                time.sleep(poll_every)
                try:
                    M.select("INBOX")
                except Exception:
                    pass
                continue

            # 2) RECENT + SUBJECT
            try:
                typ, data = imap_search_utf8(M, 'RECENT', 'SUBJECT', f'"{subject_search}"')
                if typ == 'OK' and data and data[0]:
                    uids = [int(x) for x in data[0].split()]
                    uids = sorted(uids, reverse=True)
                else:
                    uids = []
            except Exception:
                uids = []

            if uids:
                for uid in uids:
                    try:
                        subj, body, date_hdr = uid_fetch_text(M, uid)
                        msg_dt = parse_email_date(date_hdr)
                        code = extract_transfer_code_from_text(subj, body)
                        if not code:
                            m2 = generic_digits_re.search(body or "") or generic_digits_re.search(subj or "")
                            if m2:
                                code = m2.group(1)
                        if code and message_time_matches_now(msg_dt):
                            try:
                                M.logout()
                            except Exception:
                                pass
                            return code, uid
                    except Exception:
                        continue
                time.sleep(poll_every)
                try:
                    M.select("INBOX")
                except Exception:
                    pass
                continue

            # 3) SUBJECT (todos)
            try:
                typ, data = imap_search_utf8(M, 'SUBJECT', f'"{subject_search}"')
                if typ == 'OK' and data and data[0]:
                    uids = [int(x) for x in data[0].split()]
                    uids = sorted(uids, reverse=True)
                else:
                    uids = []
            except Exception:
                uids = []

            if uids:
                for uid in uids:
                    try:
                        subj, body, date_hdr = uid_fetch_text(M, uid)
                        msg_dt = parse_email_date(date_hdr)
                        code = extract_transfer_code_from_text(subj, body)
                        if not code:
                            m2 = generic_digits_re.search(body or "") or generic_digits_re.search(subj or "")
                            if m2:
                                code = m2.group(1)
                        if code and message_time_matches_now(msg_dt):
                            try:
                                M.logout()
                            except Exception:
                                pass
                            return code, uid
                    except Exception:
                        continue
                time.sleep(poll_every)
                try:
                    M.select("INBOX")
                except Exception:
                    pass
                continue

            # 4) Fallback: UNSEEN generic - buscar frase exacta en cuerpo
            try:
                typ, data = imap_search_utf8(M, 'UNSEEN')
                if typ == 'OK' and data and data[0]:
                    uids_unseen = [int(x) for x in data[0].split()]
                    uids_unseen = sorted(uids_unseen, reverse=True)
                else:
                    uids_unseen = []
            except Exception:
                uids_unseen = []

            for uid in uids_unseen:
                try:
                    subj, body, date_hdr = uid_fetch_text(M, uid)
                    msg_dt = parse_email_date(date_hdr)
                    m = TRANSFER_CODE_RE.search(body or "")
                    code = None
                    if m:
                        code = m.group(1)
                    else:
                        m2 = generic_digits_re.search(body or "") or generic_digits_re.search(subj or "")
                        if m2:
                            code = m2.group(1)
                    if code and message_time_matches_now(msg_dt):
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return code, uid
                except Exception:
                    continue

            # 5) Fallback: revisar últimos N mensajes por cuerpo
            try:
                typ_all, data_all = M.uid('SEARCH', None, 'ALL')
                if typ_all == 'OK' and data_all and data_all[0]:
                    all_uids = [int(x) for x in data_all[0].split()]
                    check_uids = sorted(all_uids[-200:], reverse=True)
                else:
                    check_uids = []
            except Exception:
                check_uids = []

            for uid in check_uids:
                try:
                    subj, body, date_hdr = uid_fetch_text(M, uid)
                    msg_dt = parse_email_date(date_hdr)
                    m = TRANSFER_CODE_RE.search(body or "")
                    if m and message_time_matches_now(msg_dt):
                        found_code = m.group(1)
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return found_code, uid
                except Exception:
                    continue

            time.sleep(poll_every)
            try:
                M.select("INBOX")
            except Exception:
                pass

        raise TimeoutError("Mail de confirmación (Envío de código) no llegó a tiempo (timeout)")
    finally:
        if M:
            try:
                M.logout()
            except Exception:
                pass


# ---------------------------
# SELENIUM helpers (OTP + clicks + frames + shadow)
# ---------------------------
def find_otp_input_and_debug(driver: webdriver.Chrome, wait: WebDriverWait, timeout: int = 10):
    try:
        el = driver.find_element(By.ID, OTP_FIELD_ID)
        if el and el.is_displayed():
            return el
    except Exception:
        pass

    try:
        el = driver.find_element(By.NAME, OTP_FIELD_NAME)
        if el and el.is_displayed():
            return el
    except Exception:
        pass

    # probar iframes (simple scan)
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for fr in iframes:
            try:
                driver.switch_to.frame(fr)
                try:
                    el = driver.find_element(By.ID, OTP_FIELD_ID)
                    if el and el.is_displayed():
                        driver.switch_to.default_content()
                        return el
                except Exception:
                    pass
                try:
                    el = driver.find_element(By.NAME, OTP_FIELD_NAME)
                    if el and el.is_displayed():
                        driver.switch_to.default_content()
                        return el
                except Exception:
                    pass
                cand = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='tel'], input[inputmode='numeric'], input[type='number']")
                for el in cand:
                    try:
                        if el.is_displayed():
                            driver.switch_to.default_content()
                            return el
                    except Exception:
                        continue
                driver.switch_to.default_content()
            except Exception:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
    except Exception:
        pass

    # heurística JS fallback
    js = r"""
    (function(){
      const inputs = Array.from(document.querySelectorAll('input'));
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
      if(scored.length === 0) return null;
      return scored[0].sc > 0 ? scored[0].el : null;
    })();
    """
    try:
        el = driver.execute_script(js)
        if el:
            try:
                if el.is_displayed():
                    return el
            except Exception:
                pass
    except Exception:
        pass

    # último recurso: devolver None (no preguntar al usuario)
    raise TimeoutException("No se encontró input OTP automáticamente")


def _find_in_shadow_dom(driver: webdriver.Chrome, css_selector: str):
    js = r"""
    const sel = arguments[0];
    function deepQuery(selector, root=document){
      const parts = selector.split('>>>').map(s=>s.trim());
      let cur = root;
      for(const p of parts){
        if(!cur) return null;
        const el = cur.querySelector(p);
        if(!el) return null;
        if(parts.indexOf(p) !== parts.length-1){
          cur = el.shadowRoot || el;
        } else {
          return el;
        }
      }
      return cur;
    }
    let q = document.querySelector(sel);
    if(q) return q;
    function walk(node){
      if(node.querySelector){
        let t = node.querySelector(sel);
        if(t) return t;
      }
      const children = node.children || [];
      for(let i=0;i<children.length;i++){
        const c = children[i];
        if(c.shadowRoot){
          const found = walk(c.shadowRoot);
          if(found) return found;
        }
        const found2 = walk(c);
        if(found2) return found2;
      }
      return null;
    }
    return walk(document);
    """
    try:
        res = driver.execute_script(js, css_selector)
        return res
    except Exception:
        return None


def _recursive_search_frames(driver: webdriver.Chrome, finder: Callable[[], Optional[webdriver.remote.webelement.WebElement]], depth: int = 0, max_depth: int = 6) -> Optional[webdriver.remote.webelement.WebElement]:
    if depth > max_depth:
        return None
    try:
        el = finder()
        if el:
            try:
                if el.is_displayed():
                    return el
            except Exception:
                return el
    except Exception:
        pass
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        iframes = []
    for i, fr in enumerate(iframes):
        try:
            try:
                driver.switch_to.frame(fr)
            except Exception:
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(i)
                except Exception:
                    driver.switch_to.default_content()
                    continue
            found = _recursive_search_frames(driver, finder, depth + 1, max_depth)
            if found:
                return found
            try:
                driver.switch_to.parent_frame()
            except Exception:
                driver.switch_to.default_content()
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
    return None


def locate_element_across_frames(driver: webdriver.Chrome, by: By, value: str, timeout: float = 15.0, poll: float = 0.5) -> Optional[webdriver.remote.webelement.WebElement]:
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        def finder():
            try:
                return driver.find_element(by, value)
            except Exception:
                return None
        try:
            found = _recursive_search_frames(driver, finder)
            if found:
                return found
        except Exception as e:
            last_exc = e
        try:
            driver.switch_to.default_content()
            el = finder()
            if el:
                return el
        except Exception:
            pass
        def finder_text_accept():
            try:
                candidates = driver.find_elements(By.XPATH, "//a[contains(translate(normalize-space(.), 'ACEPTAR', 'aceptar'), 'acept') or contains(translate(normalize-space(.), 'CONFIRMAR', 'confirmar'), 'confirm') or contains(translate(normalize-space(.), 'VERIFICAR', 'verificar'), 'verif') or contains(translate(normalize-space(.), 'ENVIAR', 'enviar'), 'enviar') or //button]")
                for c in candidates:
                    try:
                        if c.is_displayed():
                            return c
                    except Exception:
                        return c
                return None
            except Exception:
                return None
        try:
            driver.switch_to.default_content()
            found_text = _recursive_search_frames(driver, finder_text_accept)
            if found_text:
                return found_text
        except Exception:
            pass
        try:
            driver.switch_to.default_content()
            sd = _find_in_shadow_dom(driver, value if by == By.CSS_SELECTOR else value)
            if sd:
                return sd
        except Exception:
            pass
        time.sleep(poll)
    return None


def safe_click_element(driver: webdriver.Chrome, el: webdriver.remote.webelement.WebElement) -> bool:
    try:
        el.click()
        return True
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].scrollIntoView(true);", el)
        driver.execute_script("arguments[0].click();", el)
        return True
    except Exception:
        pass
    try:
        onclick = el.get_attribute("onclick")
        if onclick:
            driver.execute_script(onclick)
            return True
    except Exception:
        pass
    return False


def find_first_numeric_input(driver: webdriver.Chrome, timeout: float = 10.0) -> Optional[webdriver.remote.webelement.WebElement]:
    deadline = time.time() + timeout
    candidates_selectors = [
        ("id", "id_sc_field_importe"),
        ("id", "id_sc_field_monto"),
        ("id", "id_sc_field_valor"),
        ("name", "monto"),
        ("name", "importe"),
        ("name", "valor"),
        ("css", "input[inputmode='numeric']"),
        ("css", "input[type='number']"),
        ("css", "input[type='tel']"),
        ("css", "input[type='text']"),
    ]
    while time.time() < deadline:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        for typ, sel in candidates_selectors:
            try:
                if typ == "id":
                    el = locate_element_across_frames(driver, By.ID, sel, timeout=1)
                elif typ == "name":
                    el = locate_element_across_frames(driver, By.NAME, sel, timeout=1)
                else:
                    el = locate_element_across_frames(driver, By.CSS_SELECTOR, sel, timeout=1)
                if el:
                    try:
                        if el.is_displayed():
                            return el
                    except Exception:
                        return el
            except Exception:
                continue
        try:
            driver.switch_to.default_content()
            inputs = driver.find_elements(By.XPATH, "//input[(@type='text' or @type='number' or @type='tel') and not(contains(@style,'display:none'))]")
            for inp in inputs:
                try:
                    if inp.is_displayed():
                        name = (inp.get_attribute("name") or "").lower()
                        idv = (inp.get_attribute("id") or "").lower()
                        ph = (inp.get_attribute("placeholder") or "").lower()
                        if any(k in name for k in ("monto", "importe", "valor", "amount", "cantidad")) or any(k in idv for k in ("monto", "importe", "valor", "amount")):
                            return inp
                except Exception:
                    continue
        except Exception:
            pass
        time.sleep(0.5)
    return None


def set_input_value(driver: webdriver.Chrome, el: webdriver.remote.webelement.WebElement, value: str):
    try:
        el.clear()
    except Exception:
        try:
            driver.execute_script("arguments[0].value = '';", el)
        except Exception:
            pass
    try:
        el.send_keys(value)
    except Exception:
        try:
            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));", el, value)
        except Exception:
            pass


def select_select2_option_choose_varios_or_last(driver: webdriver.Chrome, combo_css: str, timeout: float = 10.0) -> bool:
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    combo = locate_element_across_frames(driver, By.CSS_SELECTOR, combo_css, timeout=8)
    if not combo:
        return False
    if not safe_click_element(driver, combo):
        return False
    time.sleep(1.0)
    options = []
    try:
        options = driver.execute_script("return Array.from(document.querySelectorAll('li.select2-results__option'));")
        if not options:
            options = driver.execute_script("return Array.from(document.querySelectorAll('ul.select2-results__options li'));")
    except Exception:
        options = []
    if not options:
        try:
            opts = driver.find_elements(By.CSS_SELECTOR, "li.select2-results__option")
            options = opts
        except Exception:
            options = []
    if not options:
        try:
            native_opts = driver.find_elements(By.TAG_NAME, "option")
            if native_opts:
                for o in native_opts[::-1]:
                    try:
                        txt = (o.text or "").strip()
                        if txt and "varios" in txt.lower():
                            safe_click_element(driver, o)
                            return True
                    except Exception:
                        continue
                try:
                    safe_click_element(driver, native_opts[-1])
                    return True
                except Exception:
                    pass
        except Exception:
            pass
        return False
    opts_list = options if isinstance(options, list) else list(options)
    chosen = None
    for opt in opts_list:
        try:
            text = (opt.text or "").strip()
            if text and "varios" in text.lower():
                chosen = opt
                break
        except Exception:
            continue
    if not chosen:
        for opt in reversed(opts_list):
            try:
                if getattr(opt, "is_displayed", lambda: True)():
                    chosen = opt
                    break
            except Exception:
                chosen = opt
                break
    if not chosen:
        return False
    try:
        safe_click_element(driver, chosen)
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", chosen)
            return True
        except Exception:
            return False


def click_accept_button(driver: webdriver.Chrome, wait: WebDriverWait, timeout: float = 15.0):
    try:
        el = locate_element_across_frames(driver, By.ID, ACCEPT_BTN_ID, timeout=timeout)
        if el:
            ok = safe_click_element(driver, el)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return ok
        el = locate_element_across_frames(driver, By.CSS_SELECTOR, f"#{ACCEPT_BTN_ID}", timeout=6)
        if el:
            ok = safe_click_element(driver, el)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return ok
        el = locate_element_across_frames(driver, By.XPATH, "//a[contains(., 'Aceptar') or contains(., 'Confirmar') or contains(., 'Verificar') or contains(., 'Enviar')]", timeout=6)
        if el:
            ok = safe_click_element(driver, el)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return ok
        return False
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False


def click_confirm_button(driver: webdriver.Chrome, wait: WebDriverWait, timeout: float = 15.0):
    try:
        el = locate_element_across_frames(driver, By.ID, CONFIRM_BTN_ID, timeout=timeout)
        if el:
            ok = safe_click_element(driver, el)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return ok
        el = locate_element_across_frames(driver, By.CSS_SELECTOR, f"#{CONFIRM_BTN_ID}", timeout=6)
        if el:
            ok = safe_click_element(driver, el)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return ok
        el = locate_element_across_frames(driver, By.XPATH, "//a[contains(@title,'Confirmar') or contains(., 'Aceptar') or contains(., 'Confirmar')]", timeout=6)
        if el:
            ok = safe_click_element(driver, el)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return ok
        return False
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False


# ---------------------------
# HISTORIAL DE TRANSFERENCIAS
# ---------------------------
def create_transfer_log_file() -> str:
    """
    Crea un archivo de log de transferencias con timestamp.
    Retorna la ruta del archivo creado.
    """
    # Crear carpeta de logs si no existe
    log_dir = os.path.join(os.getcwd(), "transfer_logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Generar nombre de archivo con timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"transferencias_{timestamp}.txt")
    
    # Crear archivo con encabezado
    try:
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"HISTORIAL DE TRANSFERENCIAS - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
        _orig_print(f"Archivo de log creado: {log_file}")
        return log_file
    except Exception as e:
        _orig_print(f"Error creando archivo de log: {e}")
        return ""


def log_transfer(log_file: str, transfer_number: int, cbu_origen: str, cbu_destino: str, monto: str, status: str = "COMPLETADA"):
    """
    Agrega una transferencia al archivo de log.
    """
    if not log_file or not os.path.exists(log_file):
        return
    
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"Transferencia #{transfer_number}: {status}\n")
            f.write(f"  CBU de ORIGEN:  {cbu_origen}\n")
            f.write(f"  CBU de DESTINO: {cbu_destino}\n")
            f.write(f"  MONTO:          ${monto}\n")
            f.write(f"  Fecha/Hora:     {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write("-" * 80 + "\n\n")
        _orig_print(f"Transfer #{transfer_number} registrada en log")
    except Exception as e:
        _orig_print(f"❌ Error escribiendo en log: {e}")


# ---------------------------
# CSV HELPERS
# ---------------------------
def select_csv_file() -> Optional[str]:
    """
    Abre un diálogo para seleccionar un archivo CSV.
    Devuelve la ruta del archivo o None si se cancela.
    Compatible con Windows, macOS y Linux.
    """
    import platform
    system = platform.system()
    
    # Método 1: Intentar usar tkinter (funciona en Windows, macOS y Linux)
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        # Crear una ventana raíz oculta
        root = tk.Tk()
        root.withdraw()  # Ocultar la ventana principal
        root.attributes('-topmost', True)  # Traer al frente
        
        # Abrir diálogo de selección de archivo
        file_path = filedialog.askopenfilename(
            title="Por favor, seleccione el archivo CSV",
            filetypes=[
                ("Archivos CSV", "*.csv"),
                ("Todos los archivos", "*.*")
            ]
        )
        
        root.destroy()  # Cerrar la ventana
        
        if file_path:
            _orig_print(f"Archivo seleccionado: {file_path}")
            return file_path
        else:
            _orig_print("Selección cancelada")
            return None
            
    except Exception as e:
        _orig_print(f"Error con tkinter: {e}")
    
    # Método 2: En macOS, intentar AppleScript
    if system == "Darwin":
        try:
            import subprocess
            script = '''
            tell application "System Events"
                activate
                set theFile to choose file with prompt "Por favor, adjunte el CSV" of type {"csv", "public.comma-separated-values-text"}
                return POSIX path of theFile
            end tell
            '''
            result = subprocess.run(['osascript', '-e', script], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=300)
            if result.returncode == 0:
                file_path = result.stdout.strip()
                return file_path if file_path else None
            else:
                _orig_print("AppleScript cancelado o falló")
        except Exception as e:
            _orig_print(f"Error con AppleScript: {e}")
    
    # Método 3: Fallback - input manual (funciona en todos los sistemas)
    _orig_print("\n=== Por favor, adjunte el CSV ===")
    file_path = input("Ingrese la ruta completa del archivo CSV: ").strip()
    # Remover comillas si las hay
    file_path = file_path.strip('"').strip("'")
    if file_path and os.path.isfile(file_path):
        return file_path
    else:
        _orig_print(f"Archivo no encontrado: {file_path}")
        return None


def read_transfers_from_csv(csv_path: str) -> List[Dict[str, Any]]:
    """
    Lee el CSV y devuelve una lista de diccionarios con los datos de cada transferencia.
    Cada diccionario tiene al menos las claves: 'CBU_DESTINO', 'MONTO', y el resto de columnas disponibles.
    """
    transfers = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Verificar que tenga las columnas requeridas
                if 'CBU_DESTINO' in row and 'MONTO' in row:
                    transfers.append(dict(row))
                else:
                    _orig_print(f"ADVERTENCIA: Fila sin CBU_DESTINO o MONTO: {row}")
    except Exception as e:
        _orig_print(f"ERROR leyendo CSV: {e}")
        return []
    
    return transfers


# ---------------------------
# Opción B (secuencia principal)
# ---------------------------
def opcion_b_selenium(cbu_destino: str = "0000155300000000001362", monto: str = "10000") -> Tuple[bool, str]:
    """
    Ejecuta una transferencia completa en una nueva instancia de navegador.
    Devuelve (success: bool, cbu_origen: str).
    - success: True si la transferencia se consideró exitosa, False en caso contrario.
    - cbu_origen: CBU de la cuenta origen seleccionada (vacío si falla antes de seleccionar cuenta).
    IMPORTANTE: no pide inputs manuales. Si OTP o código de transferencia no llegan -> devuelve False.
    """
    cbu_origen_selected = ""  # Variable para guardar el CBU origen seleccionado
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--remote-debugging-port=0")  # Use random port
    if HEADLESS:
        # usar modo headless moderno si disponible
        options.add_argument("--headless=new")

    # Crear driver con Selenium 4 usando ChromeService
    try:
        from selenium.webdriver.chrome.service import Service as ChromeService
    except Exception:
        ChromeService = None

    try:
        if ChromeService is not None:
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        else:
            # Compat con Selenium 3: usar constructor simple sin executable_path
            driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"ERROR_DEBUG:ChromeDriverManager falló: {str(e)}")
        # Fallback a chromedriver en PATH usando Service si es posible
        try:
            if ChromeService is not None:
                service = ChromeService()
                driver = webdriver.Chrome(service=service, options=options)
            else:
                driver = webdriver.Chrome(options=options)
        except Exception as e2:
            print(f"ERROR_DEBUG:Fallo creando driver con fallback: {e2}")
            raise
    
    # Set proper timeouts to prevent hanging
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(10)

    success = False
    try:
        print("ERROR_DEBUG:Iniciando navegación del navegador")
        driver.get(URL_B)
        wait = WebDriverWait(driver, 30)
        print("ERROR_DEBUG:Página cargada, buscando campos de login")

        # Usuario
        print("ERROR_DEBUG:Buscando campo de usuario")
        user_input = wait.until(EC.presence_of_element_located((By.ID, FIELD_LOGIN_ID)))
        try:
            user_input.clear()
        except Exception:
            pass
        user_input.send_keys(USER_B)
        print("ERROR_DEBUG:Usuario ingresado")

        # Password
        pass_input = wait.until(EC.presence_of_element_located((By.ID, FIELD_PASS_ID)))
        try:
            pass_input.clear()
        except Exception:
            pass
        pass_input.send_keys(PASS_B)

        # Click Ingresar
        login_btn = None
        for by_name, sel in [("CSS_SELECTOR", LOGIN_BTN_CSS), ("XPATH", "//input[@class='button' and @value='Ingresar']"), ("XPATH", "//button[contains(., 'Ingresar')]")]:
            try:
                login_btn = wait.until(EC.element_to_be_clickable((getattr(By, by_name), sel)))
                break
            except Exception:
                login_btn = None
        if not login_btn:
            # no se encontró el botón -> considerar fallo de transferencia
            return (False, cbu_origen_selected)
        try:
            login_btn.click()
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", login_btn)
            except Exception:
                pass

        # Esperar posible redirección al 2FA
        try:
            wait.until(EC.url_contains("app_control_2fa"))
        except Exception:
            # no necesariamente fatal, seguir intentando encontrar OTP
            pass

        # Buscar campo OTP (si no hay -> fallo)
        try:
            otp_input = find_otp_input_and_debug(driver, wait, timeout=10)
        except Exception:
            # no se encontró campo OTP -> considerar transferencia fallida
            return (False, cbu_origen_selected)

        # Preparar baseline UID para IMAP
        since_uid = None
        if GMAIL_USER and GMAIL_PASS:
            try:
                Mtmp = imap_connect(GMAIL_IMAP_HOST, GMAIL_USER, GMAIL_PASS)
                all_uids = uid_search_all(Mtmp, "ALL")
                since_uid = max(all_uids) if all_uids else 0
                try:
                    Mtmp.logout()
                except Exception:
                    pass
            except Exception:
                since_uid = None

        # Poll IMAP para OTP (si no llega -> marcar fallo)
        otp_code = ""
        try:
            if GMAIL_USER and GMAIL_PASS:
                otp_code, got_uid = get_latest_otp_gmail(user=GMAIL_USER, pwd=GMAIL_PASS, timeout_sec=120, poll_every=2.0, since_uid=since_uid)
            else:
                # sin credenciales gmail -> no puede operar
                return (False, cbu_origen_selected)
        except Exception:
            # No se obtuvo OTP -> marcar falla
            return (False, cbu_origen_selected)

        # Pegar OTP
        try:
            try:
                otp_input.clear()
            except Exception:
                pass
            otp_input.send_keys(otp_code)
        except Exception:
            # no se pudo pegar OTP -> fallo
            return (False, cbu_origen_selected)

        # Buscar botón validar/confirmar y click (si existe)
        validate_btn = None
        for by_name, sel in [
            ("XPATH", "//input[@type='button' and (contains(@value,'Validar') or contains(@value,'Confirmar') or contains(@value,'Verificar') or contains(@value,'Enviar'))]"),
            ("XPATH", "//button[contains(., 'Validar') or contains(., 'Confirmar') or contains(., 'Verificar') or contains(., 'Enviar')]"),
            ("CSS_SELECTOR", "input.button[onclick*='nm_atualiza']"),
        ]:
            try:
                validate_btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((getattr(By, by_name), sel)))
                break
            except Exception:
                validate_btn = None

        if validate_btn:
            try:
                validate_btn.click()
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", validate_btn)
                except Exception:
                    pass

        # Click en Aceptar (sc_submit_ajax_bot)
        try:
            click_accept_button(driver, wait, timeout=20)
        except Exception:
            pass

        time.sleep(1.0)

        # Click en Confirmar final (sub_form_b)
        ok_confirm = False
        try:
            ok_confirm = click_confirm_button(driver, wait, timeout=12)
        except Exception:
            ok_confirm = False

        if ok_confirm:
            time.sleep(3)
            try:
                # Esperar 2s
                time.sleep(2)
                # Doble click izquierdo en el centro de la pantalla
                try:
                    body_el = driver.find_element(By.TAG_NAME, "body")
                    try:
                        ActionChains(driver).double_click(body_el).perform()
                    except Exception:
                        # Fallback: mover al centro del body y doble click
                        w = body_el.size.get('width', 0)
                        h = body_el.size.get('height', 0)
                        ActionChains(driver).move_to_element_with_offset(body_el, max(1, w//2), max(1, h//2)).double_click().perform()
                except Exception:
                    pass
                # Esperar 1s adicional
                time.sleep(1)
                # Navegar directamente a TRANSFER_URL
                driver.get(TRANSFER_URL)
                time.sleep(3)
            except Exception:
                pass

            # --- PARTE 1: Verificar saldo de cuentas origen y seleccionar una con saldo suficiente ---
            try:
                # Esperar 3 segundos antes de buscar el select de cuentas
                time.sleep(3)
                # Buscar el select de cuentas origen
                print("ERROR_DEBUG:Buscando select de cuentas origen...")
                select_origen = locate_element_across_frames(driver, By.ID, "id_sc_field_idcuenta", timeout=15)
                
                if not select_origen:
                    print("ERROR_DEBUG:No se encontró el select de cuentas origen")
                    return (False, cbu_origen_selected)
                
                # Obtener todas las opciones del select
                try:
                    options = select_origen.find_elements(By.TAG_NAME, "option")
                    print(f"ERROR_DEBUG:Encontradas {len(options)} cuentas origen")
                except Exception as e:
                    print(f"ERROR_DEBUG:Error obteniendo opciones del select: {e}")
                    return (False, cbu_origen_selected)
                
                if not options:
                    print("ERROR_DEBUG:No hay cuentas origen disponibles")
                    return (False, cbu_origen_selected)
                
                # Convertir monto a float para comparación
                # El CSV viene en formato inglés (punto decimal): 20000.00
                try:
                    monto_str = str(monto).strip()
                    # Detectar si es formato argentino (con coma decimal) o inglés (con punto decimal)
                    if ',' in monto_str and '.' in monto_str:
                        # Formato argentino: 1.000,50 -> eliminar punto (miles) y reemplazar coma por punto
                        monto_float = float(monto_str.replace('.', '').replace(',', '.'))
                    elif ',' in monto_str:
                        # Solo coma: formato argentino: 1000,50
                        monto_float = float(monto_str.replace(',', '.'))
                    else:
                        # Solo punto o sin separadores: formato inglés: 1000.50 o 1000
                        monto_float = float(monto_str)
                except Exception as e:
                    print(f"ERROR_DEBUG:Error convirtiendo monto '{monto}': {e}")
                    monto_float = 0
                
                print(f"ERROR_DEBUG:Monto a transferir: {monto_float}")
                
                # Iterar sobre cada cuenta origen para verificar saldo
                cuenta_seleccionada = None
                for idx, option in enumerate(options):
                    try:
                        cuenta_text = option.text
                        cuenta_value = option.get_attribute("value")
                        print(f"ERROR_DEBUG:Verificando cuenta {idx+1}: {cuenta_text}")
                        
                        # Seleccionar esta opción
                        try:
                            driver.execute_script("arguments[0].selected = true; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", option)
                            time.sleep(1)  # Esperar a que se actualice el saldo
                        except Exception as e:
                            print(f"ERROR_DEBUG:Error seleccionando opción: {e}")
                            continue
                        
                        # Buscar el campo de saldo
                        try:
                            saldo_field = locate_element_across_frames(driver, By.ID, "id_sc_field_saldo", timeout=5)
                            if not saldo_field:
                                print(f"ERROR_DEBUG:No se encontró campo de saldo para cuenta {idx+1}")
                                continue
                            
                            saldo_text = saldo_field.get_attribute("value") or ""
                            print(f"ERROR_DEBUG:Saldo leído (raw): '{saldo_text}'")
                            
                            # Convertir saldo a float (formato: "24.500,00" -> 24500.00)
                            try:
                                saldo_float = float(saldo_text.replace('.', '').replace(',', '.'))
                            except Exception as e:
                                print(f"ERROR_DEBUG:Error convirtiendo saldo '{saldo_text}': {e}")
                                continue
                            
                            print(f"ERROR_DEBUG:Saldo: {saldo_float}, Monto: {monto_float}")
                            
                            # Verificar si el saldo es suficiente
                            if saldo_float >= monto_float:
                                print(f"ERROR_DEBUG:✅ Cuenta con saldo suficiente encontrada: {cuenta_text}")
                                cuenta_seleccionada = {
                                    'option': option,
                                    'text': cuenta_text,
                                    'value': cuenta_value,
                                    'saldo': saldo_float
                                }
                                break
                            else:
                                print(f"ERROR_DEBUG:❌ Saldo insuficiente ({saldo_float} < {monto_float})")
                        except Exception as e:
                            print(f"ERROR_DEBUG:Error verificando saldo: {e}")
                            continue
                    except Exception as e:
                        print(f"ERROR_DEBUG:Error procesando cuenta {idx+1}: {e}")
                        continue
                
                # Verificar si se encontró una cuenta con saldo suficiente
                if not cuenta_seleccionada:
                    print("ERROR_DEBUG:❌ Ninguna cuenta tiene saldo suficiente para esta transferencia")
                    _orig_print("\n" + "="*80)
                    _orig_print("❌ TRANSFERENCIA FALLIDA: Ninguna de las cuentas tiene saldo suficiente")
                    _orig_print(f"   Monto requerido: ${monto_float:,.2f}")
                    _orig_print("="*80 + "\n")
                    return (False, cbu_origen_selected)
                
                # Seleccionar la cuenta encontrada (por si no quedó seleccionada)
                try:
                    driver.execute_script("arguments[0].selected = true; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", cuenta_seleccionada['option'])
                    time.sleep(0.5)
                    print(f"ERROR_DEBUG:Cuenta origen seleccionada: {cuenta_seleccionada['text']}")
                    
                    # Extraer CBU origen del texto (formato: "BPMUP SRL871 (0000155300000000000871) PONDRA.CUARTO.BALDE")
                    try:
                        import re as re_module
                        cbu_match = re_module.search(r'\((\d{22})\)', cuenta_seleccionada['text'])
                        if cbu_match:
                            cbu_origen_selected = cbu_match.group(1)
                            print(f"ERROR_DEBUG:CBU origen extraído: {cbu_origen_selected}")
                    except Exception as e:
                        print(f"ERROR_DEBUG:Error extrayendo CBU origen: {e}")
                except Exception as e:
                    print(f"ERROR_DEBUG:Error en selección final: {e}")
                
                # Ahora sí, pegar la cuenta destino
                print("ERROR_DEBUG:Buscando campo cuenta destino...")
                cuenta_el = locate_element_across_frames(driver, By.ID, CUENTA_FIELD_ID, timeout=15)
                if cuenta_el:
                    try:
                        cuenta_el.clear()
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].value='';", cuenta_el)
                        except Exception:
                            pass
                    try:
                        cuenta_el.send_keys(cbu_destino)
                        print(f"ERROR_DEBUG:CBU destino pegado: {cbu_destino}")
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));", cuenta_el, cbu_destino)
                            print(f"ERROR_DEBUG:CBU destino pegado (JS): {cbu_destino}")
                        except Exception:
                            pass
                # primer Próximo
                prox_el = locate_element_across_frames(driver, By.ID, PRIMERO_BTN_ID, timeout=12)
                if prox_el:
                    safe_click_element(driver, prox_el)
                time.sleep(5)
                time.sleep(2)
                prox_el2 = locate_element_across_frames(driver, By.ID, PRIMERO_BTN_ID, timeout=10)
                if prox_el2:
                    safe_click_element(driver, prox_el2)
                time.sleep(2)
                amount_input = find_first_numeric_input(driver, timeout=12)
                if amount_input:
                    set_input_value(driver, amount_input, str(monto))
                # select2
                select_select2_option_choose_varios_or_last(driver, SELECT2_COMBO_CSS, timeout=12)
                # último Próximo
                prox_el3 = locate_element_across_frames(driver, By.ID, PRIMERO_BTN_ID, timeout=12)
                if prox_el3:
                    safe_click_element(driver, prox_el3)
                    time.sleep(3)
            except Exception:
                # si algo falla aquí, consideramos transferencia fallida
                return (False, cbu_origen_selected)
        else:
            # if confirm not clicked, no podemos avanzar -> fallo
            return (False, cbu_origen_selected)

        # --- AHORA: volver al mail para leer el código de confirmación de la transferencia ---
        transfer_code = ""
        try:
            if GMAIL_USER and GMAIL_PASS:
                # Esperas previas solicitadas
                time.sleep(3)
                time.sleep(3)

                # Intentar UNA vez obtener el código de transferencia (sin reenvíos)
                try:
                    transfer_code, t_uid = get_latest_transfer_code_gmail(user=GMAIL_USER, pwd=GMAIL_PASS, subject_search="Envío de código", timeout_sec=35, poll_every=3.0)
                except Exception:
                    # no llegó el código -> marcar falla
                    return (False, cbu_origen_selected)
            else:
                return (False, cbu_origen_selected)
        except Exception:
            return (False, cbu_origen_selected)

        # Pegar código en input token_cliente
        try:
            token_el = locate_element_across_frames(driver, By.ID, TOKEN_FIELD_ID, timeout=75)
            if token_el:
                try:
                    # clic izquierdo en el input, espera 2s, como pediste
                    try:
                        token_el.click()
                    except Exception:
                        safe_click_element(driver, token_el)
                    time.sleep(2)
                    
                    # Timeout de 1 minuto 15 segundos para pegar el token
                    start_time = time.time()
                    token_pasted = False
                    
                    while time.time() - start_time < 75:  # 75 segundos = 1 minuto 15 segundos
                        if transfer_code:  # Si ya tenemos el código, pegarlo
                            set_input_value(driver, token_el, transfer_code)
                            token_pasted = True
                            break
                        time.sleep(1)  # Esperar 1 segundo y verificar de nuevo
                    
                    if not token_pasted:
                        return False  # Timeout: no se pudo pegar el token en 75 segundos
                    
                    time.sleep(3)
                except Exception:
                    return (False, cbu_origen_selected)
            else:
                return (False, cbu_origen_selected)
        except Exception:
            return (False, cbu_origen_selected)

        # Presionar Confirmar final
        try:
            conf_btn = locate_element_across_frames(driver, By.ID, TOKEN_CONFIRM_BTN_ID, timeout=15)
            if conf_btn:
                ok_conf = safe_click_element(driver, conf_btn)
                if ok_conf:
                    # esperar efectos
                    time.sleep(10)
                    success = True
                else:
                    success = False
            else:
                success = False
        except Exception:
            success = False

        # breve check post-transfer (no es determinante)
        try:
            wait.until(lambda d: "app_control_2fa" not in d.current_url)
        except Exception:
            pass

        return (success, cbu_origen_selected)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ---------------------------
# MAIN: ejecutar transferencias una por una, cada una en su propia ventana.
# Si fallan, reintentar pasadas hasta que se completen (espera 3s entre reintentos).
# ---------------------------
def main():
    # Primero: abrir diálogo para seleccionar CSV
    _orig_print("Abriendo diálogo para seleccionar CSV...")
    csv_path = select_csv_file()
    
    if not csv_path:
        _orig_print("ERROR: No se seleccionó ningún archivo CSV. Abortando.")
        return
    
    _orig_print(f"CSV seleccionado: {csv_path}")
    
    # Leer transferencias del CSV
    transfers = read_transfers_from_csv(csv_path)
    
    if not transfers:
        _orig_print("ERROR: No se encontraron transferencias válidas en el CSV. Abortando.")
        return
    
    _orig_print(f"Se encontraron {len(transfers)} transferencias en el CSV")
    
    # Crear archivo de log de transferencias
    log_file = create_transfer_log_file()
    
    # Estructura para tracking: diccionario {índice: {'transfer': datos, 'status': 'pending'|'done'|'failed'}}
    transfer_status: Dict[int, Dict[str, Any]] = {}
    for idx, transfer in enumerate(transfers, start=1):
        transfer_status[idx] = {
            'transfer': transfer,
            'status': 'pending',
            'cbu_destino': transfer.get('CBU_DESTINO', ''),
            'cbu_origen': transfer.get('CBU_ORIGEN', ''),  # Del CSV si está disponible
            'monto': transfer.get('MONTO', '')
        }
    
    failed: List[int] = []
    pass_number = 1

    # Primera pasada
    for idx in range(1, len(transfers) + 1):
        t_data = transfer_status[idx]
        cbu_destino = t_data['cbu_destino']
        monto = t_data['monto']
        
        print(f"TRANSFE_START:{idx}")
        try:
            ok, cbu_origen = opcion_b_selenium(cbu_destino=cbu_destino, monto=monto)
            if ok:
                print(f"TRANSFE_DONE:{idx}")
                transfer_status[idx]['status'] = 'done'
                transfer_status[idx]['cbu_origen_real'] = cbu_origen  # Guardar CBU origen real
                # Registrar en log
                log_transfer(log_file, idx, cbu_origen, cbu_destino, monto, "COMPLETADA")
            else:
                print(f"TRANSFE_FAILED:{idx}")
                transfer_status[idx]['status'] = 'failed'
                failed.append(idx)
        except KeyboardInterrupt:
            print(f"TRANSFE_FAILED:{idx}")
            transfer_status[idx]['status'] = 'failed'
            failed.append(idx)
            raise
        except Exception as e:
            print(f"ERROR_DEBUG:Excepción en bucle principal: {str(e)}")
            print(f"TRANSFE_FAILED:{idx}")
            transfer_status[idx]['status'] = 'failed'
            failed.append(idx)
        # esperar 2 segundos entre ventanas (pasada inicial)
        time.sleep(2)

    # Resumen de la primera pasada
    completed_first = [str(x) for x in range(1, len(transfers) + 1) if x not in failed]
    failed_first = [str(x) for x in failed]
    comp_str = ",".join(completed_first) if completed_first else "none"
    fail_str = ",".join(failed_first) if failed_first else "none"
    print(f"PASADA_FINALIZADA:Pass {pass_number} — Completadas: {comp_str} — Fallidas: {fail_str}")

    # Reintentar fallidas por pasadas hasta que no queden
    while failed:
        pass_number += 1
        current_failed = list(failed)
        failed = []
        succeeded_this_pass: List[int] = []
        failed_this_pass: List[int] = []

        for idx in current_failed:
            t_data = transfer_status[idx]
            cbu_destino = t_data['cbu_destino']
            monto = t_data['monto']
            
            print(f"TRANSFE_START:{idx}")
            try:
                ok, cbu_origen = opcion_b_selenium(cbu_destino=cbu_destino, monto=monto)
                if ok:
                    print(f"TRANSFE_DONE:{idx}")
                    transfer_status[idx]['status'] = 'done'
                    transfer_status[idx]['cbu_origen_real'] = cbu_origen
                    # Registrar en log
                    log_transfer(log_file, idx, cbu_origen, cbu_destino, monto, "COMPLETADA")
                    succeeded_this_pass.append(idx)
                else:
                    print(f"TRANSFE_FAILED:{idx}")
                    transfer_status[idx]['status'] = 'failed'
                    failed_this_pass.append(idx)
                # esperar 3 segundos entre reintentos individuales
                time.sleep(3)
            except KeyboardInterrupt:
                print(f"TRANSFE_FAILED:{idx}")
                transfer_status[idx]['status'] = 'failed'
                failed_this_pass.append(idx)
                raise
            except Exception as e:
                print(f"ERROR_DEBUG:Excepción en bucle de reintentos: {str(e)}")
                print(f"TRANSFE_FAILED:{idx}")
                transfer_status[idx]['status'] = 'failed'
                failed_this_pass.append(idx)
                time.sleep(3)
                continue

        # preparar lista para la siguiente pasada (si quedaron)
        failed = list(failed_this_pass)

        # imprimir resumen de la pasada
        comp_str = ",".join(str(x) for x in succeeded_this_pass) if succeeded_this_pass else "none"
        fail_str = ",".join(str(x) for x in failed_this_pass) if failed_this_pass else "none"
        print(f"PASADA_FINALIZADA:Pass {pass_number} — Completadas: {comp_str} — Fallidas: {fail_str}")

    # fin del flujo: todas las transferencias se intentaron y las fallidas se reintentaron hasta completar
    # si alguna nunca llega a completarse, el proceso quedará reintentando indefinidamente para esa transferencia.

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        try:
            sys.exit(1)
        except SystemExit:
            pass

