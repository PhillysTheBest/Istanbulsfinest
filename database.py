# database.py updates
import os
from pymongo import MongoClient
from dotenv import load_dotenv
import certifi  # <--- Add this import

# Load environment variables
load_dotenv()

mongodb_url = os.getenv("MONGODB_URL")

_client = None

def get_client():
    """Initializes the MongoDB client singleton."""
    global _client
    if _client is None:
        if not mongodb_url:
            raise ValueError("MONGODB_URL not found in .env file")
        
        # Add the tlsCAFile parameter here
        _client = MongoClient(
            mongodb_url, 
            tlsCAFile=certifi.where()
        )
    return _client

# Credentials Database
def get_creds_db():
    """
    Returns the 'Creds' database instance.
    Used for user authentication and login details.
    """
    return get_client()["Creds"] # Ends up being get_client()["Creds"]["Credentials"]

# Credentials Collection
def get_credentials_collection():
    """
    Helper to get the 'Credentials' collection in the 'Creds' database.
    Format: { "user_id": "", "username": "", "password": "", "role": "" }
    Recruiters also have "company_id": "" (str of Jobs.CompanyCollection _id).
    """
    return get_creds_db()["Credentials"]

# Skills Database
def get_skills_db():
    """
    Returns the 'Skills' database instance.
    Used for skill trees, profiles, and matching data.
    """
    return get_client()["Skills"]

# Skills Collection
def get_skills_profile_collection():
    """
    Helper to get the specific 'SkillsProfile' collection directly.
    """
    return get_skills_db()["SkillsProfile"]

# Jobs Database
def get_job_db():
    """
    Returns the 'Jobs' database instance.
    Used for job postings and matching data.
    """
    return get_client()["Jobs"]

# Jobs Collection
def get_job_collection():
    """
    Helper to get the specific 'Jobs' collection directly.
    Schema: { company_id, posted_by (user_id), title, description, created_at }
    """
    return get_job_db()["JobsData"]

# Companies Database
def get_companies_db():
    """
    Returns the 'Companies' database instance.
    Used for company postings and matching data.
    """
    return get_client()["Company"]

# Companies Collection (database = Jobs, collection = CompanyCollection)
def get_companies_collection():
    """
    Companies collection: database = Jobs, collection = CompanyCollection.
    Schema: { _id (ObjectId, auto), name, created_at }.
    Recruiters store company_id (str of this _id) in Credentials.
    """
    return get_job_db()["CompanyCollection"]

# Applications Database
def get_applications_db():
    """
    Returns the 'Applications' database instance.
    Used for application postings and matching data.
    """
    return get_client()["Applications"]

# Applications Collection
def get_applications_collection():
    """
    Helper to get the 'Applications' collection.
    Schema: { applicant_id (user_id), job_id (ObjectId str), status, applied_at, applicant_snapshot }
    Indexes: unique (applicant_id, job_id), job_id, applicant_id
    """
    return get_job_db()["ApplicationsCollection"]



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