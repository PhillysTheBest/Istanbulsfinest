import os
import json
import datetime
import hashlib
from database import get_skills_db, get_skills_profile_collection
from CVScraperJSON import (
    extract_text_from_pdf, 
    extract_github_url, 
    scrape_github_profile, 
    extract_skills_tree,
    deterministic_format
)

# --- UTILITIES ---

def generate_content_hash(data: dict) -> str:
    """Generates a SHA-256 hash of the JSON data for Solana anchoring."""
    # Ensure data is in deterministic format before hashing
    normalized_data = deterministic_format(data)
    body = json.dumps(normalized_data, sort_keys=True)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()

# --- MAIN EXECUTION ---

if __name__ == '__main__':
    print("--- Istanbulsfinest Project Initialization ---")
    
    # 1. Verify DB Connection
    db = get_skills_db()
    if not db:
        print("Initialization failed: Could not connect to MongoDB.")
        exit(1)
    print(f"Database {db.name} connected successfully.")

    # 2. Setup Paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_file_path = os.path.join(script_dir, "sample_cv.pdf")
    
    if not os.path.exists(pdf_file_path):
        print(f"Error: {pdf_file_path} not found. Please add a sample_cv.pdf.")
        exit(1)

    print(f"Processing CV: {pdf_file_path}...")
    
    # 3. Process CV (using imported functions)
    cv_content = extract_text_from_pdf(pdf_file_path)
    github_url, github_username = extract_github_url(cv_content) if cv_content else ("", "")
    github_content = scrape_github_profile(github_username) if github_username else "No GitHub URL parsed."

    # 4. Extract Skills Tree via Gemini
    print("\nSending extracted combined text to Gemini for structured formatting...\n")
    result = extract_skills_tree(cv_content, github_content)
    
    if result:
        print("--- Extracted JSON Skills Tree ---")
        print(json.dumps(result, indent=4))
        
        # 5. Security Anchor (Hashing)
        content_hash = generate_content_hash(result)
        
        # 6. Save to MongoDB
        mongo_document = {
            "user_id": "user_demo_123", # Placeholder
            "content_hash": content_hash,
            "profile_data": result,
            "github_url": github_url,
            "created_at": datetime.datetime.utcnow()
        }
        
        try:
            collection = get_skills_profile_collection()
            insert_result = collection.insert_one(mongo_document)
            print(f"\n[SUCCESS] Profile saved to MongoDB!")
            print(f"  -> Mongo ID: {insert_result.inserted_id}")
            print(f"  -> Content Hash (for Solana): {content_hash}")

            # --- CREDENTIALS SKELETON ---
            # 7. Create Login Credentials Skeleton
            from database import get_credentials_collection
            creds_collection = get_credentials_collection()
            
            # This is a skeleton - we will get this data from the frontend later
            creds_skeleton = {
                "user_id": "user_demo_123", # Matches the mongo_document above
                "username": "candidate_username",
                "password": "hashed_password_here", # Security note: Always hash!
                "role": "applicant"
            }
            
            # Check if it already exists or just insert for demo
            if not creds_collection.find_one({"username": creds_skeleton["username"]}):
                creds_result = creds_collection.insert_one(creds_skeleton)
                print(f"[SUCCESS] Credentials skeleton created!")
                print(f"  -> Creds ID: {creds_result.inserted_id}")

        except Exception as e:
            print(f"\n[ERROR] Failed to save to MongoDB: {e}")
    else:
        print("Extraction failed. Check your Gemini API key and prompt limits.")
