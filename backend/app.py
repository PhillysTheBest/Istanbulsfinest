import os
import re
import datetime
import pprint
import sys
import tempfile
import uuid
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
from backend.interview_prep import generate_interview_script, generate_audio_base64, rank_applicants_by_eligibility
from security_utils import generate_skill_hash
from solana_integration import SkillRegistryClient
from verification import router as verification_router
from onboarding import router as onboarding_router

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

# Mount the Verification API
app.include_router(verification_router)
app.include_router(onboarding_router)


def _index_key_names(info):
    """Return list of field names in an index key (handles list of tuples or dict)."""
    key = info.get("key")
    if key is None:
        return []
    if isinstance(key, dict):
        return list(key.keys())
    return [item[0] for item in list(key)]


@app.on_event("startup")
async def create_indexes():
    """Ensure required indexes exist on startup. Drop any unique index on job_id only (would block multiple users applying to same job)."""
    try:
        apps = get_applications_collection()
        indexes = apps.index_information()
        for name, info in list(indexes.items()):
            key_names = sorted(_index_key_names(info))
            is_unique = info.get("unique", False)
            print(f"[startup] Applications index: {name!r} key={key_names} unique={is_unique}")
            if name == "_id_":
                continue
            if is_unique and key_names == ["job_id"]:
                try:
                    apps.drop_index(name)
                    print(f"[startup] Dropped unique index on job_id only: {name!r}")
                except Exception as drop_err:
                    print(f"[startup] Failed to drop index {name!r}: {drop_err}")
            elif is_unique and len(key_names) == 1 and "job_id" in key_names:
                try:
                    apps.drop_index(name)
                    print(f"[startup] Dropped unique single-field job_id index: {name!r}")
                except Exception as drop_err:
                    print(f"[startup] Failed to drop index {name!r}: {drop_err}")
            elif is_unique and name == "job_id_1":
                try:
                    apps.drop_index(name)
                    print(f"[startup] Dropped unique index by name: {name!r}")
                except Exception as drop_err:
                    print(f"[startup] Failed to drop index {name!r}: {drop_err}")
            elif is_unique and "applicant_id" in key_names:
                try:
                    apps.drop_index(name)
                    print(f"[startup] Dropped unique index on applicant_id: {name!r} (app uses user_id)")
                except Exception as drop_err:
                    print(f"[startup] Failed to drop index {name!r}: {drop_err}")
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
    uid = user.get("user_id")
    request.session["user_id"] = str(uid) if uid is not None else None
    request.session["role"] = role
    request.session["username"] = user.get("username", username.strip())
    if role == "recruiter":
        request.session["company_id"] = user.get("company_id")

    if role == "applicant":
        return RedirectResponse(url="/applicant", status_code=303)
    return RedirectResponse(url="/recruiter", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


def _applicant_has_profile(user_id: str) -> bool:
    if not user_id:
        return False
    collection = get_skills_profile_collection()
    return collection.find_one({"user_id": user_id}) is not None


@app.get("/applicant", response_class=HTMLResponse)
async def applicant_page(request: Request, success: str | None = None):
    if request.session.get("role") != "applicant":
        return RedirectResponse(url="/login", status_code=303)
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    if not _applicant_has_profile(user_id):
        return RedirectResponse(url="/applicant/upload", status_code=303)
    return RedirectResponse(url="/applicant/tree", status_code=303)


@app.get("/applicant/upload", response_class=HTMLResponse)
async def applicant_upload_page(request: Request):
    """CV upload page for applicants who have not yet uploaded. Required before seeing tree/dashboard."""
    if request.session.get("role") != "applicant":
        return RedirectResponse(url="/login", status_code=303)
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    if _applicant_has_profile(user_id):
        return RedirectResponse(url="/applicant/tree", status_code=303)
    return templates.TemplateResponse(
        "applicant_upload.html",
        {"request": request},
    )


@app.get("/applicant/tree", response_class=HTMLResponse)
async def skill_tree_page(request: Request):
    if request.session.get("role") != "applicant":
        return RedirectResponse(url="/login", status_code=303)
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    collection = get_skills_profile_collection()
    profile = collection.find_one({"user_id": user_id})
    if not profile:
        return RedirectResponse(url="/applicant/upload", status_code=303)
    return templates.TemplateResponse(
        "skill_tree.html",
        {"request": request, "profile": profile}
    )

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


def _get_jobs_for_company(company_id: str):
    """Fetch all jobs for a company, most recent first."""
    if not company_id:
        return []
    try:
        jobs_coll = get_job_collection()
        cursor = jobs_coll.find({"company_id": company_id}).sort("created_at", -1)
        result = []
        for job in cursor:
            created = job.get("created_at")
            created_str = created.isoformat() + "Z" if hasattr(created, "isoformat") else str(created) if created else ""
            result.append({
                "id": str(job["_id"]),
                "title": job.get("title", ""),
                "preview": job.get("preview", ""),
                "qualifications": job.get("qualifications", ""),
                "created_at": created_str,
            })
        return result
    except Exception:
        return []


@app.get("/recruiter", response_class=HTMLResponse)
async def recruiter_page(
    request: Request,
    added: str | None = None,
    error: str | None = None,
):
    if request.session.get("role") != "recruiter":
        return RedirectResponse(url="/login", status_code=303)
    company_id = request.session.get("company_id")
    recruiter_name = request.session.get("username", "Recruiter")
    jobs = _get_jobs_for_company(company_id) if company_id else []
    return templates.TemplateResponse(
        "recruiter.html",
        {
            "request": request,
            "recruiter_name": recruiter_name,
            "jobs": jobs,
            "job_added": added is not None,
            "job_error": error is not None,
        },
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
    solana_wallet: str = Form(""),
):
    if request.session.get("role") != "applicant":
        return RedirectResponse(url="/login", status_code=303)
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await cv.read()
        tmp.write(content)
        tmp_path = tmp.name
    try:
        extracted_text = extract_text_from_pdf(tmp_path)
        github_url, github_username = extract_github_url(github)
        if github_username:
            github_content = scrape_github_profile(github_username)
        else:
            github_content = ""
        extracted_skills = extract_skills_tree(extracted_text, github_content)
        extracted_skills["user_id"] = user_id

        collection = get_skills_profile_collection()
        collection.update_one(
            {"user_id": user_id},
            {"$set": extracted_skills},
            upsert=True,
        )
        
        # --- WEB2 END ---
        
        # --- WEB3 BEGIN ---
        # 1. Generate SHA-256 Hash for the Skill Tree
        skill_hash = generate_skill_hash(extracted_skills)
        
        # 2. Anchor to Solana Blockchain 
        # (Assuming the candidate's wallet is provided in the form or extracted)
        # Requirement: "candidate_wallet: the candidate's Solana public key (string)"
        candidate_wallet = solana_wallet if solana_wallet else github
        
        try:
            print(f"Anchoring Skill Tree to Solana for wallet: {candidate_wallet}")
            registry = SkillRegistryClient()
            tx_sig = registry.issue_skill_passport(candidate_wallet, skill_hash)
            
            if tx_sig:
                blockchain_status = "CONFIRMED"
                solana_tx_sig = tx_sig
            else:
                blockchain_status = "PENDING"
                solana_tx_sig = None
        except Exception as e:
            print(f"Solana Anchoring Error: {e}")
            blockchain_status = "PENDING"
            solana_tx_sig = None

        # 3. Update MongoDB with Web3 metadata
        collection.update_one(
            {"name": extracted_skills.get("Name", "Unknown")},
            {"$set": {
                "candidate_wallet": candidate_wallet,
                "skill_hash": skill_hash,
                "solana_tx_signature": solana_tx_sig,
                "blockchain_status": blockchain_status
            }},
            upsert=True
        )
        # --- WEB3 END ---
        
        pprint.pprint(extracted_skills)
    finally:
        os.unlink(tmp_path)
    return RedirectResponse(url="/applicant/tree", status_code=303)


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
    raw_user_id = request.session.get("user_id")
    user_id = str(raw_user_id).strip() if raw_user_id else None
    if request.session.get("role") != "applicant" or not user_id:
        return RedirectResponse(url="/login", status_code=303)

    job_id = (job_id or "").strip()
    if not job_id:
        return RedirectResponse(url="/apply?error=job_not_found", status_code=303)

    try:
        jobs_coll = get_job_collection()
        job = jobs_coll.find_one({"_id": ObjectId(job_id)})
        if not job:
            return RedirectResponse(url="/apply?error=job_not_found", status_code=303)

        apps_coll = get_applications_collection()
        existing = apps_coll.find_one({"user_id": user_id, "job_id": job_id})
        if existing:
            print(f"[applications] already_applied: user_id={user_id!r} job_id={job_id!r}")
            return RedirectResponse(url="/apply?error=already_applied", status_code=303)

        company_id = str(job.get("company_id", ""))
        job_title = job.get("title", "")

        skills_col = get_skills_profile_collection()
        profile_doc = skills_col.find_one({"user_id": user_id}, {"_id": 0})
        applicant_snapshot = {}
        if profile_doc:
            applicant_snapshot = {
                "profile_data": {
                    "Name": profile_doc.get("Name"),
                    "Skills": profile_doc.get("Skills", {}),
                },
                "github_url": profile_doc.get("github_url"),
                "content_hash": profile_doc.get("content_hash"),
            }

        apps_coll.insert_one({
            "user_id": user_id,
            "company_id": company_id,
            "job_id": job_id,
            "job_title": job_title,
            "status": "pending",
            "applied_at": datetime.datetime.utcnow(),
            "applicant_snapshot": applicant_snapshot,
        })
        print(f"[applications] applied: user_id={user_id!r} job_id={job_id!r}")
    except pymongo_errors.DuplicateKeyError:
        print(f"[applications] DuplicateKeyError: user_id={user_id!r} job_id={job_id!r}")
        return RedirectResponse(url="/apply?error=already_applied", status_code=303)
    except Exception as e:
        print(f"[applications] error: {e}")
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


@app.get("/api/jobs/{job_id}/applications")
async def api_job_applications(request: Request, job_id: str):
    """JSON: applications for a job. Recruiter only; job must belong to recruiter's company."""
    if request.session.get("role") != "recruiter" or not request.session.get("company_id"):
        return JSONResponse({"error": "Not authorized."}, status_code=401)
    company_id = request.session["company_id"]
    try:
        job = get_job_collection().find_one({"_id": ObjectId(job_id)})
    except Exception:
        job = None
    if not job or str(job.get("company_id", "")) != company_id:
        return JSONResponse({"error": "Job not found."}, status_code=404)
    try:
        apps = get_applications_collection()
        application_list = list(apps.find({"job_id": job_id}, {"_id": 0}))
    except Exception:
        application_list = []
    skills_coll = get_skills_profile_collection()
    out = []
    for app in application_list:
        applied_at = app.get("applied_at")
        applied_str = applied_at.isoformat() + "Z" if hasattr(applied_at, "isoformat") else str(applied_at) if applied_at else None
        snapshot = app.get("applicant_snapshot") or {}
        profile_data = snapshot.get("profile_data")
        if not profile_data or (not profile_data.get("Skills") and not profile_data.get("Name")):
            user_id = app.get("user_id")
            if user_id:
                profile_doc = skills_coll.find_one({"user_id": user_id}, {"_id": 0, "Name": 1, "Skills": 1, "github_url": 1})
                if profile_doc:
                    snapshot = dict(snapshot)
                    snapshot["profile_data"] = {
                        "Name": profile_doc.get("Name"),
                        "Skills": profile_doc.get("Skills", {}),
                    }
                    if profile_doc.get("github_url") is not None:
                        snapshot["github_url"] = profile_doc.get("github_url")
        out.append({
            "user_id": app.get("user_id"),
            "job_title": app.get("job_title"),
            "status": app.get("status"),
            "applied_at": applied_str,
            "applicant_snapshot": snapshot,
        })
    return JSONResponse({"applications": out})


def _flatten_skills_for_ranking(skills_obj) -> str:
    """Convert nested skills dict to a single string for ranking prompt."""
    if not skills_obj or not isinstance(skills_obj, dict):
        return "No skills listed."
    lines = []
    def walk(obj, prefix=""):
        if isinstance(obj, list) and obj:
            lines.append(prefix + ": " + ", ".join(str(x) for x in obj))
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, prefix + " → " + k if prefix else k)
    walk(skills_obj)
    return "\n".join(lines) if lines else "No skills listed."


@app.post("/api/jobs/{job_id}/rank-applications")
async def api_rank_job_applications(request: Request, job_id: str):
    """Rank applicants by eligibility using Gemini. Recruiter only; returns applications in ranked order."""
    if request.session.get("role") != "recruiter" or not request.session.get("company_id"):
        return JSONResponse({"error": "Not authorized."}, status_code=401)
    company_id = request.session["company_id"]
    try:
        job = get_job_collection().find_one({"_id": ObjectId(job_id)})
    except Exception:
        job = None
    if not job or str(job.get("company_id", "")) != company_id:
        return JSONResponse({"error": "Job not found."}, status_code=404)
    try:
        apps = get_applications_collection()
        application_list = list(apps.find({"job_id": job_id}, {"_id": 0}))
    except Exception:
        application_list = []
    skills_coll = get_skills_profile_collection()
    out = []
    for app in application_list:
        applied_at = app.get("applied_at")
        applied_str = applied_at.isoformat() + "Z" if hasattr(applied_at, "isoformat") else str(applied_at) if applied_at else None
        snapshot = app.get("applicant_snapshot") or {}
        profile_data = snapshot.get("profile_data")
        if not profile_data or (not profile_data.get("Skills") and not profile_data.get("Name")):
            user_id = app.get("user_id")
            if user_id:
                profile_doc = skills_coll.find_one({"user_id": user_id}, {"_id": 0, "Name": 1, "Skills": 1, "github_url": 1})
                if profile_doc:
                    snapshot = dict(snapshot)
                    snapshot["profile_data"] = {
                        "Name": profile_doc.get("Name"),
                        "Skills": profile_doc.get("Skills", {}),
                    }
                    if profile_doc.get("github_url") is not None:
                        snapshot["github_url"] = profile_doc.get("github_url")
        out.append({
            "user_id": app.get("user_id"),
            "job_title": app.get("job_title"),
            "status": app.get("status"),
            "applied_at": applied_str,
            "applicant_snapshot": snapshot or {},
        })

    if not out:
        return JSONResponse({"ranked_applications": []})

    job_title = job.get("title", "")
    job_preview = job.get("preview", "")
    job_qualifications = job.get("qualifications", "")

    candidates = []
    for i, app in enumerate(out):
        snap = app.get("applicant_snapshot") or {}
        profile = snap.get("profile_data") or {}
        name = profile.get("Name") or "Applicant"
        skills_str = _flatten_skills_for_ranking(profile.get("Skills"))
        candidates.append({"index": i, "name": name, "skills": skills_str})

    try:
        ranked_indices = rank_applicants_by_eligibility(
            job_title=job_title,
            job_preview=job_preview,
            job_qualifications=job_qualifications,
            candidates=candidates,
        )
    except Exception as e:
        print(f"[rank-applications] Gemini error: {e}")
        return JSONResponse({"error": "Ranking failed. Please try again."}, status_code=500)

    ranked_out = [out[i] for i in ranked_indices if 0 <= i < len(out)]
    return JSONResponse({"ranked_applications": ranked_out})


@app.get("/applicant/interview-prep", response_class=HTMLResponse)
async def interview_prep_page(request: Request, job_id: str | None = None):
    """Render the interview prep page for a specific applied job."""
    if request.session.get("role") != "applicant" or not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)
    if not job_id:
        return RedirectResponse(url="/applicant/applied-jobs", status_code=303)
    user_id = request.session["user_id"]
    apps = get_applications_collection()
    application = apps.find_one({"user_id": user_id, "job_id": job_id})
    if not application:
        return RedirectResponse(url="/applicant/applied-jobs", status_code=303)
    job_title = application.get("job_title", "")
    return templates.TemplateResponse(
        "interview_prep.html",
        {"request": request, "job_id": job_id, "job_title": job_title},
    )


@app.get("/applicant/interview-prep/result")
async def interview_prep_result(
    request: Request,
    job_id: str | None = None,
    regenerate: str | None = None,
):
    """Return cached script + audio for job_id, or generate and store them. Use regenerate=1 to force regeneration."""
    if request.session.get("role") != "applicant" or not request.session.get("user_id"):
        return JSONResponse({"error": "Not authenticated."}, status_code=401)
    if not job_id:
        return JSONResponse({"error": "job_id is required."}, status_code=400)
    user_id = request.session["user_id"]
    force_regenerate = regenerate in ("1", "true", "yes")

    apps_coll = get_applications_collection()
    application = apps_coll.find_one({"user_id": user_id, "job_id": job_id})
    if not application:
        return JSONResponse({"error": "Application not found."}, status_code=403)

    # Return cached if present and not regenerating
    if not force_regenerate:
        cached_script = application.get("interview_prep_script")
        cached_audio = application.get("interview_prep_audio_base64")
        if cached_script and cached_audio:
            return JSONResponse({"script": cached_script, "audio_base64": cached_audio})

    # Load job details
    try:
        jobs_coll = get_job_collection()
        job = jobs_coll.find_one({"_id": ObjectId(job_id)})
    except Exception:
        job = None
    if not job:
        return JSONResponse({"error": "Job not found."}, status_code=404)

    # Load applicant skills profile
    skills_coll = get_skills_profile_collection()
    profile = skills_coll.find_one({"user_id": user_id})
    applicant_name = ""
    skills_dict = {}
    if profile:
        applicant_name = profile.get("Name", "")
        skills_dict = profile.get("Skills", {})

    # Generate script via Gemini
    try:
        script = generate_interview_script(
            job_title=job.get("title", ""),
            job_preview=job.get("preview", ""),
            job_qualifications=job.get("qualifications", ""),
            applicant_name=applicant_name,
            skills_dict=skills_dict,
        )
    except Exception as exc:
        return JSONResponse({"error": f"Script generation failed: {exc}"}, status_code=502)

    # Generate audio via ElevenLabs
    try:
        audio_base64 = generate_audio_base64(script)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    except Exception as exc:
        return JSONResponse({"error": f"Audio generation failed: {exc}"}, status_code=502)

    # Store in application document for future visits
    apps_coll.update_one(
        {"user_id": user_id, "job_id": job_id},
        {
            "$set": {
                "interview_prep_script": script,
                "interview_prep_audio_base64": audio_base64,
                "interview_prep_generated_at": datetime.datetime.utcnow(),
            }
        },
    )

    return JSONResponse({"script": script, "audio_base64": audio_base64})
