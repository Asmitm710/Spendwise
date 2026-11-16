import os
import re
import sys
import time
import threading
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo.errors import DuplicateKeyError
from bson.objectid import ObjectId
from bson.errors import InvalidId

from db import client, users, expenses

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY not found. Add it to your .env file.")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
# Render sets the RENDER variable automatically. Locally it doesn't exist.
if os.getenv("RENDER"):
    app.config["SESSION_COOKIE_SECURE"] = True

CATEGORIES = {
    "expense": ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Other"],
    "income": ["Salary", "Freelance", "Business", "Investments", "Gift", "Other"],
}
MAX_AMOUNT = 10_000_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- Helpers ----------

def parse_object_id(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def normalize(doc):
    doc["id"] = str(doc["_id"])
    doc["type"] = doc.get("type", "expense")
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


def last_n_months(n=6):
    """Returns ['2026-06', ..., '2026-11'] ending with the current month."""
    today = date.today()
    y, m = today.year, today.month
    keys = []
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(keys))


def month_label(key):
    return datetime.strptime(key, "%Y-%m").strftime("%b %Y")


def is_safe_next(target):
    """Only allow redirects to pages inside our own site."""
    return bool(target) and target.startswith("/") and not target.startswith("//") and "\\" not in target


def validate_form(form):
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


# ---------- Session handling ----------

@app.before_request
def load_logged_in_user():
    """Runs before every request. Sets g.user to the logged-in user or None."""
    g.user = None
    if request.endpoint == "static":
        return
    uid = session.get("user_id")
    if uid:
        oid = parse_object_id(uid)
        g.user = users.find_one({"_id": oid}) if oid else None
        if g.user is None:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def start_session(user_id):
    session.clear()
    session["user_id"] = str(user_id)
    session.permanent = True


# ---------- Auth routes ----------

@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))

    form = {}
    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        confirm = form.get("confirm", "")

        errors = []
        if len(name) < 2 or len(name) > 50:
            errors.append("Name must be between 2 and 50 characters.")
        if not EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        elif len(password) > 128:
            errors.append("Password must be 128 characters or fewer.")
        elif not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
            errors.append("Password must contain at least one letter and one number.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not errors and users.find_one({"email": email}):
            errors.append("An account with this email already exists.")

        if not errors:
            try:
                result = users.insert_one({
                    "name": name,
                    "email": email,
                    "password_hash": generate_password_hash(password),
                    "created_at": datetime.now(timezone.utc),
                })
            except DuplicateKeyError:
                errors.append("An account with this email already exists.")
            else:
                start_session(result.inserted_id)
                flash(f"Welcome to Spendwise, {name}!", "success")
                return redirect(url_for("dashboard"))

        for e in errors:
            flash(e, "error")

    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))

    next_url = request.values.get("next", "")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = users.find_one({"email": email})
        stored_hash = user.get("password_hash") if user else None

        if stored_hash and check_password_hash(stored_hash, password):
            start_session(user["_id"])
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(next_url if is_safe_next(next_url) else url_for("dashboard"))

        # Same message for wrong email and wrong password, on purpose
        flash("Invalid email or password.", "error")
        return render_template("login.html", email=email, next=next_url)

    return render_template("login.html", email="", next=next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------- App routes (all require login) ----------

@app.route("/")
@login_required
def dashboard():
    items = get_user_transactions(g.user["_id"])
    income, expense, balance = compute_summary(items)

    # Category-wise chart data (expenses only)
    by_category = {}
    for i in items:
        if i["type"] == "expense":
            by_category[i["category"]] = by_category.get(i["category"], 0) + i["amount"]
    sorted_cats = sorted(by_category.items(), key=lambda kv: -kv[1])
    category_labels = [c for c, _ in sorted_cats]
    category_values = [round(v, 2) for _, v in sorted_cats]

    # Monthly chart data (last 6 months)
    month_keys = last_n_months(6)
    monthly_income = dict.fromkeys(month_keys, 0)
    monthly_expense = dict.fromkeys(month_keys, 0)
    for i in items:
        key = str(i.get("date", ""))[:7]
        if key in monthly_income:
            if i["type"] == "income":
                monthly_income[key] += i["amount"]
            else:
                monthly_expense[key] += i["amount"]

    return render_template(
        "dashboard.html",
        income=income,
        expense=expense,
        balance=balance,
        count=len(items),
        recent=items[:5],
        category_labels=category_labels,
        category_values=category_values,
        month_labels=[month_label(k) for k in month_keys],
        monthly_income=[round(monthly_income[k], 2) for k in month_keys],
        monthly_expense=[round(monthly_expense[k], 2) for k in month_keys],
    )


@app.route("/add", methods=["GET", "POST"])
@login_required
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

        data["user_id"] = g.user["_id"]
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
@login_required
def history():
    tx_type = request.args.get("type", "")
    category = request.args.get("category", "")
    items = get_user_transactions(g.user["_id"], tx_type, category)
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
@login_required
def edit_expense(expense_id):
    oid = parse_object_id(expense_id)
    user_id = g.user["_id"]
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
@login_required
def delete_expense(expense_id):
    oid = parse_object_id(expense_id)
    if oid:
        result = expenses.delete_one({"_id": oid, "user_id": g.user["_id"]})
        if result.deleted_count:
            flash("Transaction deleted.", "success")
            return redirect(url_for("history"))
    flash("Transaction not found.", "error")
    return redirect(url_for("history"))

# ---------- Health check and monitoring ----------

START_TIME = time.time()
stats = {"requests": 0, "errors": 0}
stats_lock = threading.Lock()


@app.after_request
def count_requests(response):
    """Counts every page visit (not static files or health checks)."""
    if request.endpoint not in ("static", "health"):
        with stats_lock:
            stats["requests"] += 1
            if response.status_code >= 500:
                stats["errors"] += 1
    return response


def check_database():
    """Returns (is_connected, response_time_in_ms)."""
    start = time.perf_counter()
    try:
        client.admin.command("ping")
        ok = True
    except Exception:
        ok = False
    return ok, round((time.perf_counter() - start) * 1000)


@app.route("/health")
def health():
    """Fast liveness check for Render. No database call, so it answers instantly."""
    return {"status": "ok"}, 200


@app.route("/status")
@login_required
def status():
    """Simple monitoring page for logged-in users."""
    db_ok, latency = check_database()
    seconds = int(time.time() - START_TIME)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)

    info = [
        ("App status", "Running"),
        ("Database", "Connected" if db_ok else "Unreachable"),
        ("Database response time", f"{latency} ms"),
        ("Uptime since last start", f"{hours}h {minutes}m {secs}s"),
        ("Page requests since start", stats["requests"]),
        ("Server errors since start", stats["errors"]),
        ("Python version", sys.version.split()[0]),
        ("Server time (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        ("Your transactions", expenses.count_documents({"user_id": g.user["_id"]})),
    ]
    return render_template("status.html", info=info, db_ok=db_ok)
if __name__ == "__main__":
    app.run(debug=True)