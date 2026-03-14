import os
import json
from google import genai
from google.genai import types

# DO NOT COMMIT THIS FILE WITH YOUR REAL API KEY EXPOSED
api_key = "enter API Key"
client = genai.Client(api_key=api_key)

MODEL_ID = 'gemini-2.5-flash' 

def extract_skills_tree(cv_text: str, linkedin_text: str) -> dict:
    """
    Takes CV and LinkedIn text and uses Gemini to extract a hierarchical, 
    normalized JSON skills tree.
    """
    
    combined_info = f"CV Info: {cv_text}\n\nLinkedIn Info: {linkedin_text}"
    
    prompt = f"""
    You are an expert technical recruiter matching candidate skills.
    Extract the candidate's name and a comprehensive "skills tree" from the provided combined CV and LinkedIn profile.

    CRITICAL RULES FOR CONSISTENCY:
    1. Standardize/Normalize Names: You MUST normalize all skill names to their most common, official industry standard to ensure different candidates can be matched. 
       (e.g., "ReactJS" or "React.js" -> "React", "NodeJS" -> "Node.js", "ML" -> "Machine Learning", "k8s" -> "Kubernetes").
    2. Hierarchical Grouping:
       - The top-level Category MUST ALWAYS describe the broad Domain (e.g., FrontEnd, BackEnd, MachineLearning, Maths, Cryptography, Embedded Systems, Mobile Apps, Desktop Apps, Game Development).
       - The second-level Subcategory MUST ALWAYS be the Language (e.g., Python, Java, C++, JavaScript). If the skill is genuinely language-agnostic, use a broad category like 'Tooling' or 'General'.
       - The third-level MUST describe the Specific Category (e.g., API, Framework, Library, Database).
       - Inside the Specific Category, list the specific skills, libraries, frameworks, or APIs as an array.
    3. Output Structure: Do not invent obscure categories or use inconsistent keys. Keep the taxonomy strict to the rule above.

    The output MUST match this exact JSON structure outline:
    {{
        "Name": "(Extracted Name from profile or CV)",
        "Skills": {{
            "(Domain - e.g., BackEnd)": {{
                "(Language - e.g., Python)": {{
                    "(Specific Category - e.g., API)": [
                        "(NormalizedSkill1 - e.g., FastAPI)"
                    ],
                    "(Specific Category - e.g., Framework)": [
                         "(NormalizedSkill2 - e.g., Django)"
                    ]
                }},
                "(Language - e.g., Java)": {{
                      "(Specific Category - e.g., Framework)": [
                          "(NormalizedSkill - e.g., Spring Boot)"
                      ]
                }}
            }},
            "(Domain - e.g., MachineLearning)": {{
                "(Language - e.g., Python)": {{
                    "(Specific Category - e.g., Framework)": [
                        "(NormalizedSkill - e.g., PyTorch)"
                    ],
                    "(Specific Category - e.g., Library)": [
                        "(NormalizedSkill - e.g., scikit-learn)"
                    ]
                }}
            }}
        }}
    }}

    Text to analyze:
    {combined_info}
    """

    #2 GENERATION CONFIG - low temperature, higher consistency, JSON output
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
        
        # Parse JSON string into Python Dictionary
        return json.loads(response.text)
    
    except Exception as e:
        print(f"Error during extraction: {e}")
        return None

# Example
if __name__ == '__main__':
    
    sample_cv = "CV - Phil Smith\nI'm a backend dev. I write Python mainly, using FastAPI, Django, and NumPy for maths. I also know Java and Spring Boot."
    sample_linkedin = "Endorsement: AWS, Docker, Kubernetes(k8s) and Microservices."
    
    print("Sending request to Gemini...\n")
    if api_key:
        result = extract_skills_tree(
            cv_text=sample_cv, 
            linkedin_text=sample_linkedin
        )
        
        if result:
            print("--- Extracted JSON Skills Tree ---")
            print(json.dumps(result, indent=4))
    else:
        print("Please set your api_key variable to run the API.")
