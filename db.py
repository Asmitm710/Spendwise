import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI not found. Check your .env file.")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

db = client["spendwise"]     # database name
users = db["users"]           # users collection
expenses = db["expenses"]     # expenses collection