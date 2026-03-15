import json
import hashlib

def generate_skill_hash(skill_tree_dict: dict) -> str:
    """
    Deterministically serializes the Skill Tree JSON (sorted keys) 
    and returns a SHA-256 hex string.
    """
    if not skill_tree_dict:
        return ""
        
    # Standardize JSON: sort keys and remove unnecessary whitespace
    # This ensures that the same data always results in the same hash.
    standardized_json = json.dumps(
        skill_tree_dict, 
        sort_keys=True, 
        separators=(',', ':')
    )
    
    # Generate SHA-256 hash
    return hashlib.sha256(standardized_json.encode('utf-8')).hexdigest()

if __name__ == "__main__":
    # Test
    test_tree = {
        "Name": "Phil",
        "Skills": {
            "BackEnd": {
                "Python": {
                    "Framework": ["FastAPI"]
                }
            }
        }
    }
    h1 = generate_skill_hash(test_tree)
    h2 = generate_skill_hash(test_tree)
    print(f"Hash: {h1}")
    assert h1 == h2, "Hashing is not deterministic!"
