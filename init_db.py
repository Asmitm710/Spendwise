from datetime import datetime, timezone
from db import db, users, expenses

# 1. Create collections if they don't exist
existing = db.list_collection_names()
for name in ["users", "expenses"]:
    if name not in existing:
        db.create_collection(name)
        print("Created collection:", name)
    else:
        print("Already exists:", name)

# 2. Indexes (rules + speed)
users.create_index("email", unique=True)              # no duplicate emails
expenses.create_index([("user_id", 1), ("date", -1)]) # fast lookups

# 3. Demo user
if not users.find_one({"email": "demo@spendwise.com"}):
    users.insert_one({
        "name": "Demo User",
        "email": "demo@spendwise.com",
        "created_at": datetime.now(timezone.utc),
    })
    print("Demo user created.")
else:
    print("Demo user already exists.")

print("Collections now:", db.list_collection_names())