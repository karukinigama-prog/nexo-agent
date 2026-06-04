import os
import asyncio
import subprocess
import uuid
import time
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from port_manager import find_free_port, register_port, release_port
from groq_agent import generate_app_code, get_model_info
from screenshot import capture_screenshot_async

# ── Directory setup ──────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
WORKSPACE  = BASE_DIR / "workspace"
STATIC_DIR = BASE_DIR / "static"
SHOTS_DIR  = STATIC_DIR / "screenshots"

for d in [WORKSPACE, STATIC_DIR, SHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── App registry: project_id → {port, pid, screenshot, ...} ─────────────────
projects: dict[str, dict] = {}

# ── FastAPI setup ─────────────────────────────────────────────────────────────
app = FastAPI(title="Nexo AI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Request models ────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    prompt: str


# ── SSE stream generator ──────────────────────────────────────────────────────
async def nexo_pipeline(prompt: str) -> AsyncGenerator[str, None]:
    project_id = str(uuid.uuid4())[:8]

    def emit(msg: str):
        return f"data: {msg}\n\n"

    yield emit(f"[Nexo] 🚀 Initialising agent for project #{project_id}...")
    await asyncio.sleep(0.3)

    # ── STEP 1 & 2: Groq LLM ─────────────────────────────────────────────────
    yield emit(f"[Nexo] 🧠 Querying Groq ({get_model_info()}) — crafting your application...")
    await asyncio.sleep(0.2)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, generate_app_code, prompt)
    except Exception as e:
        yield emit(f"[Nexo] ❌ Groq error: {e}")
        yield emit("__ERROR__")
        return

    code    = result.get("code", "")
    fname   = result.get("filename", "app.py")
    lang    = result.get("language", "python")

    yield emit(f"[Nexo] ✅ Code generated — {len(code.splitlines())} lines of {lang}.")
    await asyncio.sleep(0.2)

    # ── STEP 3: Write to workspace ────────────────────────────────────────────
    proj_dir = WORKSPACE / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    app_file = proj_dir / fname
    app_file.write_text(code, encoding="utf-8")

    yield emit(f"[Nexo] 📁 Code written → workspace/{project_id}/{fname}")
    await asyncio.sleep(0.2)

    # ── STEP 3b: Allocate port & start subprocess ─────────────────────────────
    port = find_free_port()
    yield emit(f"[Nexo] 🔌 Allocated port {port} — starting live server...")
    await asyncio.sleep(0.2)

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["FLASK_ENV"] = "production"

    # Install flask silently if missing
    subprocess.run(
        ["pip", "install", "flask", "--quiet", "--disable-pip-version-check"],
        capture_output=True
    )

    proc = subprocess.Popen(
        ["python", str(app_file)],
        env=env,
        cwd=str(proj_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    register_port(port, proc.pid)

    # Wait for server to be ready
    yield emit(f"[Nexo] ⏳ Waiting for server to become ready on port {port}...")
    for _ in range(20):
        await asyncio.sleep(0.6)
        import socket
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break

    live_url = f"http://localhost:{port}"
    yield emit(f"[Nexo] 🌐 Server live → {live_url}")
    await asyncio.sleep(0.3)

    # ── STEP 4: Headless screenshot ───────────────────────────────────────────
    yield emit("[Nexo] 📸 Launching headless Chromium — capturing screenshot...")
    await asyncio.sleep(0.2)

    shot_name = f"{project_id}.png"
    shot_path = str(SHOTS_DIR / shot_name)
    shot_ok   = await capture_screenshot_async(live_url, shot_path)

    if shot_ok:
        yield emit(f"[Nexo] 🖼️  Screenshot captured → static/screenshots/{shot_name}")
    else:
        yield emit("[Nexo] ⚠️  Screenshot failed (server still running).")

    await asyncio.sleep(0.2)

    # Store project
    projects[project_id] = {
        "port": port,
        "pid":  proc.pid,
        "url":  live_url,
        "screenshot": f"/static/screenshots/{shot_name}" if shot_ok else None,
        "filename": fname,
        "code": code,
        "prompt": prompt,
        "ts": time.time(),
    }

    yield emit(f"[Nexo] ✅ Pipeline complete for project #{project_id}!")
    yield emit(f"__DONE__{project_id}")


# ── Routes ────────────────────────────────────────────────────────────────────

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
    proj = projects.get(project_id)
    if not proj:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(proj)

@app.get("/projects")
async def list_projects():
    items = [
        {
            "id": pid,
            "prompt": p["prompt"][:60] + ("..." if len(p["prompt"]) > 60 else ""),
            "url": p["url"],
            "screenshot": p.get("screenshot"),
            "ts": p["ts"],
        }
        for pid, p in sorted(projects.items(), key=lambda x: -x[1]["ts"])
    ]
    return JSONResponse(items)

@app.delete("/project/{project_id}")
async def delete_project(project_id: str):
    proj = projects.pop(project_id, None)
    if proj:
        release_port(proj["port"])
        return JSONResponse({"status": "deleted"})
    return JSONResponse({"error": "Not found"}, status_code=404)

@app.get("/health")
async def health():
    return {"status": "ok", "model": get_model_info(), "active_projects": len(projects)}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=7860, reload=False)
