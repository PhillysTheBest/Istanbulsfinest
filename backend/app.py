import os
import pprint
import sys
import tempfile
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates
import hashlib
from backend import login
from database import get_skills_profile_collection

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from CVScraperJSON import extract_github_url, extract_skills_tree, extract_text_from_pdf, scrape_github_profile

app = FastAPI(title="CV Skill Tree", description="Skill Tree for CVs")
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
            {"request": request, "success": False},
        )
    elif role == "recruiter":
        return templates.TemplateResponse(
        "recruiter.html",
        {"request": request})
    return render_login(request, error="Invalid username or password")


@app.get("/applicant", response_class=HTMLResponse)
async def applicant_page(request: Request, success: str | None = None):
    return templates.TemplateResponse(
        "applicant.html",
        {"request": request, "success": success is not None},
    )


@app.get("/applicant/tree", response_class=HTMLResponse)
async def skill_tree_page(request: Request):
    # Fetch the latest profile for now (simple hackathon logic)
    # In a real app, we'd filter by user_id/session
    collection = get_skills_profile_collection()
    profile = collection.find_one(sort=[("_id", -1)])
    
    if not profile:
        return RedirectResponse(url="/applicant")
        
    return templates.TemplateResponse(
        "skill_tree.html",
        {"request": request, "profile": profile}
    )


@app.post("/applicant/profile")
async def applicant_profile_post(
    request: Request,
    cv: UploadFile = File(...),
    linkedin: str = Form(""),
    github: str = Form(""),
    portfolio: str = Form(""),
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await cv.read()
        tmp.write(content)
        tmp_path = tmp.name
    try:
        # CV from applicant form submit → CVScraperJSON.extract_text_from_pdf
        extracted_text = extract_text_from_pdf(tmp_path)
        github_url, github_username = extract_github_url(github)
        if github_username:
            github_content = scrape_github_profile(github_username)
        else:
            github_content = ""
        extracted_skills = extract_skills_tree(extracted_text, github_content)
        
        # Store in MongoDB
        collection = get_skills_profile_collection()
        collection.update_one(
            {"name": extracted_skills.get("Name", "Unknown")},
            {"$set": extracted_skills},
            upsert=True
        )
        
        pprint.pprint(extracted_skills)
    finally:
        os.unlink(tmp_path)
    return RedirectResponse(url="/applicant?success=1", status_code=303)


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
