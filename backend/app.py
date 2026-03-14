from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os
from fastapi.responses import FileResponse

# Initialize FastAPI app
app = FastAPI(title="CV Skill Tree", description="Skill Tree for CVs")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "../frontend/static")
templates_dir = os.path.join(BASE_DIR, "../frontend/templates")

if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
else:
    print("Static directory not found")

if os.path.isdir(templates_dir):
    app.mount("/templates", StaticFiles(directory=templates_dir), name="templates")
else:
    print("Templates directory not found")

@app.get("/")
async def root():
    return FileResponse(os.path.join(templates_dir, "login.html"))