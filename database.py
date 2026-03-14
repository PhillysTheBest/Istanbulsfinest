import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_database():
    """
    Initializes and returns the MongoDB database connection.
    Uses the MONGODB_URL from the .env file.
    """
    mongodb_url = os.getenv("MONGODB_URL")
    if not mongodb_url:
        raise ValueError("MONGODB_URL not found in .env file")
    
    try:
        # Create a connection using MongoClient
        client = MongoClient(mongodb_url)
        
        # Access the 'CVportal' database
        # (The database name can also be parsed from the URI or set here)
        db = client.get_database("CVportal")
        
        print("Successfully connected to MongoDB Atlas!")
        return db
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")
        return None

if __name__ == "__main__":
    # Test the connection when the script is run directly
    db = get_database()
    if db:
        print(f"Connected to database: {db.name}")
