from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "change-this-later"

CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Other"]

# Temporary storage. Data is lost when the server restarts.
# A real database comes on Day 2.
expenses = []


@app.route("/")
def dashboard():
    total = sum(e["amount"] for e in expenses)

    by_category = {}
    for e in expenses:
        by_category[e["category"]] = by_category.get(e["category"], 0) + e["amount"]

    top_category = max(by_category, key=by_category.get) if by_category else "—"
    recent = list(reversed(expenses))[:5]

    return render_template(
        "dashboard.html",
        total=total,
        count=len(expenses),
        by_category=by_category,
        top_category=top_category,
        recent=recent,
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

        expenses.append({
            "title": title,
            "amount": amount,
            "category": category,
            "date": exp_date,
            "notes": notes,
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
    return render_template("history.html", expenses=list(reversed(expenses)))


if __name__ == "__main__":
    app.run(debug=True)