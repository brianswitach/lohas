#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot.py - Automación login + 2FA OTP (IMAP Gmail) con Selenium.
Flujo:
 - SOLO Opción B: Selenium Chrome -> login -> espera OTP en Gmail -> pega OTP ->
   click Aceptar (sc_submit_ajax_bot) -> click Confirmar (sub_form_b) ->
   espera 3s -> navegar a https://app.lohas.eco/form_transferencias/ -> espera 3s ->
   busca campo cuenta -> pega 0000155300000000001409 -> click Próximo ->
   espera 5s -> espera 2s -> click Próximo otra vez -> espera 2s ->
   pega 10000 en campo monto detectado -> abrir select2 'css_idconcepto_bcra_obj' ->
   seleccionar opción "Varios" (si existe) o la última -> click Próximo -> espera 3s ->
   luego vuelve a leer Gmail buscando subject "Envío de código", extrae el código del
   último correo del hilo (texto "Se envía el código para confirmar la transferencia:171052"),
   pega ese código en el campo token_cliente (id_sc_field_token_cliente), espera 3s,
   presiona Confirmar (sc_confirmar_bot) y espera 10 segundos.
Modificado para buscar botones dentro de iframes modales (incluso anidados) y Shadow DOM.
"""

from __future__ import annotations
import os
import re
import sys
import time
import imaplib
import email
import email.header
from typing import List, Optional, Tuple, Callable

# Selenium + webdriver-manager
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------
# CONFIG
# ---------------------------
URL_B = "https://app.lohas.eco/app_Login"
USER_B = "recaudacionp1"
PASS_B = "Prec770!!"
FIELD_LOGIN_ID = "id_sc_field_login"
FIELD_PASS_ID = "id_sc_field_pswd"
LOGIN_BTN_CSS = 'input.button[onclick*="nm_atualiza"]'

# OTP field en la página
OTP_FIELD_ID = "id_sc_field_code"
OTP_FIELD_NAME = "code"

# Botón Aceptar y Confirm
ACCEPT_BTN_ID = "sc_submit_ajax_bot"
CONFIRM_BTN_ID = "sub_form_b"

# URL destino final (reemplazo de clicks en "Transferencias")
TRANSFER_URL = "https://app.lohas.eco/form_transferencias/"

# Campo y botón dentro de la página de transferencias
CUENTA_FIELD_ID = "id_sc_field_cuenta"
CUENTA_TO_PASTE = "0000155300000000001409"
PRIMERO_BTN_ID = "sc_b_stepavc_b"  # "Próximo"

# Select2 combobox CSS (el span que abrimos)
SELECT2_COMBO_CSS = "span.select2-selection.select2-selection--single.css_idconcepto_bcra_obj"

# Token field & Confirm button after transfer confirmation-mail
TOKEN_FIELD_ID = "id_sc_field_token_cliente"
TOKEN_CONFIRM_BTN_ID = "sc_confirmar_bot"

# Gmail IMAP (opcional para OTP y para código de confirmación)
GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")

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

# ---------------------------
# IMAP helpers (igual que antes)
# ---------------------------
def imap_connect(host: str, user: str, pwd: str) -> imaplib.IMAP4_SSL:
    print(f"[IMAP] Conectando a {host} como {user} ...")
    M = imaplib.IMAP4_SSL(host)
    M.login(user, pwd)
    M.select("INBOX")
    print("[IMAP] Conectado y seleccionado INBOX")
    return M

def uid_search_all(M: imaplib.IMAP4_SSL, criteria: str) -> List[int]:
    typ, data = M.uid("SEARCH", None, criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    return [int(x) for x in data[0].split()]

def uid_fetch_text(M: imaplib.IMAP4_SSL, uid: int) -> Tuple[str, str]:
    typ, data = M.uid("FETCH", str(uid), "(RFC822)")
    if typ != "OK" or not data or not data[0]:
        return "", ""
    raw = data[0][1]
    msg = email.message_from_bytes(raw)
    subj = email.header.make_header(email.header.decode_header(msg.get("Subject", "")))
    subject = str(subj)
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
                    plaintexts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
            elif ctype == "text/html" and "attachment" not in disp:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    htmltexts.append(payload.decode(charset, errors="ignore"))
                except Exception:
                    htmltexts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
        if plaintexts:
            body_text = "\n\n".join(plaintexts)
        elif htmltexts:
            body_text = "\n\n".join(strip_tags(h) for h in htmltexts)
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            body_text = payload.decode(charset, errors="ignore")
            if "<html" in body_text.lower():
                body_text = strip_tags(body_text)
        except Exception:
            try:
                body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            except Exception:
                body_text = ""
    return subject, body_text

def imap_search_utf8(M: imaplib.IMAP4_SSL, *parts: str):
    try:
        need_utf8 = any(any(ord(c) > 127 for c in p) for p in parts if isinstance(p, str))
        if need_utf8:
            return M.uid('SEARCH', 'CHARSET', 'UTF-8', *parts)
        else:
            return M.uid('SEARCH', None, *parts)
    except Exception as e:
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
        except Exception as e2:
            print("[IMAP] imap_search fallback failed:", e2)
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
            print(f"[IMAP] Baseline UID tomado: {since_uid}")

        attempt = 0
        while time.time() - start < timeout_sec:
            attempt += 1
            elapsed = int(time.time() - start)
            print(f"[IMAP] Poll attempt #{attempt} (elapsed {elapsed}s) - buscando remitente {KNOWN_SENDER}")

            # Buscar mensajes del remitente
            try:
                typ, data = imap_search_utf8(M, 'ALL', 'FROM', f'"{KNOWN_SENDER}"')
                if typ == 'OK' and data and data[0]:
                    uids = [int(x) for x in data[0].split()]
                    uids = sorted(uids, reverse=True)
                    print(f"[IMAP] UIDs from {KNOWN_SENDER}: {uids[:10]}")
                else:
                    uids = []
            except Exception as e:
                print("[IMAP] Error buscando FROM KNOWN_SENDER:", e)
                uids = []

            for uid in uids:
                if since_uid and uid <= since_uid:
                    continue
                try:
                    print(f"[IMAP] Revisando UID {uid} (del remitente) ...")
                    subject, body = uid_fetch_text(M, uid)
                    print(f"[IMAP]  Subject: {subject!r}")
                    snippet = (body or "")[:800].replace("\n", " ").replace("\r", " ")
                    print(f"[IMAP]  Body snippet: {snippet!s}")
                    otp = extract_otp_from_text(subject, body)
                    if otp:
                        print(f"[IMAP]  >>> OTP EXTRAÍDO: {otp} (uid {uid})")
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return otp, uid
                    else:
                        print(f"[IMAP]  UID {uid} del remitente NO contiene OTP según regex")
                except Exception as e:
                    print(f"[IMAP] Error procesando UID {uid} del remitente: {e}")
                    continue

            # UNSEEN FROM
            try:
                typ, data = imap_search_utf8(M, 'UNSEEN', 'FROM', f'"{KNOWN_SENDER}"')
                if typ == 'OK' and data and data[0]:
                    uids_unseen = [int(x) for x in data[0].split()]
                    uids_unseen = sorted(uids_unseen, reverse=True)
                    print(f"[IMAP] UNSEEN from {KNOWN_SENDER}: {uids_unseen[:10]}")
                else:
                    uids_unseen = []
            except Exception as e:
                print("[IMAP] Error buscando UNSEEN FROM KNOWN_SENDER:", e)
                uids_unseen = []

            for uid in uids_unseen:
                if since_uid and uid <= since_uid:
                    continue
                try:
                    print(f"[IMAP] Revisando UID {uid} (UNSEEN remitente) ...")
                    subject, body = uid_fetch_text(M, uid)
                    print(f"[IMAP]  Subject: {subject!r}")
                    snippet = (body or "")[:800].replace("\n", " ").replace("\r", " ")
                    print(f"[IMAP]  Body snippet: {snippet!s}")
                    otp = extract_otp_from_text(subject, body)
                    if otp:
                        print(f"[IMAP]  >>> OTP EXTRAÍDO: {otp} (uid {uid})")
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return otp, uid
                except Exception as e:
                    print(f"[IMAP] Error procesando UID {uid} unseen remitente: {e}")
                    continue

            # Fallback UNSEEN generic
            try:
                typ, data = imap_search_utf8(M, 'UNSEEN')
                if typ == 'OK' and data and data[0]:
                    uids_generic = [int(x) for x in data[0].split()]
                    uids_generic = sorted(uids_generic, reverse=True)
                    print(f"[IMAP] UNSEEN generic: {uids_generic[:10]}")
                else:
                    uids_generic = []
            except Exception as e:
                print("[IMAP] Error buscando UNSEEN generic:", e)
                uids_generic = []

            for uid in uids_generic:
                if since_uid and uid <= since_uid:
                    continue
                try:
                    print(f"[IMAP] Revisando UID {uid} (generic unseen) ...")
                    subject, body = uid_fetch_text(M, uid)
                    print(f"[IMAP]  Subject: {subject!r}")
                    snippet = (body or "")[:800].replace("\n", " ").replace("\r", " ")
                    print(f"[IMAP]  Body snippet: {snippet!s}")
                    otp = extract_otp_from_text(subject, body)
                    if otp:
                        print(f"[IMAP]  >>> OTP EXTRAÍDO (generic): {otp} (uid {uid})")
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return otp, uid
                except Exception as e:
                    print(f"[IMAP] Error procesando UID {uid} generic: {e}")
                    continue

            print(f"[IMAP] Ningún OTP encontrado en esta ronda. Esperando {poll_every}s antes de reintentar...")
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

# ---------------------------
# Mejorada: get_latest_transfer_code_gmail con SUBJECT-check estricto + body-format fallback
# ---------------------------
def get_latest_transfer_code_gmail(user: str, pwd: str, subject_search: str = "Envío de código", timeout_sec: int = 180, poll_every: float = 3.0) -> Tuple[str, int]:
    """
    Busca correos cuyo SUBJECT contenga subject_search y/o cuerpos que contengan
    la frase de transferencia en el formato exacto:
      "Se envía el código para confirmar la transferencia:NNNNNN"
    Comportamiento:
      1) Primero exige mails cuyo SUBJECT contenga subject_search. Si hay, procesa
         esos mensajes (del más reciente al más antiguo) y extrae el código.
      2) Si NO hay mensajes con SUBJECT que contenga subject_search, entonces
         revisa los últimos mensajes del mailbox buscando en el cuerpo la frase
         exacta (TRANSFER_CODE_RE). Devuelve el código del ÚLTIMO mensaje
         recibido que cumpla (es decir, el de mayor UID).
      3) Si nada, espera poll_every y reintenta hasta agotar timeout_sec.
    """
    start = time.time()
    M = None
    generic_digits_re = re.compile(r"\b(\d{4,8})\b")
    try:
        M = imap_connect(GMAIL_IMAP_HOST, user, pwd)
        attempt = 0
        while time.time() - start < timeout_sec:
            attempt += 1
            elapsed = int(time.time() - start)
            print(f"[IMAP][TRANSFER] Poll #{attempt} (elapsed {elapsed}s) buscando SUBJECT '{subject_search}' / cuerpo ...")

            # 1) Estrategia estricta: buscar mails cuyo SUBJECT contenga subject_search
            try:
                # Intento de búsqueda por SUBJECT (CHARSET si necesario)
                typ, data = imap_search_utf8(M, 'SUBJECT', f'"{subject_search}"')
                if typ == 'OK' and data and data[0]:
                    uids = [int(x) for x in data[0].split()]
                    uids = sorted(uids, reverse=True)  # revisar del más reciente al más antiguo
                    print(f"[IMAP][TRANSFER] Encontrados UIDs con SUBJECT que contiene '{subject_search}': {uids[:10]}")
                else:
                    uids = []
            except Exception as e:
                print("[IMAP][TRANSFER] Error buscando SUBJECT directo:", e)
                uids = []

            if uids:
                # Procesar los UIDs que sí tienen el SUBJECT requerido
                for uid in uids:
                    try:
                        subj, body = uid_fetch_text(M, uid)
                        print(f"[IMAP][TRANSFER] Revisando UID {uid} SUBJECT: {subj!r}")
                        code = extract_transfer_code_from_text(subj, body)
                        if not code:
                            # fallback: buscar cualquier dígito en asunto o cuerpo (pero sólo dentro de mails con el SUBJECT correcto)
                            m2 = generic_digits_re.search(body or "") or generic_digits_re.search(subj or "")
                            if m2:
                                code = m2.group(1)
                        if code:
                            print(f"[IMAP][TRANSFER] >>> Código EXTRAÍDO: {code} (uid {uid})")
                            try:
                                M.logout()
                            except Exception:
                                pass
                            return code, uid
                        else:
                            print(f"[IMAP][TRANSFER] UID {uid} con SUBJECT correcto no contiene código según regex; sigo con otros UIDs con ese SUBJECT.")
                    except Exception as e:
                        print(f"[IMAP][TRANSFER] Error procesando UID {uid}: {e}")
                        continue

                # si ninguno de los mensajes con SUBJECT correcto dió código, esperar y reintentar
                print(f"[IMAP][TRANSFER] Mensajes con SUBJECT '{subject_search}' encontrados pero ninguno contenía el código. Esperando {poll_every}s antes de reintentar...")
                time.sleep(poll_every)
                try:
                    M.select("INBOX")
                except Exception:
                    pass
                continue

            # 2) Si no hay mails con el SUBJECT esperado, hacer fallback buscando la frase exacta en el cuerpo
            print(f"[IMAP][TRANSFER] No hay mails con asunto que contenga '{subject_search}'. Buscando en cuerpo la frase exacta 'Se envía el código para confirmar la transferencia:...' en los últimos mensajes.")
            try:
                typ_all, data_all = M.uid('SEARCH', None, 'ALL')
                if typ_all == 'OK' and data_all and data_all[0]:
                    all_uids = [int(x) for x in data_all[0].split()]
                    # revisar los últimos N (p.ej. 200) mensajes del mailbox del más reciente al más antiguo
                    check_uids = sorted(all_uids[-200:], reverse=True)
                else:
                    check_uids = []
            except Exception as e:
                print("[IMAP][TRANSFER] Error listando ALL para fallback por cuerpo:", e)
                check_uids = []

            found_code = None
            found_uid = None
            for uid in check_uids:
                try:
                    subj, body = uid_fetch_text(M, uid)
                    snippet = (body or "")[:300].replace("\n", " ")
                    print(f"[IMAP][TRANSFER] Revisando UID {uid} (fallback cuerpo) snippet={snippet!r}")
                    # Buscar frase exacta en el body (TRANSER_CODE_RE)
                    m = TRANSFER_CODE_RE.search(body or "")
                    if m:
                        found_code = m.group(1)
                        found_uid = uid
                        print(f"[IMAP][TRANSFER] >>> Código EXTRAÍDO por frase en cuerpo: {found_code} (uid {uid})")
                        break  # como estamos iterando del más reciente al más antiguo, este es el último recibido que cumple
                except Exception as e:
                    print(f"[IMAP][TRANSFER] Error procesando UID {uid} en fallback cuerpo: {e}")
                    continue

            if found_code:
                try:
                    M.logout()
                except Exception:
                    pass
                return found_code, found_uid

            # 3) Si no encontramos aún, esperar y reintentar
            print(f"[IMAP][TRANSFER] No encontrado aún en cuerpo; esperando {poll_every}s antes de reintentar...")
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
            print(f"[SELENIUM][OTP] Encontrado campo OTP por ID en contexto actual: #{OTP_FIELD_ID}")
            return el
        else:
            print(f"[SELENIUM][OTP] Elemento por ID presente pero no visible: {OTP_FIELD_ID}")
    except Exception:
        print(f"[SELENIUM][OTP] No se encontró elemento por ID {OTP_FIELD_ID} en contexto actual.")

    try:
        el = driver.find_element(By.NAME, OTP_FIELD_NAME)
        if el and el.is_displayed():
            print(f"[SELENIUM][OTP] Encontrado campo OTP por NAME en contexto actual: {OTP_FIELD_NAME}")
            return el
    except Exception:
        print(f"[SELENIUM][OTP] No se encontró elemento por NAME {OTP_FIELD_NAME} en contexto actual.")

    # probar iframes (simple scan)
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"[SELENIUM][OTP] iframes found: {len(iframes)}")
        for i, fr in enumerate(iframes, start=1):
            try:
                driver.switch_to.frame(fr)
                try:
                    el = driver.find_element(By.ID, OTP_FIELD_ID)
                    if el and el.is_displayed():
                        print(f"[SELENIUM][OTP] Encontrado campo OTP por ID dentro iframe #{i}")
                        return el
                except Exception:
                    pass
                try:
                    el = driver.find_element(By.NAME, OTP_FIELD_NAME)
                    if el and el.is_displayed():
                        print(f"[SELENIUM][OTP] Encontrado campo OTP por NAME dentro iframe #{i}")
                        return el
                except Exception:
                    pass
                cand = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='tel'], input[inputmode='numeric'], input[type='number']")
                for el in cand:
                    try:
                        if el.is_displayed():
                            print(f"[SELENIUM][OTP] Candidato visible en iframe #{i}: {(el.get_attribute('outerHTML') or '')[:200]}")
                            return el
                    except Exception:
                        continue
                driver.switch_to.default_content()
            except Exception as e:
                print(f"[SELENIUM][OTP] Error en iframe #{i}: {e}")
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
    except Exception as e:
        print("[SELENIUM][OTP] Error buscando iframes:", e)

    # heurística JS fallback
    print("[SELENIUM][OTP] Heurística JS (fallback) ...")
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
        if(!(el.getAttribute('value'))) s += 1;
        const rect = el.getBoundingClientRect();
        if(rect.width > 0 && rect.height > 0) s += 2;
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
                typ = (el.get_attribute("type") or "").lower()
                name = (el.get_attribute("name") or "").lower()
                if typ == "hidden" or "csrf" in name:
                    print("[SELENIUM][OTP] JS devolvió hidden/csrf; ignoro.")
                elif not el.is_displayed():
                    print("[SELENIUM][OTP] JS devolvió elemento no visible; ignoro.")
                else:
                    print("[SELENIUM][OTP] JS heurística devolvió elemento visible.")
                    return el
            except Exception as e:
                print("[SELENIUM][OTP] Error validando elemento devuelto por JS:", e)
    except Exception as e:
        print("[SELENIUM][OTP] Error ejecutando JS heurística:", e)

    # último recurso: listar inputs y pedir selector manual
    print("[SELENIUM][OTP] Fallback: listando inputs (primeros 80) con atributos...")
    inputs = driver.find_elements(By.TAG_NAME, "input")
    for i, el in enumerate(inputs[:80], start=1):
        try:
            attr = {
                "index": i,
                "id": el.get_attribute("id"),
                "name": el.get_attribute("name"),
                "placeholder": el.get_attribute("placeholder"),
                "type": el.get_attribute("type"),
                "maxlength": el.get_attribute("maxlength"),
                "outerHTML": (el.get_attribute("outerHTML") or "")[:350]
            }
            print(f"[INPUT #{i}] {attr}")
        except Exception as e:
            print(f"[SELENIUM][OTP] Error leyendo input #{i} attrs: {e}")

    sel_manual = input("[SELENIUM][OTP] Pegá aquí el selector CSS o XPATH del input OTP (o ENTER para abortar): ").strip()
    if not sel_manual:
        raise TimeoutException("Usuario no proveyó selector OTP manualmente")
    try:
        if sel_manual.startswith("/") or sel_manual.startswith("(") or sel_manual.startswith("//"):
            return driver.find_element(By.XPATH, sel_manual)
        else:
            return driver.find_element(By.CSS_SELECTOR, sel_manual)
    except Exception as e:
        print("[SELENIUM][OTP] Selector manual falló:", e)
        raise

# ---------------------------
# BÚSQUEDA RECURSIVA EN IFRAMES + SHADOW DOM
# ---------------------------
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
                    print(f"[FRAMES][SEARCH] Encontrado en depth {depth} en contexto actual.")
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
            except Exception as e:
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(i)
                except Exception as e2:
                    print(f"[FRAMES][SEARCH] No pude switch a iframe #{i}: {e2}")
                    driver.switch_to.default_content()
                    continue

            found = _recursive_search_frames(driver, finder, depth + 1, max_depth)
            if found:
                return found
            try:
                driver.switch_to.parent_frame()
            except Exception:
                driver.switch_to.default_content()
        except Exception as e:
            print(f"[FRAMES][SEARCH] Error iterando iframe #{i}: {e}")
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
            print("[LOCATE] Error en recursive iframe search:", e)

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

    if last_exc:
        print("[LOCATE] Última excepción durante locate:", last_exc)
    return None

def safe_click_element(driver: webdriver.Chrome, el: webdriver.remote.webelement.WebElement) -> bool:
    try:
        el.click()
        print("[CLICK] Click normal OK")
        return True
    except Exception as e:
        print("[CLICK] Click normal falló:", e)
    try:
        driver.execute_script("arguments[0].scrollIntoView(true);", el)
        driver.execute_script("arguments[0].click();", el)
        print("[CLICK] Click via JS OK")
        return True
    except Exception as e:
        print("[CLICK] Click JS falló:", e)
    try:
        onclick = el.get_attribute("onclick")
        if onclick:
            print("[CLICK] Ejecutando onclick manualmente:", (onclick or "")[:300])
            driver.execute_script(onclick)
            return True
    except Exception as e:
        print("[CLICK] Ejecutar onclick falló:", e)
    return False

# ---------------------------
# Helpers específicos: buscar primer input numérico/importe y setear valor
# ---------------------------
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
                            print(f"[FIND_NUM] Encontrado input candidate por {typ}={sel}")
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
                            print(f"[FIND_NUM] Seleccionado input por heurística name/id: id={idv} name={name} placeholder={ph}")
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
        print(f"[SET_INPUT] Send keys to element -> {value}")
    except Exception as e:
        print("[SET_INPUT] send_keys falló:", e)
        try:
            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));", el, value)
            print("[SET_INPUT] Valor seteado via JS fallback.")
        except Exception as e2:
            print("[SET_INPUT] Fallback JS falló:", e2)

# ---------------------------
# Funcion para abrir select2 y elegir la opción "Varios" o la última
# ---------------------------
def select_select2_option_choose_varios_or_last(driver: webdriver.Chrome, combo_css: str, timeout: float = 10.0) -> bool:
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    combo = locate_element_across_frames(driver, By.CSS_SELECTOR, combo_css, timeout=8)
    if not combo:
        print("[SELECT2] No se encontró el combobox select2 con css:", combo_css)
        return False

    print("[SELECT2] Combobox localizado. Abriendo dropdown...")
    if not safe_click_element(driver, combo):
        print("[SELECT2] No se pudo abrir combobox con click.")
        return False

    time.sleep(1.0)

    options = []
    try:
        options = driver.execute_script("return Array.from(document.querySelectorAll('li.select2-results__option'));")
        if not options:
            options = driver.execute_script("return Array.from(document.querySelectorAll('ul.select2-results__options li'));")
    except Exception as e:
        print("[SELECT2] Error ejecutando script para obtener opciones:", e)
        options = []

    if not options:
        try:
            opts = driver.find_elements(By.CSS_SELECTOR, "li.select2-results__option")
            options = opts
        except Exception:
            options = []

    if not options:
        print("[SELECT2] No encontré opciones select2. Intentaré buscar 'option' dentro de selects nativos.")
        try:
            native_opts = driver.find_elements(By.TAG_NAME, "option")
            if native_opts:
                for o in native_opts[::-1]:
                    try:
                        txt = (o.text or "").strip()
                        if txt and "varios" in txt.lower():
                            safe_click_element(driver, o)
                            print("[SELECT2] Seleccionada opción 'Varios' (native select).")
                            return True
                    except Exception:
                        continue
                try:
                    safe_click_element(driver, native_opts[-1])
                    print("[SELECT2] Seleccionada última opción (native select).")
                    return True
                except Exception:
                    pass
        except Exception:
            pass

        print("[SELECT2] No pude obtener opciones del select2.")
        return False

    opts_list = options if isinstance(options, list) else list(options)
    chosen = None
    for opt in opts_list:
        try:
            text = (opt.text or "").strip()
            if text and "varios" in text.lower():
                chosen = opt
                print("[SELECT2] Encontrada opción que contiene 'Varios':", text)
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
        print("[SELECT2] No se encontró opción para seleccionar.")
        return False

    try:
        safe_click_element(driver, chosen)
        print("[SELECT2] Click en opción seleccionada realizado.")
        return True
    except Exception as e:
        print("[SELECT2] Error al clickear la opción seleccionada:", e)
        try:
            driver.execute_script("arguments[0].click();", chosen)
            print("[SELECT2] Click via JS realizado.")
            return True
        except Exception as e2:
            print("[SELECT2] Click via JS falló:", e2)
            return False

# ---------------------------
# Click Aceptar / Confirm helpers (iguales que antes)
# ---------------------------
def click_accept_button(driver: webdriver.Chrome, wait: WebDriverWait, timeout: float = 15.0):
    print(f"[SELENIUM][ACCEPT] Buscando botón Aceptar id={ACCEPT_BTN_ID} (timeout {timeout}s) ...")
    try:
        el = locate_element_across_frames(driver, By.ID, ACCEPT_BTN_ID, timeout=timeout)
        if el:
            print("[SELENIUM][ACCEPT] Botón Aceptar localizado por ID.")
            ok = safe_click_element(driver, el)
            driver.switch_to.default_content()
            return ok

        el = locate_element_across_frames(driver, By.CSS_SELECTOR, f"#{ACCEPT_BTN_ID}", timeout=6)
        if el:
            print("[SELENIUM][ACCEPT] Botón Aceptar localizado por CSS fallback.")
            ok = safe_click_element(driver, el)
            driver.switch_to.default_content()
            return ok

        print("[SELENIUM][ACCEPT] Intentando fallback por texto 'Aceptar' / 'Confirmar' ...")
        el = locate_element_across_frames(driver, By.XPATH, "//a[contains(., 'Aceptar') or contains(., 'Confirmar') or contains(., 'Verificar') or contains(., 'Enviar')]", timeout=6)
        if el:
            print("[SELENIUM][ACCEPT] Botón Aceptar localizado por texto heurístico.")
            ok = safe_click_element(driver, el)
            driver.switch_to.default_content()
            return ok

        print("[SELENIUM][ACCEPT] No se encontró el botón Aceptar; retornando False.")
        return False
    except Exception as e:
        print("[SELENIUM][ACCEPT] Error buscando/accionando aceptar:", e)
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False

def click_confirm_button(driver: webdriver.Chrome, wait: WebDriverWait, timeout: float = 15.0):
    print(f"[SELENIUM][CONFIRM] Buscando botón Confirmar id={CONFIRM_BTN_ID} (timeout {timeout}s) ...")
    try:
        el = locate_element_across_frames(driver, By.ID, CONFIRM_BTN_ID, timeout=timeout)
        if el:
            print("[SELENIUM][CONFIRM] Botón Confirmar localizado por ID.")
            ok = safe_click_element(driver, el)
            driver.switch_to.default_content()
            return ok

        el = locate_element_across_frames(driver, By.CSS_SELECTOR, f"#{CONFIRM_BTN_ID}", timeout=6)
        if el:
            print("[SELENIUM][CONFIRM] Botón Confirmar localizado por CSS fallback.")
            ok = safe_click_element(driver, el)
            driver.switch_to.default_content()
            return ok

        print("[SELENIUM][CONFIRM] Intentando heurística por texto/título 'Confirmar' / 'Aceptar' ...")
        el = locate_element_across_frames(driver, By.XPATH, "//a[contains(@title,'Confirmar') or contains(., 'Aceptar') or contains(., 'Confirmar')]", timeout=6)
        if el:
            print("[SELENIUM][CONFIRM] Botón Confirmar localizado por texto heurístico.")
            ok = safe_click_element(driver, el)
            driver.switch_to.default_content()
            return ok

        print("[SELENIUM][CONFIRM] No se encontró el botón Confirmar; retornando False.")
        return False
    except Exception as e:
        print("[SELENIUM][CONFIRM] Error buscando/accionando confirmar:", e)
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False

# ---------------------------
# Opción B (secuencia principal)
# ---------------------------
def opcion_b_selenium():
    print("== Opción B: Selenium + Chrome WebDriver con OTP Gmail IMAP (DEBUG) ==")
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    # options.add_argument("--headless=new")  # si quieres headless, descomenta
    try:
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    except Exception as e:
        print("[SELENIUM] Error iniciando Chrome WebDriver:", e)
        raise

    try:
        print("[SELENIUM] Navegando a:", URL_B)
        driver.get(URL_B)
        wait = WebDriverWait(driver, 30)

        # Usuario
        print("[SELENIUM] Esperando campo usuario (id=%s)..." % FIELD_LOGIN_ID)
        user_input = wait.until(EC.presence_of_element_located((By.ID, FIELD_LOGIN_ID)))
        user_input.clear()
        user_input.send_keys(USER_B)
        print("[SELENIUM] Usuario escrito:", USER_B)

        # Password
        print("[SELENIUM] Esperando campo password (id=%s)..." % FIELD_PASS_ID)
        pass_input = wait.until(EC.presence_of_element_located((By.ID, FIELD_PASS_ID)))
        pass_input.clear()
        pass_input.send_keys(PASS_B)
        print("[SELENIUM] Password enviado (oculto)")

        # Click Ingresar
        print("[SELENIUM] Buscando botón Ingresar...")
        login_btn = None
        for by_name, sel in [("CSS_SELECTOR", LOGIN_BTN_CSS), ("XPATH", "//input[@class='button' and @value='Ingresar']"), ("XPATH", "//button[contains(., 'Ingresar')]")]:
            try:
                login_btn = wait.until(EC.element_to_be_clickable((getattr(By, by_name), sel)))
                print(f"[SELENIUM] Botón Ingresar matched: {by_name} -> {sel}")
                break
            except Exception as e:
                print(f"[SELENIUM] Botón Ingresar no match: {by_name} -> {sel} ; err: {e}")
        if not login_btn:
            raise RuntimeError("No se encontró botón Ingresar.")
        login_btn.click()
        print("[SELENIUM] Click Ingresar realizado.")

        # Esperar 2FA
        print("[SELENIUM] Esperando redirección a app_control_2fa ...")
        try:
            wait.until(EC.url_contains("app_control_2fa"))
            print("[SELENIUM] Detectada URL 2FA por url_contains")
        except TimeoutException:
            print("[SELENIUM] No se detectó cambio de URL a app_control_2fa con timeout, continúo")

        print("[SELENIUM] URL actual:", driver.current_url)
        print("[SELENIUM] Título:", driver.title)

        # Buscar campo OTP
        print("[SELENIUM] Buscando campo OTP (priorizando id/name que indicaste)...")
        otp_input = find_otp_input_and_debug(driver, wait)
        print("[SELENIUM] Campo OTP localizado (outerHTML recorte):", (otp_input.get_attribute("outerHTML") or "")[:400])

        # Preparar baseline UID para IMAP
        since_uid = None
        if GMAIL_USER and GMAIL_PASS:
            try:
                Mtmp = imap_connect(GMAIL_IMAP_HOST, GMAIL_USER, GMAIL_PASS)
                all_uids = uid_search_all(Mtmp, "ALL")
                since_uid = max(all_uids) if all_uids else 0
                print("[SELENIUM] UID baseline (último UID actual en INBOX):", since_uid)
                try:
                    Mtmp.logout()
                except Exception:
                    pass
            except Exception as e:
                print("[SELENIUM][IMAP] No se pudo obtener baseline UID:", e)
        else:
            print("[SELENIUM] GMAIL_USER/GMAIL_PASS no configuradas. Se pedirá OTP manual si no llega.")

        # Poll IMAP para OTP
        otp_code = ""
        try:
            if GMAIL_USER and GMAIL_PASS:
                print("[SELENIUM] Iniciando polling IMAP en busca del OTP (timeout 120s)...")
                otp_code, got_uid = get_latest_otp_gmail(user=GMAIL_USER, pwd=GMAIL_PASS, timeout_sec=120, poll_every=2.0, since_uid=since_uid)
                print(f"[SELENIUM] OTP recibido por IMAP: {otp_code} (uid {got_uid})")
            else:
                raise RuntimeError("No GMAIL credentials")
        except Exception as e:
            print("[SELENIUM][OTP] Error/Timeout leyendo Gmail:", e)
            otp_code = input("[SELENIUM] Ingresá manualmente el OTP (si lo tenés): ").strip()

        # Pegar OTP en el campo detectado
        print("[SELENIUM] Pegando OTP en campo:", otp_code)
        try:
            otp_input.clear()
            otp_input.send_keys(otp_code)
            print("[SELENIUM] OTP pegado en el campo.")
        except Exception as e:
            print("[SELENIUM] Error pegando OTP en el campo detectado:", e)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            otp_input = find_otp_input_and_debug(driver, wait)
            otp_input.clear()
            otp_input.send_keys(otp_code)
            print("[SELENIUM] OTP pegado en reintento.")

        # Buscar botón validar/confirmar y click (si existe)
        print("[SELENIUM] Buscando botón validar/confirmar...")
        validate_btn = None
        for by_name, sel in [
            ("XPATH", "//input[@type='button' and (contains(@value,'Validar') or contains(@value,'Confirmar') or contains(@value,'Verificar') or contains(@value,'Enviar'))]"),
            ("XPATH", "//button[contains(., 'Validar') or contains(., 'Confirmar') or contains(., 'Verificar') or contains(., 'Enviar')]"),
            ("CSS_SELECTOR", "input.button[onclick*='nm_atualiza']"),
        ]:
            try:
                validate_btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((getattr(By, by_name), sel)))
                print(f"[SELENIUM] Botón validar matched: {by_name} -> {sel}")
                break
            except Exception as e:
                print(f"[SELENIUM] Botón validar no match: {by_name} -> {sel} ; err: {e}")
                validate_btn = None

        if validate_btn:
            try:
                validate_btn.click()
                print("[SELENIUM] Click en validar realizado.")
            except Exception as e:
                print("[SELENIUM] Click validar falló, intentando JS:", e)
                try:
                    driver.execute_script("arguments[0].click();", validate_btn)
                    print("[SELENIUM] Click validar por JS realizado.")
                except Exception as e2:
                    print("[SELENIUM] Click validar por JS falló:", e2)
        else:
            print("[SELENIUM] No se encontró botón validar; pasamos a intentar Aceptar directo")

        # Click en Aceptar (sc_submit_ajax_bot) -- búsqueda en iframes/modal
        ok_accept = click_accept_button(driver, wait, timeout=20)
        if ok_accept:
            print("[SELENIUM] Botón Aceptar clickeado correctamente.")
        else:
            print("[SELENIUM] FALLÓ click en Aceptar. Intentá manualmente.")

        # Esperar un pequeño lapso para que la UI se actualice
        time.sleep(1.0)

        # Click en Confirmar final (sub_form_b)
        ok_confirm = click_confirm_button(driver, wait, timeout=12)
        if ok_confirm:
            print("[SELENIUM] Botón Confirmar (sub_form_b) clickeado correctamente.")
            # --> PAUSA SOLICITADA DE 3 SEGUNDOS
            print("[SELENIUM] Pausando 3 segundos tras presionar el último botón (Confirmar)...")
            time.sleep(3)
            print("[SELENIUM] Pausa de 3s finalizada. Ahora navegando a:", TRANSFER_URL)

            # Navegar directamente a la URL indicada
            try:
                driver.get(TRANSFER_URL)
                print("[SELENIUM] Navegando a TRANSFER_URL:", TRANSFER_URL)
                # esperar breve carga
                time.sleep(3)
                print("[SELENIUM] Espera de 3s en TRANSFER_URL finalizada.")
            except Exception as e:
                print("[SELENIUM] Error navegando a TRANSFER_URL:", e)

            # --- PARTE 1: buscar campo cuenta, pegar valor y presionar "Próximo" ---
            try:
                print(f"[SELENIUM][TRANSFER] Buscando campo cuenta id={CUENTA_FIELD_ID} ...")
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
                        cuenta_el.send_keys(CUENTA_TO_PASTE)
                        print(f"[SELENIUM][TRANSFER] Valor pegado en campo cuenta: {CUENTA_TO_PASTE}")
                    except Exception as e:
                        print("[SELENIUM][TRANSFER] Error enviando keys al campo cuenta:", e)
                        try:
                            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));", cuenta_el, CUENTA_TO_PASTE)
                            print("[SELENIUM][TRANSFER] Valor seteado via JS fallback.")
                        except Exception as e2:
                            print("[SELENIUM][TRANSFER] Fallback JS para setear campo falló:", e2)
                else:
                    print("[SELENIUM][TRANSFER] No se encontró el input de cuenta (id=id_sc_field_cuenta).")

                # buscar y clickear botón Próximo (primer click)
                print(f"[SELENIUM][TRANSFER] Buscando botón 'Próximo' id={PRIMERO_BTN_ID} ... (primer click)")
                prox_el = locate_element_across_frames(driver, By.ID, PRIMERO_BTN_ID, timeout=12)
                if prox_el:
                    okp = safe_click_element(driver, prox_el)
                    if okp:
                        print("[SELENIUM][TRANSFER] Primer click en 'Próximo' realizado correctamente.")
                    else:
                        print("[SELENIUM][TRANSFER] Falló click en 'Próximo' (primer intento).")
                else:
                    print("[SELENIUM][TRANSFER] No se encontró botón 'Próximo' (primer intento).")

                # esperar 5 segundos (tal como pediste originalmente)
                print("[SELENIUM][TRANSFER] Esperando 5 segundos después del primer 'Próximo'...")
                time.sleep(5)
                print("[SELENIUM][TRANSFER] Espera de 5s finalizada.")

                # --- NUEVOS PASOS REQUERIDOS AHORA ---
                # esperar 2 segundos y presionar nuevamente "Próximo"
                print("[SELENIUM][TRANSFER] Esperando 2 segundos antes del segundo 'Próximo'...")
                time.sleep(2)
                print("[SELENIUM][TRANSFER] Intentando segundo click en 'Próximo' (id=%s)..." % PRIMERO_BTN_ID)
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
                prox_el2 = locate_element_across_frames(driver, By.ID, PRIMERO_BTN_ID, timeout=10)
                if prox_el2:
                    okp2 = safe_click_element(driver, prox_el2)
                    if okp2:
                        print("[SELENIUM][TRANSFER] Segundo click en 'Próximo' realizado correctamente.")
                    else:
                        print("[SELENIUM][TRANSFER] Segundo click en 'Próximo' falló.")
                else:
                    print("[SELENIUM][TRANSFER] No se encontró botón 'Próximo' (segundo intento).")

                # esperar 2 segundos
                print("[SELENIUM][TRANSFER] Esperando 2 segundos antes de pegar monto...")
                time.sleep(2)

                # buscar input numérico/importe y pegar 10000
                print("[SELENIUM][TRANSFER] Buscando un input numérico/importe para pegar '10000' ...")
                amount_input = find_first_numeric_input(driver, timeout=12)
                if amount_input:
                    set_input_value(driver, amount_input, "1000000")
                    print("[SELENIUM][TRANSFER] Pegado '1000000' en el input encontrado.")
                else:
                    print("[SELENIUM][TRANSFER] No se encontró input numérico razonable para pegar '10000'.")

                # Ahora abrir el select2 y elegir "Varios" o la última opción
                print("[SELENIUM][TRANSFER] Intentando abrir select2 y elegir 'Varios' / última opción...")
                ok_select2 = select_select2_option_choose_varios_or_last(driver, SELECT2_COMBO_CSS, timeout=12)
                if ok_select2:
                    print("[SELENIUM][TRANSFER] Select2: opción seleccionada correctamente.")
                else:
                    print("[SELENIUM][TRANSFER] Select2: no se pudo seleccionar opción.")

                # Finalmente, presionar "Próximo" otra vez y esperar 3 segundos
                print("[SELENIUM][TRANSFER] Buscando botón 'Próximo' para último click...")
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
                prox_el3 = locate_element_across_frames(driver, By.ID, PRIMERO_BTN_ID, timeout=12)
                if prox_el3:
                    okp3 = safe_click_element(driver, prox_el3)
                    if okp3:
                        print("[SELENIUM][TRANSFER] Último click en 'Próximo' realizado correctamente. Esperando 3s...")
                        time.sleep(3)
                        print("[SELENIUM][TRANSFER] Espera post-último 'Próximo' (3s) finalizada.")
                    else:
                        print("[SELENIUM][TRANSFER] Falló último click en 'Próximo'.")
                else:
                    print("[SELENIUM][TRANSFER] No se encontró botón 'Próximo' para el último click.")
            except Exception as e:
                print("[SELENIUM][TRANSFER] Error en la secuencia de cuenta/Próximo:", e)
        else:
            print("[SELENIUM] FALLÓ click en Confirmar (sub_form_b). Intentá manualmente o chequeá selectores.")

        # --- AHORA: volver al mail para leer el código de confirmación de la transferencia ---
        print("[SELENIUM][TRANSFER] Ahora se intentará leer el mail de confirmación de transferencia (subject 'Envío de código') ...")
        transfer_code = ""
        try:
            if GMAIL_USER and GMAIL_PASS:
                print("[IMAP][TRANSFER] Iniciando polling para mail de confirmación (timeout 180s)...")
                transfer_code, t_uid = get_latest_transfer_code_gmail(user=GMAIL_USER, pwd=GMAIL_PASS, subject_search="Envío de código", timeout_sec=180, poll_every=3.0)
                print(f"[IMAP][TRANSFER] Código recibido: {transfer_code} (uid {t_uid})")
            else:
                raise RuntimeError("No GMAIL credentials")
        except Exception as e:
            print("[IMAP][TRANSFER] Error/Timeout leyendo Gmail para código de transferencia:", e)
            transfer_code = input("[SELENIUM] Ingresá manualmente el código de transferencia (si lo tenés): ").strip()

        # Pegar código en input token_cliente
        print("[SELENIUM][TRANSFER] Pegando código en campo token_cliente:", transfer_code)
        try:
            token_el = locate_element_across_frames(driver, By.ID, TOKEN_FIELD_ID, timeout=20)
            if token_el:
                # -- AÑADIDO: click en input para enfocarlo, esperar 1s, luego pegar el código --
                try:
                    try:
                        token_el.click()
                        print("[SELENIUM][TRANSFER] Click en input token_cliente para enfocar.")
                    except Exception:
                        # fallback a safe click si .click() falla
                        safe_click_element(driver, token_el)
                        print("[SELENIUM][TRANSFER] Click (fallback) en input token_cliente realizado.")
                    # esperar 1 segundo antes de pegar
                    time.sleep(1)
                except Exception as e:
                    print("[SELENIUM][TRANSFER] No pudo hacerse click/focus en token_cliente:", e)

                # ahora pegar el código
                set_input_value(driver, token_el, transfer_code)
                print("[SELENIUM][TRANSFER] Código pegado en token_cliente.")
                # esperar 3 segundos ANTES de presionar Confirmar
                print("[SELENIUM][TRANSFER] Esperando 3 segundos antes de presionar Confirmar...")
                time.sleep(3)
            else:
                print("[SELENIUM][TRANSFER] No se encontró input token_cliente (id=%s)." % TOKEN_FIELD_ID)
        except Exception as e:
            print("[SELENIUM][TRANSFER] Error seteando token_cliente:", e)

        # Presionar Confirmar (sc_confirmar_bot)
        print("[SELENIUM][TRANSFER] Buscando botón Confirmar final id=%s ..." % TOKEN_CONFIRM_BTN_ID)
        try:
            conf_btn = locate_element_across_frames(driver, By.ID, TOKEN_CONFIRM_BTN_ID, timeout=15)
            if conf_btn:
                ok_conf = safe_click_element(driver, conf_btn)
                if ok_conf:
                    print("[SELENIUM][TRANSFER] Botón Confirmar final clickeado correctamente. Esperando 10s...")
                    time.sleep(10)
                    print("[SELENIUM][TRANSFER] Espera 10s finalizada.")
                else:
                    print("[SELENIUM][TRANSFER] Falló click en botón Confirmar final.")
            else:
                print("[SELENIUM][TRANSFER] No se encontró botón Confirmar final (id=%s)." % TOKEN_CONFIRM_BTN_ID)
        except Exception as e:
            print("[SELENIUM][TRANSFER] Error buscando/accionando Confirmar final:", e)

        # Esperar resultado post-2FA y post-transfer
        print("[SELENIUM] Esperando resultado final ... (breve check)")
        try:
            wait.until(lambda d: "app_control_2fa" not in d.current_url)
            print("[SELENIUM] Salida de 2FA detectada por URL")
        except TimeoutException:
            print("[SELENIUM] Timeout esperando salir de 2FA; continuamos")

        print("[SELENIUM] URL final:", driver.current_url)
        print("[SELENIUM] Título final:", driver.title)
        print("[SELENIUM] HTML final (snippet):\n", (driver.page_source or "")[:1200])

    finally:
        print("[SELENIUM] Cerrando navegador...")
        try:
            driver.quit()
        except Exception:
            pass

# ---------------------------
# MAIN (solo opción B)
# ---------------------------
def main():
    print("Ejecutando solamente la Opción B (Selenium + Chrome) ...")
    if not GMAIL_USER or not GMAIL_PASS:
        print("⚠️  GMAIL_USER/GMAIL_PASS no configuradas en el entorno. Se pedirá OTP / código manual si no llegaran.")
    opcion_b_selenium()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        try:
            sys.exit(1)
        except SystemExit:
            pass
