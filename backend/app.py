import os
from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates
import hashlib
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



def render_login(
    request: Request,
    error: str | None = None,
    signup_success: str | None = None,
    signup_error: str | None = None,
):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": error,
            "signup_success": signup_success,
            "signup_error": signup_error,
        },
    )


@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str | None = None,
    signup_success: str | None = None,
    signup_error: str | None = None,
):
    return render_login(request, error, signup_success, signup_error)


@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    role = login.validate_credentials(username, password)
    if role == "applicant":
        return templates.TemplateResponse(
        "applicant.html",
        {"request": request})
    elif role == "recruiter":
        return templates.TemplateResponse(
        "recruiter.html",
        {"request": request})
    return render_login(request, error="Invalid username or password")


@app.post("/signup")
async def signup_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    sha256_hash = hashlib.sha256()
    sha256_hash.update(password.encode("utf-8"))
    hashed_password = sha256_hash.hexdigest()

    print(f"Hashed password: {hashed_password}")
    

    return render_login(
        request,
        signup_success="Account created. You can sign in now.",
    )
