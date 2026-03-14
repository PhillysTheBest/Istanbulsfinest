import os
import json
import re
import requests
from bs4 import BeautifulSoup
import PyPDF2

from google import genai
from google.genai import types

# Configure the API keys using environment variables 
api_key = "API-KEY-HERE"
if not api_key:
    raise ValueError("API KEY missing. Suggestion: $env:API_KEY=\"<your_full_key>\"")

client = genai.Client(api_key=api_key)

MODEL_ID = 'gemini-2.5-flash'

def extract_text_from_pdf(pdf_path: str) -> str:
    """Reads a PDF file and extracts its text."""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text = f"{text}{extracted}\n"
            return text
    except FileNotFoundError:
        print(f"Error: Could not find PDF at {pdf_path}")
        return ""
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return ""

def extract_github_url(text: str) -> tuple[str, str]:
    """Uses Regex to find a GitHub profile URL within text."""
    # Matches github.com/username
    pattern = r'(https?://(?:www\.)?github\.com/([A-Za-z0-9_-]+)/?)'
    match = re.search(pattern, text)
    if match:
        return str(match.group(1)), str(match.group(2)) # Returns (URL, Username)
    return "", ""

def scrape_github_profile(username: str) -> str:
    """
    Attempts to scrape a GitHub profile using the official GitHub API.
    Fetches public repositories to aggregate the technologies/languages used.
    """
    if not username:
        return "No GitHub username provided."
        
    print(f"\nAttempting to fetch GitHub repository data for: {username}")
    
    # Optional: If you hit rate limits, you can add a Github Personal Access Token here
    # headers = {'Authorization': f'token {os.environ.get("GITHUB_TOKEN")}'}
    headers = {'Accept': 'application/vnd.github.v3+json'}
    api_endpoint = f"https://api.github.com/users/{username}/repos"
    
    try:
        response = requests.get(api_endpoint, headers=headers, timeout=15)
        
        if response.status_code == 200:
            repos_data = response.json()
            if not isinstance(repos_data, list):
                return f"Unexpected response format for {username}."
            
            repos: list[dict] = repos_data
            if not repos:
                return f"GitHub User {username} has no public repositories."
                
            languages_used: set[str] = set()
            descriptions: list[str] = []
            
            # Tally up the languages and gather descriptions of their work
            for repo in repos:
                # GitHub returns the primary language of the repo
                lang = repo.get('language')
                if lang:
                    languages_used.add(str(lang))
                
                desc = repo.get('description')
                if desc:
                    descriptions.append(str(desc))
                    
            summary = []
            summary.append(f"GitHub Username: {username}")
            if languages_used:
                summary.append(f"Primary Languages Found in Repos: {', '.join(sorted(languages_used))}")
            if descriptions:
                # Using a list comprehension to satisfy pedantic linters regarding slicing
                limited_desc = [descriptions[i] for i in range(min(len(descriptions), 15))]
                summary.append(f"Repository Descriptions:\n- " + "\n- ".join(limited_desc)) # Limit to top 15 desc

            final_text = "\n".join(summary)
            print(f"  -> Successfully fetched GitHub data! Found {len(repos)} repos.")
            return final_text[:4000] # Return safe chunk of text
            
        elif response.status_code == 403: # Rate limited
             print("  -> GitHub API Rate Limit exceeded. If doing bulk processing, add a GITHUB_TOKEN environment variable.")
             return "GitHub API Rate Limited."
        elif response.status_code == 404:
            print(f"  -> GitHub user {username} not found.")
            return "GitHub User not found."
        else:
            print(f"  -> Failed to fetch GitHub profile: Status {response.status_code}")
            return f"Failed: Status {response.status_code}"
            
    except Exception as e:
        print(f"  -> Error scraping GitHub: {e}")
        return ""

def deterministic_format(data):
    """
    Recursively sorts all keys in dictionaries and all items in lists,
    and normalizes strings by stripping whitespace to ensure identical JSON output.
    """
    if isinstance(data, dict):
        return {str(k): deterministic_format(v) for k, v in sorted(data.items())}
    if isinstance(data, list):
        normalized = [str(item).strip() for item in data]
        return sorted(list(set(normalized))) # Deduplicate and sort
    if isinstance(data, str):
        return data.strip()
    return data

def extract_skills_tree(cv_text: str, github_text: str) -> dict:
    if cv_text and github_text:
        combined_info = f"CV Info: {cv_text}\n\nGitHub Info: {github_text}"
    elif cv_text and not github_text:
        combined_info = f"CV Info: {cv_text}"
    elif not cv_text and github_text:
        combined_info = f"GitHub Info: {github_text}"
    else:
        combined_info = "No CV or GitHub text provided."
        
    prompt = f"""
    You are an expert technical recruiter matching candidate skills.
    Extract the candidate's name and a comprehensive "skills tree" from the provided combined CV and GitHub profile snippet.

    CRITICAL RULES FOR CONSISTENCY:
    1. Standardize/Normalize Names: Normalize all skill names (e.g., "ReactJS" -> "React", "NodeJS" -> "Node.js").
    2. STRICT DOMAIN WHITELIST: The top-level "Domain" MUST be exactly one of these strings. DO NOT CREATE NEW ONES:
       [FrontEnd, BackEnd, MachineLearning, MobileApps, DesktopApps, EmbeddedSystems, GameDevelopment, DevOps, DataScience, Design, Maths, Cryptography, Other].
    3. STRICT CATEGORY WHITELIST: The "Specific Category" level MUST be exactly one of these strings:
       [API, Framework, Library, Database, Tool, Concept, Protocol, Service, Other].
    4. Hierarchical Grouping:
       - Level 1 (Key): Domain (from whitelist)
       - Level 2 (Key): Language (e.g., Python, C, Java, JavaScript, Assembly, General)
       - Level 3 (Key): Specific Category (from whitelist)
       - Level 4 (Value): List of strings (Normalized Skills)
    5. ALPHABETICAL SORTING: You MUST sort all keys at every level of the JSON alphabetically.
    6. DETERMINISM: Use the provided text to pick the best fit. If a domain or category is ambiguous, default to 'Other'.
    7. Output Structure: Match this exact JSON schema:

    {{
        "Name": "Name",
        "Skills": {{
            "Domain": {{
                "Language": {{
                    "Specific Category": ["Skill"]
                }}
            }}
        }}
    }}

    Text to analyze:
    {combined_info}
    """

    # 2. GENERATION CONFIG: 
    # Use the new Generation Config structure from `google.genai.types`
    # - `response_mime_type="application/json"` forces Gemini to only output valid JSON (no markdown text).
    # - `temperature=0.1` stops the model from being "creative" and makes the output highly consistent.
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.1,
    )

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=config
        )
        
        # Parse the JSON string into a Python Dictionary
        raw_result = json.loads(response.text)
        
        # Post-process for absolute identity
        # We sort everything and normalize
        if "Skills" in raw_result:
            raw_result["Skills"] = deterministic_format(raw_result["Skills"])
        
        return raw_result
    
    except Exception as e:
        print(f"Error during extraction: {e}")
        return None

# --- Example Usage ---
if __name__ == '__main__':
    # Define the path to the PDF you want to parse
    # Make sure to update this path to a real PDF file on your computer!
    # This now dynamically points to `sample_cv.pdf` in the EXACT SAME FOLDER as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_file_path = os.path.join(script_dir, "sample_cv.pdf")
    
    print(f"Reading CV from '{pdf_file_path}'...")
    
    # 1. Extract text from the PDF
    cv_content = extract_text_from_pdf(pdf_file_path)
    
    if cv_content:
        # 2. Extract GitHub URL/Username from the text
        github_url, github_username = extract_github_url(cv_content)
        
        if github_username:
            print(f"Found GitHub URL: {github_url}")
            # 3. Request GitHub Repo data from official API
            github_content = scrape_github_profile(github_username)
        else:
            print("No GitHub URL found in CV.")
            github_content = "No GitHub URL parsed."

        # 4. Use Gemini to structure the final JSON 
        print("\nSending extracted combined text to Gemini for structured formatting...\n")
        
        # Execute extraction
        result = extract_skills_tree(
            cv_text=cv_content, 
            github_text=github_content
        )
        
        if result:
            print("--- Extracted JSON Skills Tree ---")
            print(json.dumps(result, indent=4))
    else:
        print("Could not process CV. Please check the PDF path. Do you have a file named sample_cv.pdf?")
