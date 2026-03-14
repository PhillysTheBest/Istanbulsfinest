import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

_client = None

def get_client():
    """Initializes the MongoDB client singleton."""
    global _client
    if _client is None:
        mongodb_url = os.getenv("MONGODB_URL")
        if not mongodb_url:
            raise ValueError("MONGODB_URL not found in .env file")
        _client = MongoClient(mongodb_url)
    return _client

def get_creds_db():
    """
    Returns the 'Creds' database instance.
    Used for user authentication and login details.
    """
    return get_client()["Creds"]

def get_skills_db():
    """
    Returns the 'Skills' database instance.
    Used for skill trees, profiles, and matching data.
    """
    return get_client()["Skills"]

def get_skills_profile_collection():
    """
    Helper to get the specific 'SkillsProfile' collection directly.
    """
    return get_skills_db()["SkillsProfile"]

def get_credentials_collection():
    """
    Helper to get the 'Credentials' collection in the 'Creds' database.
    Format: { "user_id": "", "username": "", "password": "", "role": "" }
    """
    return get_creds_db()["Credentials"]

# Optional: Helper to close connection (good for scripts)
def close_connection():
    global _client
    if _client:
        _client.close()
        _client = None

if __name__ == "__main__":
    # Test the connection
    try:
        # Test Creds DB
        creds_db = get_creds_db()
        print(f"Connected to Creds DB: {creds_db.name}")
        
        # Test Skills DB
        skills_db = get_skills_db()
        print(f"Connected to Skills DB: {skills_db.name}")
        
        # Test Collection
        col = get_skills_profile_collection()
        print(f"Accessed Collection: {col.name}")
        
        print("\nDatabase structure setup successful!")
        
    except Exception as e:
        print(f"Error: {e}")