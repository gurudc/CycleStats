"""CycleStats — Combined Health & Cycling Dashboard."""
import os
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from routers import activities, gear, health, training, garmin, strava, auth, segments, coach
from database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_db()
    logger.info("CycleStats ready!")
    yield


app = FastAPI(
    title="CycleStats",
    description="Combined Health & Cycling Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://cyclestats.colahan.cc", "http://localhost:8080", "http://127.0.0.1:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(activities.router)
app.include_router(health.router)
app.include_router(training.router)
app.include_router(garmin.router)
app.include_router(strava.router)
app.include_router(auth.router)
app.include_router(segments.router)
app.include_router(coach.router)
app.include_router(gear.router, prefix="/api/gear", tags=["gear"])

static_dir = Path("/opt/cyclestats/backend/static")
frontend_dir = Path("/opt/cyclestats/frontend")

if static_dir.exists():
    @app.get("/static/js/app.js")
    def serve_app_js():
        from fastapi.responses import FileResponse
        import os as _os
        path = _os.path.join(str(static_dir), "js", "app.js")
        return FileResponse(path, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})

    app.mount("/static", StaticFiles(directory=str(static_dir), html=False), name="static_files")

    @app.get("/app.js")
    def app_js():
        import time
        return FileResponse(str(static_dir / "js" / "app.js"),
            headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})

    @app.get("/login.html")
    def login_page():
        login_path = static_dir / "login.html"
        if login_path.exists():
            return FileResponse(str(login_path), headers={"Cache-Control": "no-cache"})
        return {"error": "Login page not found"}

    @app.get("/")
    def index():
        return FileResponse(str(static_dir / "index.html"), headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})

elif frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend_root")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    logger.info("CycleStats starting")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
