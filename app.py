from datetime import date, datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, flash
from db import users, expenses

app = Flask(__name__)
app.secret_key = "change-this-later"

CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Other"]
DEMO_EMAIL = "demo@spendwise.com"


def get_demo_user_id():
    user = users.find_one({"email": DEMO_EMAIL})
    if not user:
        raise RuntimeError("Demo user missing. Run: python init_db.py")
    return user["_id"]


def get_user_expenses(user_id):
    return list(
        expenses.find({"user_id": user_id}).sort([("date", -1), ("created_at", -1)])
    )


@app.route("/")
def dashboard():
    all_expenses = get_user_expenses(get_demo_user_id())

    total = sum(e["amount"] for e in all_expenses)

    by_category = {}
    for e in all_expenses:
        by_category[e["category"]] = by_category.get(e["category"], 0) + e["amount"]

    top_category = max(by_category, key=by_category.get) if by_category else "—"

    return render_template(
        "dashboard.html",
        total=total,
        count=len(all_expenses),
        by_category=by_category,
        top_category=top_category,
        recent=all_expenses[:5],
    )


@app.route("/add", methods=["GET", "POST"])
def add_expense():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category")
        exp_date = request.form.get("date")
        notes = request.form.get("notes", "").strip()

        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0

        if not title or amount <= 0:
            flash("Please enter a title and an amount greater than 0.", "error")
            return redirect(url_for("add_expense"))

        expenses.insert_one({
            "user_id": get_demo_user_id(),
            "title": title,
            "amount": amount,
            "category": category,
            "date": exp_date,
            "notes": notes,
            "created_at": datetime.now(timezone.utc),
        })
        flash("Expense added successfully!", "success")
        return redirect(url_for("history"))

    return render_template(
        "add_expense.html",
        categories=CATEGORIES,
        today=date.today().isoformat(),
    )


@app.route("/history")
def history():
    return render_template("history.html", expenses=get_user_expenses(get_demo_user_id()))


if __name__ == "__main__":
    app.run(debug=True)