#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flask_server.py – Lanza “Bot Transferencias” (sin fechas) o “Bot CSV” (con
diálogo de fechas).  Las fechas elegidas se envían al bot CSV mediante
DATE_FROM / DATE_TO.  Incluye visor de logs, seguimiento de jobs y un
“mini-scan” de cuentas (SCAN_ONLY).
"""

import os, sys, uuid, time, subprocess, threading, json
from pathlib import Path
from threading import Thread
from flask import Flask, request, jsonify, render_template_string

APP = Flask(__name__)

LOGS_DIR = Path("run_logs"); LOGS_DIR.mkdir(exist_ok=True)
JOBS: dict[str, dict] = {}
FILE_HANDLES: dict[str, object] = {}

# ───────────────────────────────  HTML UI  ───────────────────────────────────
INDEX_HTML = """<!doctype html>
<html><head>
<meta charset="utf-8"/><title>Bot Runner</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1724;--card:#0b1220;--accent:#10b981;--muted:#9aa5b1;--pad:18px;}
body{font-family:Inter,Arial;background:#0e1b2a;color:#e6eef6;margin:0;padding:32px;}
.container{max-width:980px;margin:auto;}
.card{background:rgba(255,255,255,.03);padding:var(--pad);border-radius:12px;margin-top:18px;}
button{background:var(--accent);border:0;color:#052018;padding:10px 16px;border-radius:10px;
       font-weight:600;cursor:pointer}
button.secondary{background:transparent;color:var(--accent);
                 border:1px solid rgba(16,185,129,.18)}
button.danger{background:#dc2626;color:#fff;border:1px solid #dc2626}
button.danger:hover{background:#b91c1c}
pre{background:#071827;padding:12px;border-radius:8px;max-height:420px;
    overflow:auto;white-space:pre-wrap;color:#cfeef0}
.small{font-size:13px;color:#9aa5b1}
.job-pill{background:#08232a;padding:8px 10px;border-radius:999px;color:#9fd8cc;
          font-weight:600;margin:4px 4px 0 0}
dialog{border:0;border-radius:12px;background:#0b1220;color:#e6eef6;padding:24px}
label{font-size:13px;margin-right:6px}
input[type=number]{width:60px;padding:6px;border-radius:6px;border:1px solid #334155;
                   background:#0e1b2a;color:#e6eef6;margin-right:6px}
</style>
</head><body>
<div class="container">
  <h2>Bot Runner</h2>

  <div class="card">
    <b>Acciones</b><br/><br/>
    <button id="runTransferBtn">Bot Transferencias</button>
    <button id="runCsvBtn" class="secondary">Bot CSV</button>
    <button id="stopAllBtn" class="danger">STOP ALL</button>
    <div id="status" style="margin-top:10px" class="small">Estado: idle</div>
    <div id="jobs" style="margin-top:8px"></div>
  </div>

  <div class="card" id="logcard" style="display:none">
    <b>Log (tail)</b><pre id="log"></pre>
  </div>
</div>

<!-- diálogo fechas (solo para Bot CSV) -->
<dialog id="dateDlg">
  <form method="dialog">
    <h3>Seleccionar rango de fechas</h3>
    <div>
      <label>Cuenta:</label>
      <select id="accountSelect" disabled style="min-width:220px;padding:6px;border-radius:6px;border:1px solid #334155;background:#071827;color:#e6eef6">
        <option>Cargando cuentas...</option>
      </select>
    </div><br/>
    <div>
      <label>Desde:</label>
      <input id="d_d" type="number" min="1" max="31"  placeholder="DD" required>
      <input id="d_m" type="number" min="1" max="12"  placeholder="MM" required>
      <input id="d_y" type="number" min="2020" max="2100" placeholder="AAAA" required>
    </div><br/>
    <div>
      <label>Hasta:</label>
      <input id="h_d" type="number" min="1" max="31"  placeholder="DD" required>
      <input id="h_m" type="number" min="1" max="12"  placeholder="MM" required>
      <input id="h_y" type="number" min="2020" max="2100" placeholder="AAAA" required>
    </div><br/>
    <menu style="display:flex;gap:8px">
      <button id="dlgSaveBtn" disabled>Guardar</button>
      <button id="dlgCancelBtn" value="cancel" class="secondary">Cancelar</button>
    </menu>
  </form>
</dialog>

<script>
const st=document.getElementById('status');
const log=document.getElementById('log');
const logc=document.getElementById('logcard');
const jobsDiv=document.getElementById('jobs');
// Variables globales para almacenar cuentas individuales
window.cuenta1=undefined; window.cuenta2=undefined; window.cuenta3=undefined;
function accountsFromVars(){
  const out=[];
  const push=(c)=>{ if(!c) return; if(typeof c==='object'){ out.push({value:c.value||c.text||'', text:c.text||String(c)}); } else { out.push({value:String(c), text:String(c)}); } };
  push(window.cuenta1); push(window.cuenta2); push(window.cuenta3);
  return out;
}
function pills(j){ jobsDiv.innerHTML=''; Object.keys(j).forEach(id=>{const d=document.createElement('span');d.className='job-pill';d.textContent=id+' - '+j[id].status;jobsDiv.appendChild(d);});}
async function jobs(){ const r=await fetch('/jobs'); if(r.ok) pills(await r.json()); }

async function startJob(type, payload={}, onComplete=null){
  const r=await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type, ...payload})});
  if(!r.ok){st.textContent='Error';return;}
  const {job_id}=await r.json(); st.textContent='Job '+job_id; logc.style.display='block';
  const int=setInterval(async()=>{
    const s=await fetch('/status/'+job_id); if(!s.ok)return;
    const js=await s.json(); st.textContent='Job '+job_id+' - '+js.status;
    const lg=await fetch('/logs/'+job_id); const logText=await lg.text(); log.textContent=logText; log.scrollTop=log.scrollHeight;
    if(['finished','failed','killed'].includes(js.status)){ 
      clearInterval(int); jobs(); 
      if(onComplete && js.status==='finished') onComplete(logText, job_id);
    }
  },2000);
  jobs();
}

function pad(x){return String(x).padStart(2,'0');} function val(id){return document.getElementById(id).value;}

function openDateDialog(accounts=null, cb=null){
  const dlg=document.getElementById('dateDlg'); const sel=document.getElementById('accountSelect');
  const save=document.getElementById('dlgSaveBtn'); const cancel=document.getElementById('dlgCancelBtn');
  
  // Si ya tenemos cuentas (o variables globales), poblar inmediatamente
  if((accounts && Array.isArray(accounts) && accounts.length>0) || accountsFromVars().length>0){
    if((!accounts || accounts.length===0) && accountsFromVars().length>0){ accounts = accountsFromVars(); }
    sel.innerHTML='';
    accounts.forEach(a=>{
      const opt=document.createElement('option');
      if(typeof a==='object'){opt.value=a.value||a.text; opt.textContent=a.text;}
      else{opt.value=a; opt.textContent=a;} 
      sel.appendChild(opt);
    });
    if(accounts.length===0){sel.innerHTML='<option value="">(sin cuentas)</option>';}
    sel.disabled=false; save.disabled=false;
    dlg.showModal();
  } else {
    // Método antiguo: fetch de cuentas
    sel.innerHTML='<option>Cargando cuentas...</option>'; sel.disabled=true; save.disabled=true; dlg.showModal();
    fetch('/fetch_accounts',{method:'POST'}).then(r=>r.json()).then(js=>{
      const jid=js.job_id;
      const poll=setInterval(async()=>{
        const r=await fetch('/accounts/'+jid); if(!r.ok)return;
        const data=await r.json();
        if(data.status==='ready'){ clearInterval(poll); sel.innerHTML='';
          (data.accounts||[]).forEach(a=>{
            const opt=document.createElement('option');
            if(typeof a==='object'){opt.value=a.value||a.text; opt.textContent=a.text;}
            else{opt.value=a; opt.textContent=a;} sel.appendChild(opt);});
          if(!data.accounts||data.accounts.length===0){sel.innerHTML='<option value="">(sin cuentas)</option>'; }
          sel.disabled=false; save.disabled=false;
        }else if(data.status==='failed'){ clearInterval(poll); sel.innerHTML='<option>Error</option>'; save.disabled=false;}
      },1200);
    });
  }

  save.onclick=(e)=>{
    e.preventDefault();
    const d={d:val('d_d'),m:val('d_m'),y:val('d_y')};
    const h={d:val('h_d'),m:val('h_m'),y:val('h_y')};
    if(!d.d||!d.m||!d.y||!h.d||!h.m||!h.y){alert('Complete fechas');return;}
    const payload = {
      date_from: d.y+'-'+pad(d.m)+'-'+pad(d.d),
      date_to:   h.y+'-'+pad(h.m)+'-'+pad(h.d),
      account:   sel.value
    };
    if(cb){ cb(payload); }
    dlg.close();
  };
  cancel.onclick=()=>{try{dlg.close();}catch(e){}};
}

document.getElementById('runTransferBtn').onclick=()=>{
  console.log('Bot Transferencias clicked');
  startJob('transfer');
};

// Bot CSV: ejecutar bot, parsear cuentas del log, y abrir diálogo
document.getElementById('runCsvBtn').onclick = ()=>{
  console.log('Bot CSV clicked');
  startJob('csv', {}, (logText)=>{
    console.log('Bot CSV completado, parseando log...');
    console.log('Longitud del log:', logText.length);
    // 1) Intento de extracción ultra-sencillo: última línea que empieza con {"accounts":
    let accounts = [];
    try{
      const lines = logText.split('\\n');
      for(let i=lines.length-1;i>=0;i--){
        const ln = lines[i].trim();
        if(ln.startsWith('{"accounts":')){
          const parsed = JSON.parse(ln);
          accounts = parsed.accounts || [];
          break;
        }
      }
    }catch(e){ console.warn('Parse simple falló:', e); }

    // 2) Fallback aún más simple: buscar "Cuenta 1:" y "Cuenta 2:" en el log y construir variables
    if(accounts.length===0){
      try{
        const accs=[]; 
        const reLine=/^DEBUG:\s*Cuenta\s*(\d+)\s*:\s*(.+)$/gm; 
        let m; 
        while((m=reLine.exec(logText))!==null){ accs[parseInt(m[1],10)-1] = {value:m[2].trim(), text:m[2].trim()}; }
        if(accs.filter(Boolean).length>0){ accounts = accs.filter(Boolean); }
      }catch(e){ console.warn('Fallback por líneas DEBUG falló:', e); }
    }
    
    console.log('Cuentas encontradas:', accounts.length);
    
    // Abrir diálogo con las cuentas
    if(accounts.length > 0){
      console.log('Abriendo diálogo con cuentas:', accounts);
      // Guardar en variables globales cuenta1, cuenta2, cuenta3
      try{
        window.cuenta1 = accounts[0] || undefined;
        window.cuenta2 = accounts[1] || undefined;
        window.cuenta3 = accounts[2] || undefined;
      }catch(e){ console.warn('No se pudieron setear variables cuenta1/2/3:', e); }
      // Usar las variables para poblar el diálogo
      openDateDialog(accountsFromVars(), (payload)=>startJob('csv', payload));
    } else {
      console.error('No se encontraron cuentas en el log');
      // Intentar abrir con variables existentes (si quedaron de una ejecución previa)
      const fallback = accountsFromVars();
      if(fallback.length>0){
        console.log('Usando variables existentes cuenta1/2/3:', fallback);
        openDateDialog(fallback, (payload)=>startJob('csv', payload));
      } else {
        alert('No se pudieron cargar las cuentas. Revisa el log.');
      }
    }
  });
};

document.getElementById('stopAllBtn').onclick = async ()=>{
  console.log('STOP ALL clicked');
  if(confirm('¿Estás seguro de que quieres detener TODOS los procesos? Esto matará todos los bots y ventanas de Chrome.')){
    console.log('Usuario confirmó STOP ALL');
    const r=await fetch('/stop_all',{method:'POST'});
    if(r.ok){
      console.log('STOP ALL exitoso');
      st.textContent='Estado: STOPPING ALL...';
      logc.style.display='block';
      log.textContent='Deteniendo todos los procesos...';
      setTimeout(()=>{location.reload();},2000);
    }
  }
};
jobs(); setInterval(jobs,6000);
</script>
</body></html>"""

# ─────────────────────────── HELPERS / JOBS ─────────────────────────────────
def write_job_update(job_id: str, **kw): JOBS.setdefault(job_id, {}).update(kw)

def background_monitor(job_id: str, proc: subprocess.Popen):
    write_job_update(job_id, status="running", pid=proc.pid, started_at=time.time())
    rc = proc.wait()
    write_job_update(job_id, status="finished" if rc==0 else "failed",
                     finished_at=time.time(), returncode=rc)
    fh = FILE_HANDLES.pop(job_id, None)
    if fh: fh.close()

# ────────────────────────────  ROUTES  ──────────────────────────────────────
@APP.route("/")
def index(): return render_template_string(INDEX_HTML)

@APP.route("/jobs")
def jobs_list(): return jsonify(JOBS)

@APP.route("/run", methods=["POST"])
def run_job():
    data = request.get_json(silent=True) or {}
    job_type = data.get("type", "transfer")
    if job_type not in ("transfer", "csv"): return ("type inválido", 400)

    script = "bot.py" if job_type=="transfer" else "bot_csv.py"
    if not Path(script).exists(): return (f"{script} no encontrado", 500)

    job_id = uuid.uuid4().hex
    fh = open(LOGS_DIR/f"{job_id}.log", "a", buffering=1, encoding="utf-8")
    FILE_HANDLES[job_id]=fh

    env = {**os.environ, "PYTHONUNBUFFERED":"1"}
    if job_type=="csv":
        if data.get("date_from") and data.get("date_to"):
            env["DATE_FROM"]=data["date_from"]; env["DATE_TO"]=data["date_to"]
        if data.get("account"): env["ACCOUNT_SEL"]=data["account"]
        if "headless" in data: env["HEADLESS"]="1" if data["headless"] else "0"

    proc = subprocess.Popen([sys.executable,"-u",script], stdout=fh, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, env=env)
    write_job_update(job_id, status="started", pid=proc.pid, logfile=str(fh.name))
    threading.Thread(target=background_monitor,args=(job_id,proc),daemon=True).start()
    return jsonify({"job_id": job_id})

@APP.route("/status/<job_id>")
def status(job_id): return jsonify(JOBS.get(job_id, {})) if job_id in JOBS else ("not found",404)

@APP.route("/logs/<job_id>")
def logs(job_id):
    lp = LOGS_DIR/f"{job_id}.log"
    if not lp.exists(): return ("log?",404)
    return (lp.read_text(errors="ignore")[-20000:],200,{"Content-Type":"text/plain"})

# ─────────────────────── SCAN DE CUENTAS (SCAN_ONLY) ────────────────────────
def start_account_scan_job():
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status":"starting","accounts":None}
    fh = open(LOGS_DIR/f"{job_id}.scan.log", "a", buffering=1, encoding="utf-8")
    FILE_HANDLES[job_id]=fh

    def _run():
        try:
            env = {**os.environ,"PYTHONUNBUFFERED":"1","SCAN_ONLY":"1"}  # no forzamos HEADLESS
            proc = subprocess.Popen([sys.executable,"-u","bot_csv.py"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env)
            out,_ = proc.communicate()
            fh.write(out or "")
            if proc.returncode!=0:
                JOBS[job_id].update(status="failed", error="scan failed", returncode=proc.returncode); return

            accounts=[]; jstart=(out or "").rfind("{")
            if jstart!=-1:
                try: accounts=json.loads((out or "")[jstart:]).get("accounts",[])
                except Exception as e:
                    fh.write(f"\n[parse error] {e}"); JOBS[job_id].update(status="failed", error="parse"); return
            JOBS[job_id].update(status="ready", accounts=accounts)
        finally:
            try: fh.close()
            except: pass
    Thread(target=_run, daemon=True).start()
    return job_id

@APP.route("/fetch_accounts", methods=["POST"])
def fetch_accounts():
    job_id = start_account_scan_job(); return jsonify({"job_id": job_id})

@APP.route("/accounts/<job_id>")
def accounts_status(job_id):
    if job_id not in JOBS: return ("not found",404)
    d=JOBS[job_id]; return jsonify({"status":d.get("status"),"accounts":d.get("accounts")})

@APP.route("/stop_all", methods=["POST"])
def stop_all():
    """Mata absolutamente todos los procesos relacionados con bots y Chrome"""
    try:
        # Matar todos los procesos de Python que ejecuten bots
        subprocess.run(["pkill", "-9", "-f", "python.*bot"], capture_output=True)
        
        # Matar todos los procesos de Chrome
        subprocess.run(["killall", "-9", "Google Chrome"], capture_output=True)
        subprocess.run(["killall", "-9", "Chrome"], capture_output=True)
        
        # Matar todos los procesos de chromedriver
        subprocess.run(["killall", "-9", "chromedriver"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "chromedriver"], capture_output=True)
        
        # Limpiar todos los jobs
        for job_id in list(JOBS.keys()):
            fh = FILE_HANDLES.pop(job_id, None)
            if fh:
                try:
                    fh.close()
                except:
                    pass
            JOBS[job_id] = {"status": "killed", "killed_at": time.time()}
        
        return jsonify({"status": "success", "message": "Todos los procesos han sido detenidos"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ───────────────────────────────  MAIN  ──────────────────────────────────────
if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=int(os.environ.get("PORT",5001)), debug=False)
