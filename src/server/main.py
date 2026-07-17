"""Standalone FastAPI entry point for the futuristic Autonomous architecture."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .router import router
from .operations_router import router as operations_router

app = FastAPI(title="Amosclaud Futuristic Autonomous Agent", version="2.1.0")
app.include_router(router)
app.include_router(operations_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "amosclaud-futuristic-autonomous"}


@app.get("/agent-mission-control", response_class=HTMLResponse)
def agent_mission_control() -> str:
    return """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Agent Mission Control</title><style>
body{font-family:system-ui;background:#08111f;color:#e8f1ff;margin:0;padding:24px}.wrap{max-width:1200px;margin:auto}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}.card,.job{background:#101d31;border:1px solid #29405f;border-radius:16px;padding:18px}.value{font-size:32px;font-weight:800}.job{margin-top:12px}.bar{height:10px;background:#27364b;border-radius:8px;overflow:hidden}.bar span{display:block;height:100%;background:#62a9ff}.status{font-weight:700;text-transform:capitalize}.muted{color:#9db0ca}button{padding:12px 16px;border:0;border-radius:10px;font-weight:700}</style></head><body><main class='wrap'><h1>Amosclaud Agent Mission Control</h1><p class='muted'>Live jobs, assigned agents, progress, blockers, evidence and truthful results.</p><div class='cards'><div class='card'><div class='muted'>Active</div><div id='active' class='value'>0</div></div><div class='card'><div class='muted'>Completed</div><div id='completed' class='value'>0</div></div><div class='card'><div class='muted'>Failed or blocked</div><div id='failed' class='value'>0</div></div></div><h2>Jobs</h2><div id='jobs'>Loading…</div></main><script>
const esc=v=>String(v??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
async function refresh(){const r=await fetch('/api/v2/agent-operations/mission-control');const d=await r.json();active.textContent=d.active_jobs;completed.textContent=d.completed_jobs;failed.textContent=d.failed_or_blocked_jobs;jobs.innerHTML=d.jobs.map(j=>`<article class='job'><div class='status'>${esc(j.status)} · ${esc(j.agent)}</div><h3>${esc(j.objective)}</h3><div class='bar'><span style='width:${Number(j.progress)||0}%'></span></div><p>${Number(j.progress)||0}% · ${esc(j.mode)} · ${esc(j.id)}</p>${j.blocker?`<p><strong>Blocker:</strong> ${esc(j.blocker)}</p>`:''}<details><summary>Evidence and result</summary><pre>${esc(JSON.stringify({evidence:j.evidence,result:j.result},null,2))}</pre></details></article>`).join('')||'<p>No jobs yet.</p>'}refresh();setInterval(refresh,3000);
</script></body></html>"""
