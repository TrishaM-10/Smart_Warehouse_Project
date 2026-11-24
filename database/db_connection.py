import mysql.connector
import os
from dotenv import load_dotenv

# Load database credentials from .env
load_dotenv()

def get_db_connection():

    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME")
        )

        return connection

    except mysql.connector.Error as error:
        print("Database Connection Error:", error)
        return None


# Test database connection
if __name__ == "__main__":

    db = get_db_connection()

    if db:
        print("MySQL Database Connected Successfully!")
        db.close()
        print("Connection Closed.")