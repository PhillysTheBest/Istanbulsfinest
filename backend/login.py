import hashlib

from database import get_credentials_collection

# Optional fallback: hardcoded credentials
VALID_APPLICANT_USERNAME = "user1"
VALID_APPLICANT_PASSWORD = "password"
VALID_RECRUITER_USERNAME = "recruiter1"
VALID_RECRUITER_PASSWORD = "password"


def hash_password(password: str) -> str:
    h = hashlib.sha256()
    h.update(password.encode("utf-8"))
    return h.hexdigest()


def validate_credentials(username: str, password: str) -> str | None:
    # Check MongoDB Credentials (users created via signup)
    try:
        creds = get_credentials_collection()
        user = creds.find_one({"username": username.strip()})
        if user and user.get("password") == hash_password(password):
            return user.get("role") or "applicant"
    except Exception as e:
        print(f"Error validating credentials: {e}")
        pass

    if username.strip() == VALID_APPLICANT_USERNAME and password == VALID_APPLICANT_PASSWORD:
        return "applicant"
    if username.strip() == VALID_RECRUITER_USERNAME and password == VALID_RECRUITER_PASSWORD:
        return "recruiter"
    return None
