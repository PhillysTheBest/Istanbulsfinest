# Hardcoded credentials
VALID_USERNAME = "user1"
VALID_PASSWORD = "password"


def validate_credentials(username: str, password: str) -> bool:
    return username.strip() == VALID_USERNAME and password == VALID_PASSWORD
