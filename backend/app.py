import os
import re
import datetime
import pprint
import sys
import tempfile
import uuid
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import hashlib
from bson import ObjectId
from pymongo import ASCENDING, errors as pymongo_errors
from backend import login

from database import (
    get_credentials_collection,
    get_companies_collection,
    get_applications_collection,
    get_skills_profile_collection,
    get_job_collection,
)

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

# Session: keeps track of logged-in user (user_id, role, company_id for recruiters)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-secret-change-in-production"),
)


@app.on_event("startup")
async def create_indexes():
    """Ensure required indexes exist on startup."""
    try:
        apps = get_applications_collection()
        apps.create_index(
            [("user_id", ASCENDING), ("job_id", ASCENDING)],
            unique=True,
            name="unique_user_job",
        )
        apps.create_index([("job_id", ASCENDING)], name="idx_job_id")
        apps.create_index([("user_id", ASCENDING)], name="idx_user_id")
    except Exception as e:
        print(f"Warning: could not create indexes: {e}")



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
    if role is None:
        return render_login(request, error="Invalid username or password")

    # Load user doc to get user_id and (for recruiters) company_id for session
    creds = get_credentials_collection()
    user = creds.find_one({"username": username.strip()})
    if not user:
        # Fallback users (e.g. recruiter1) may not be in DB; no session company_id
        user = {"user_id": None, "role": role, "company_id": None}
    request.session["user_id"] = user.get("user_id")
    request.session["role"] = role
    if role == "recruiter":
        request.session["company_id"] = user.get("company_id")

    if role == "applicant":
        return RedirectResponse(url="/applicant", status_code=303)
    return RedirectResponse(url="/recruiter", status_code=303)


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
def _get_applied_jobs_for_user(user_id: str):
    """Fetch all applications for user_id and return list with job title, company name, preview, applied_at, status."""
    apps_coll = get_applications_collection()
    jobs_coll = get_job_collection()
    companies_coll = get_companies_collection()
    applications = list(apps_coll.find({"user_id": user_id}).sort("applied_at", -1))
    result = []
    for app in applications:
        job_id = app.get("job_id")
        job_title = app.get("job_title", "")
        company_id = app.get("company_id", "")
        company_name = ""
        try:
            company = companies_coll.find_one({"_id": ObjectId(company_id)})
            if company:
                company_name = company.get("name", "")
        except (TypeError, ValueError):
            pass
        preview = ""
        qualifications = ""
        created_at = ""
        try:
            job = jobs_coll.find_one({"_id": ObjectId(job_id)})
            if job:
                preview = job.get("preview", "")
                qualifications = job.get("qualifications", "")
                created = job.get("created_at")
                created_at = created.isoformat() + "Z" if hasattr(created, "isoformat") else str(created) if created else ""
        except (TypeError, ValueError):
            pass
        applied_at = app.get("applied_at")
        applied_str = applied_at.isoformat() + "Z" if hasattr(applied_at, "isoformat") else str(applied_at) if applied_at else ""
        applied_formatted = applied_at.strftime("%b %d, %Y") if applied_at and hasattr(applied_at, "strftime") else (applied_str[:10] if applied_str else "")
        result.append({
            "id": job_id,
            "title": job_title,
            "company_name": company_name,
            "preview": preview,
            "qualifications": qualifications,
            "created_at": created_at,
            "applied_at": applied_str,
            "applied_at_formatted": applied_formatted,
            "status": app.get("status", ""),
        })
    return result


@app.get("/applicant/applied-jobs", response_class=HTMLResponse)
async def applicant_applied_jobs_page(request: Request):
    """Show jobs the logged-in applicant has applied to. Requires applicant session."""
    if request.session.get("role") != "applicant" or not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)
    jobs = _get_applied_jobs_for_user(request.session["user_id"])
    return templates.TemplateResponse(
        "applied-jobs.html",
        {"request": request, "jobs": jobs},
    )


@app.get("/recruiter", response_class=HTMLResponse)
async def recruiter_page(
    request: Request,
    added: str | None = None,
    error: str | None = None,
):
    return templates.TemplateResponse(
        "recruiter.html",
        {"request": request, "job_added": added is not None, "job_error": error is not None},
    )


def _get_random_jobs_with_company_names(n: int = 5):
    """Fetch n random jobs from JobsData and resolve company name for each. Full details for modal."""
    jobs_coll = get_job_collection()
    companies_coll = get_companies_collection()
    pipeline = [{"$sample": {"size": n}}]
    cursor = jobs_coll.aggregate(pipeline)
    result = []
    for job in cursor:
        company_name = ""
        try:
            company = companies_coll.find_one({"_id": ObjectId(job["company_id"])})
            if company:
                company_name = company.get("name", "")
        except (TypeError, ValueError):
            pass
        created = job.get("created_at")
        created_str = created.isoformat() + "Z" if hasattr(created, "isoformat") else str(created) if created else ""
        result.append({
            "id": str(job["_id"]),
            "company_id": str(job.get("company_id", "")),
            "title": job.get("title", ""),
            "preview": job.get("preview", ""),
            "qualifications": job.get("qualifications", ""),
            "company_name": company_name,
            "created_at": created_str,
        })
    return result


@app.get("/apply", response_class=HTMLResponse)
async def apply_page(
    request: Request,
    applied: str | None = None,
    error: str | None = None,
):
    jobs = _get_random_jobs_with_company_names(5)
    while len(jobs) < 5:
        jobs.append(None)
    return templates.TemplateResponse(
        "apply.html",
        {"request": request, "jobs": jobs, "applied": applied is not None, "error": error},
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
    company_name: str = Form(""),
):
    sha256_hash = hashlib.sha256()
    sha256_hash.update(password.encode("utf-8"))
    hashed_password = sha256_hash.hexdigest()

    if role == "recruiter" and not (company_name or "").strip():
        return render_login(
            request,
            signup_error="Recruiters must provide a company name.",
        )

    try:
        creds = get_credentials_collection()
        if creds.find_one({"username": username}):
            return render_login(
                request,
                signup_error="Username already taken. Choose another.",
            )
        user_id = str(uuid.uuid4())
        credential_doc = {
            "user_id": user_id,
            "username": username,
            "password": hashed_password,
            "role": role,
        }

        if role == "recruiter":
            companies = get_companies_collection()
            name_clean = company_name.strip()
            name_escaped = re.escape(name_clean)
            existing_company = companies.find_one({
                "name": {"$regex": f"^\\s*{name_escaped}\\s*$", "$options": "i"}
            })
            if existing_company:
                company_id = str(existing_company["_id"])
            else:
                # Create new company in Jobs.CompanyCollection; _id is auto-generated ObjectId
                result = companies.insert_one({
                    "name": name_clean,
                    "created_at": datetime.datetime.utcnow(),
                })
                company_id = str(result.inserted_id)
            credential_doc["company_id"] = company_id

        creds.insert_one(credential_doc)
    except Exception as e:
        return render_login(
            request,
            signup_error=f"Could not create account: {e}",
        )

    return render_login(
        request,
        signup_success="Account created. You can sign in now.",
    )


@app.post("/recruiter/jobs")
async def recruiter_create_job(
    request: Request,
    title: str = Form(...),
    preview: str = Form(""),
    qualifications: str = Form(""),
):
    """Create a job in Jobs.JobsData; company_id and posted_by come from session."""
    if request.session.get("role") != "recruiter" or not request.session.get("company_id"):
        return RedirectResponse(url="/login", status_code=303)
    try:
        jobs = get_job_collection()
        jobs.insert_one({
            "company_id": request.session["company_id"],
            "posted_by": request.session.get("user_id"),
            "title": title.strip(),
            "preview": (preview or "").strip(),
            "qualifications": (qualifications or "").strip(),
            "created_at": datetime.datetime.utcnow(),
        })
    except Exception as e:
        return RedirectResponse(url="/recruiter?error=1", status_code=303)
    return RedirectResponse(url="/recruiter?added=1", status_code=303)


@app.post("/applications")
async def create_application(request: Request, job_id: str = Form(...)):
    """
    Create an application for a job. Uses session user_id (applicant).
    Stores in Jobs.ApplicationsCollection: user_id, company_id, job_id, job_title, etc.
    """
    user_id = request.session.get("user_id")
    if request.session.get("role") != "applicant" or not user_id:
        return RedirectResponse(url="/login", status_code=303)

    try:
        jobs_coll = get_job_collection()
        job = jobs_coll.find_one({"_id": ObjectId(job_id)})
        if not job:
            return RedirectResponse(url="/apply?error=job_not_found", status_code=303)

        company_id = str(job.get("company_id", ""))
        job_title = job.get("title", "")

        skills_col = get_skills_profile_collection()
        profile_doc = skills_col.find_one({"user_id": user_id}, {"_id": 0})
        applicant_snapshot = {}
        if profile_doc:
            applicant_snapshot = {
                "profile_data": profile_doc.get("profile_data"),
                "github_url": profile_doc.get("github_url"),
                "content_hash": profile_doc.get("content_hash"),
            }

        apps = get_applications_collection()
        apps.insert_one({
            "user_id": user_id,
            "company_id": company_id,
            "job_id": job_id,
            "job_title": job_title,
            "status": "pending",
            "applied_at": datetime.datetime.utcnow(),
            "applicant_snapshot": applicant_snapshot,
        })
    except pymongo_errors.DuplicateKeyError:
        return RedirectResponse(url="/apply?error=already_applied", status_code=303)
    except Exception as e:
        return RedirectResponse(url="/apply?error=1", status_code=303)

    return RedirectResponse(url="/apply?applied=1", status_code=303)


@app.get("/jobs/{job_id}/applications", response_class=HTMLResponse)
async def list_applications(request: Request, job_id: str):
    """
    Returns all applications for a given job (for recruiter use).
    Auth/ownership check to be added when session logic is implemented.
    """
    try:
        apps = get_applications_collection()
        application_list = list(apps.find({"job_id": job_id}, {"_id": 0}))
    except Exception as e:
        application_list = []

    return templates.TemplateResponse(
        "applications.html",
        {"request": request, "job_id": job_id, "applications": application_list},
    )
