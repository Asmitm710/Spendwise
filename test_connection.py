from db import client, db

try:
    client.admin.command("ping")
    print("SUCCESS: Connected to MongoDB Atlas!")
    print("Database:", db.name)
    print("Collections:", db.list_collection_names())
except Exception as e:
    print("FAILED to connect:")
    print(e)