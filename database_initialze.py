from database import get_database

def main():
    """
    Main entry point for the application.
    Currently used to verify the database connection.
    """
    print("Initializing Istanbulsfinest Project...")
    
    db = get_database()
    if db:
        print(f"Ready to work with database: {db.name}")
        # You can add your CV parsing and storage logic here
    else:
        print("Initialization failed. Check your .env file and internet connection.")

if __name__ == "__main__":
    main()
