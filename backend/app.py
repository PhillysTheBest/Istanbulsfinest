import os
from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from backend import login

app = FastAPI(title="CV Skill Tree", description="Skill Tree for CVs")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "../frontend/static")
templates_dir = os.path.join(BASE_DIR, "../frontend/templates")
templates = Jinja2Templates(directory=templates_dir)

if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
else:
    print("Static directory not found")


def render_login(request: Request, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
    )


@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
    )


@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if login.validate_credentials(username, password):
        return templates.TemplateResponse(
            "index.html",
            {"request": request},
        )
    else:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
        )
