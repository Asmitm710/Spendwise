from datetime import date, datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, flash
from bson.objectid import ObjectId
from bson.errors import InvalidId
from db import users, expenses

app = Flask(__name__)
app.secret_key = "change-this-later"

CATEGORIES = {
    "expense": ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Other"],
    "income": ["Salary", "Freelance", "Business", "Investments", "Gift", "Other"],
}
DEMO_EMAIL = "demo@spendwise.com"
MAX_AMOUNT = 10_000_000


# ---------- Helpers ----------

def get_demo_user_id():
    user = users.find_one({"email": DEMO_EMAIL})
    if not user:
        raise RuntimeError("Demo user missing. Run: python init_db.py")
    return user["_id"]


def parse_object_id(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def normalize(doc):
    """Make a MongoDB document safe and easy to use in templates."""
    doc["id"] = str(doc["_id"])
    doc["type"] = doc.get("type", "expense")  # old Day 2 records
    return doc


def get_user_transactions(user_id, tx_type=None, category=None):
    query = {"user_id": user_id}
    if category:
        query["category"] = category
    items = [
        normalize(d)
        for d in expenses.find(query).sort([("date", -1), ("created_at", -1)])
    ]
    if tx_type in ("income", "expense"):
        items = [i for i in items if i["type"] == tx_type]
    return items


def compute_summary(items):
    income = sum(i["amount"] for i in items if i["type"] == "income")
    expense = sum(i["amount"] for i in items if i["type"] == "expense")
    return income, expense, income - expense


def validate_form(form):
    """Returns (clean_data, errors). If errors is not empty, don't save."""
    errors = []

    tx_type = form.get("type", "expense")
    if tx_type not in CATEGORIES:
        errors.append("Please choose Income or Expense.")
        tx_type = "expense"

    title = form.get("title", "").strip()
    if not title:
        errors.append("Title is required.")
    elif len(title) > 100:
        errors.append("Title must be 100 characters or fewer.")

    amount = 0.0
    try:
        amount = round(float(form.get("amount", "")), 2)
        if amount <= 0:
            errors.append("Amount must be greater than 0.")
        elif amount > MAX_AMOUNT:
            errors.append(f"Amount cannot be more than {MAX_AMOUNT:,}.")
    except ValueError:
        errors.append("Amount must be a valid number.")

    category = form.get("category", "")
    if category not in CATEGORIES[tx_type]:
        errors.append("Please choose a valid category.")

    date_str = form.get("date", "")
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
        if parsed > date.today():
            errors.append("Date cannot be in the future.")
        elif parsed.year < 2000:
            errors.append("Date cannot be before the year 2000.")
    except ValueError:
        errors.append("Please enter a valid date.")

    notes = form.get("notes", "").strip()
    if len(notes) > 300:
        errors.append("Notes must be 300 characters or fewer.")

    data = {
        "type": tx_type,
        "title": title,
        "amount": amount,
        "category": category,
        "date": date_str,
        "notes": notes,
    }
    return data, errors


# ---------- Routes ----------

@app.route("/")
def dashboard():
    items = get_user_transactions(get_demo_user_id())
    income, expense, balance = compute_summary(items)

    by_category = {}
    for i in items:
        if i["type"] == "expense":
            by_category[i["category"]] = by_category.get(i["category"], 0) + i["amount"]

    return render_template(
        "dashboard.html",
        income=income,
        expense=expense,
        balance=balance,
        count=len(items),
        by_category=by_category,
        recent=items[:5],
    )


@app.route("/add", methods=["GET", "POST"])
def add_expense():
    if request.method == "POST":
        data, errors = validate_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "add_expense.html",
                categories=CATEGORIES,
                form=request.form,
                editing=False,
                today=date.today().isoformat(),
            )

        data["user_id"] = get_demo_user_id()
        data["created_at"] = datetime.now(timezone.utc)
        expenses.insert_one(data)
        flash("Transaction added successfully!", "success")
        return redirect(url_for("history"))

    return render_template(
        "add_expense.html",
        categories=CATEGORIES,
        form={"type": "expense", "date": date.today().isoformat()},
        editing=False,
        today=date.today().isoformat(),
    )


@app.route("/history")
def history():
    tx_type = request.args.get("type", "")
    category = request.args.get("category", "")
    items = get_user_transactions(get_demo_user_id(), tx_type, category)
    income, expense, balance = compute_summary(items)

    all_categories = sorted(set(CATEGORIES["expense"] + CATEGORIES["income"]))
    return render_template(
        "history.html",
        expenses=items,
        income=income,
        expense=expense,
        balance=balance,
        all_categories=all_categories,
        selected_type=tx_type,
        selected_category=category,
    )


@app.route("/edit/<expense_id>", methods=["GET", "POST"])
def edit_expense(expense_id):
    oid = parse_object_id(expense_id)
    user_id = get_demo_user_id()
    doc = expenses.find_one({"_id": oid, "user_id": user_id}) if oid else None

    if not doc:
        flash("Transaction not found.", "error")
        return redirect(url_for("history"))

    doc = normalize(doc)

    if request.method == "POST":
        data, errors = validate_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "add_expense.html",
                categories=CATEGORIES,
                form=request.form,
                editing=True,
                expense_id=expense_id,
                today=date.today().isoformat(),
            )

        data["updated_at"] = datetime.now(timezone.utc)
        expenses.update_one({"_id": oid, "user_id": user_id}, {"$set": data})
        flash("Transaction updated!", "success")
        return redirect(url_for("history"))

    return render_template(
        "add_expense.html",
        categories=CATEGORIES,
        form=doc,
        editing=True,
        expense_id=expense_id,
        today=date.today().isoformat(),
    )


@app.route("/delete/<expense_id>", methods=["POST"])
def delete_expense(expense_id):
    oid = parse_object_id(expense_id)
    if oid:
        result = expenses.delete_one({"_id": oid, "user_id": get_demo_user_id()})
        if result.deleted_count:
            flash("Transaction deleted.", "success")
            return redirect(url_for("history"))
    flash("Transaction not found.", "error")
    return redirect(url_for("history"))


if __name__ == "__main__":
    app.run(debug=True)