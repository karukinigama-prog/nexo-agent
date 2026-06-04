import os
import asyncio
import subprocess
import uuid
import time
import socket
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from groq_agent import generate_app_code, get_model_info

# ── Dirs ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
WORKSPACE  = BASE_DIR / "workspace"
STATIC_DIR = BASE_DIR / "static"
SHOTS_DIR  = STATIC_DIR / "screenshots"

for d in [WORKSPACE, STATIC_DIR, SHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── In-memory project store ───────────────────────────────────────────────
projects: dict[str, dict] = {}

# ── Port pool (these are LOCAL ports for sandboxed sub-apps) ──────────────
_used_ports: dict[int, object] = {}

def find_free_port(start=8200, end=8400) -> int:
    for port in range(start, end):
        if port in _used_ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free ports available.")

def kill_port(port: int):
    proc = _used_ports.pop(port, None)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass

# ── Screenshot helper ─────────────────────────────────────────────────────
async def take_screenshot(url: str, out_path: str) -> bool:
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                ]
            )
            ctx  = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await ctx.new_page()
            for _ in range(6):
                try:
                    await page.goto(url, wait_until="networkidle", timeout=12000)
                    await asyncio.sleep(1.5)
                    await page.screenshot(path=out_path, type="png")
                    await browser.close()
                    return True
                except Exception:
                    await asyncio.sleep(2)
            await browser.close()
            return False
    except Exception as e:
        print(f"[Nexo] Screenshot error: {e}")
        return False

# ── FastAPI ───────────────────────────────────────────────────────────────
app = FastAPI(title="Nexo AI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

class GenerateRequest(BaseModel):
    prompt: str

# ── SSE Pipeline ──────────────────────────────────────────────────────────
async def nexo_pipeline(prompt: str):
    pid = str(uuid.uuid4())[:8]
    emit = lambda m: f"data: {m}\n\n"

    yield emit(f"[Nexo] 🚀 Starting pipeline for project #{pid}...")
    await asyncio.sleep(0.2)

    # STEP 1 & 2 — Groq LLM
    yield emit(f"[Nexo] 🧠 Querying Groq ({get_model_info()})...")
    await asyncio.sleep(0.1)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, generate_app_code, prompt)
    except Exception as e:
        yield emit(f"[Nexo] ❌ Groq error: {e}")
        yield emit("__ERROR__")
        return

    code  = result.get("code", "")
    fname = result.get("filename", "app.py")

    if not code.strip():
        yield emit("[Nexo] ❌ Empty code returned from LLM.")
        yield emit("__ERROR__")
        return

    yield emit(f"[Nexo] ✅ Code generated — {len(code.splitlines())} lines.")
    await asyncio.sleep(0.1)

    # STEP 3 — Write to workspace
    proj_dir = WORKSPACE / pid
    proj_dir.mkdir(parents=True, exist_ok=True)
    app_file = proj_dir / fname
    app_file.write_text(code, encoding="utf-8")
    yield emit(f"[Nexo] 📁 Saved → workspace/{pid}/{fname}")
    await asyncio.sleep(0.1)

    # STEP 3b — Start subprocess
    try:
        port = find_free_port()
    except RuntimeError as e:
        yield emit(f"[Nexo] ❌ {e}")
        yield emit("__ERROR__")
        return

    yield emit(f"[Nexo] 🔌 Launching sandbox on port {port}...")
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["FLASK_ENV"] = "production"

    # Ensure flask is installed
    subprocess.run(
        ["pip", "install", "flask", "--quiet", "--disable-pip-version-check"],
        capture_output=True
    )

    proc = subprocess.Popen(
        ["python", str(app_file)],
        env=env, cwd=str(proj_dir),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _used_ports[port] = proc

    # Wait for server ready
    yield emit(f"[Nexo] ⏳ Waiting for sandbox server...")
    ready = False
    for _ in range(20):
        await asyncio.sleep(0.7)
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                ready = True
                break

    if not ready:
        yield emit("[Nexo] ⚠️  Sandbox server slow to start — continuing anyway.")

    # On Render, sub-apps are only accessible internally (localhost:port)
    # We expose them via our /proxy/{port} route
    is_render = os.environ.get("RENDER", "false").lower() == "true"
    if is_render:
        # Get the Render service URL from env if available
        render_host = os.environ.get("RENDER_EXTERNAL_URL", "")
        live_url = f"{render_host}/proxy/{port}" if render_host else f"/proxy/{port}"
    else:
        live_url = f"http://localhost:{port}"

    yield emit(f"[Nexo] 🌐 Sandbox live → {live_url}")
    await asyncio.sleep(0.2)

    # STEP 4 — Screenshot
    yield emit("[Nexo] 📸 Capturing screenshot via headless Chromium...")
    shot_name = f"{pid}.png"
    shot_path = str(SHOTS_DIR / shot_name)
    shot_ok   = await take_screenshot(f"http://127.0.0.1:{port}", shot_path)

    if shot_ok:
        yield emit(f"[Nexo] 🖼️  Screenshot saved.")
    else:
        yield emit("[Nexo] ⚠️  Screenshot failed (app still running).")

    # Store project
    projects[pid] = {
        "port":       port,
        "pid_proc":   proc.pid,
        "url":        live_url,
        "internal":   f"http://127.0.0.1:{port}",
        "screenshot": f"/static/screenshots/{shot_name}" if shot_ok else None,
        "filename":   fname,
        "code":       code,
        "prompt":     prompt,
        "ts":         time.time(),
    }

    yield emit(f"[Nexo] ✅ Pipeline complete for #{pid}!")
    yield emit(f"__DONE__{pid}")

# ── Routes ────────────────────────────────────────────────────────────────
@app.get("/")
async def serve_ui():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.post("/generate")
async def generate(req: GenerateRequest):
    return StreamingResponse(
        nexo_pipeline(req.prompt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/project/{project_id}")
async def get_project(project_id: str):
    p = projects.get(project_id)
    if not p:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(p)

@app.get("/projects")
async def list_projects():
    return JSONResponse([
        {"id": k, "prompt": v["prompt"][:60], "url": v["url"],
         "screenshot": v.get("screenshot"), "ts": v["ts"]}
        for k, v in sorted(projects.items(), key=lambda x: -x[1]["ts"])
    ])

# ── Reverse proxy for sandboxed apps on Render ────────────────────────────
@app.api_route("/proxy/{port}/{path:path}", methods=["GET","POST","PUT","DELETE","OPTIONS"])
async def proxy(port: int, path: str, request: Request):
    import httpx
    target = f"http://127.0.0.1:{port}/{path}"
    params = str(request.url.query)
    if params:
        target += f"?{params}"
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target,
                headers=dict(request.headers),
                content=body,
                timeout=15,
            )
            from fastapi.responses import Response
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=502)

@app.api_route("/proxy/{port}", methods=["GET","POST"])
async def proxy_root(port: int, request: Request):
    return await proxy(port, "", request)

@app.get("/health")
async def health():
    return {"status": "ok", "model": get_model_info(), "projects": len(projects)}

# ── Start ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
