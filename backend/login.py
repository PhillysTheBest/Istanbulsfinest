# Hardcoded credentials
VALID_APPLICANT_USERNAME = "user1"
VALID_APPLICANT_PASSWORD = "password"

VALID_RECRUITER_USERNAME = "recruiter1"
VALID_RECRUITER_PASSWORD = "password"

def validate_credentials(username: str, password: str) -> str | None:
    if username.strip() == VALID_APPLICANT_USERNAME and password == VALID_APPLICANT_PASSWORD:
        return "applicant"
    elif username.strip() == VALID_RECRUITER_USERNAME and password == VALID_RECRUITER_PASSWORD:
        return "recruiter"
    else:
        return None
