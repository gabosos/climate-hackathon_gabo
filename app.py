from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Generator

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["DATABASE"] = os.environ.get(
    "FOODWISE_DATABASE", str(Path(app.instance_path) / "foodwise.sqlite3")
)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("HTTPS_ONLY") == "1"

UNITS = {"unidad", "kg", "g", "L", "ml", "paquete"}
CATEGORIES = {"Frutas", "Verduras", "Lácteos", "Proteínas", "Despensa", "Otros"}


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    database = Path(app.config["DATABASE"])
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_db() -> None:
    with get_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS foods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                quantity REAL NOT NULL CHECK (quantity > 0),
                unit TEXT NOT NULL,
                expires_on TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available'
                    CHECK (status IN ('available', 'used', 'wasted')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(foods)")
        }
        if "user_id" not in columns:
            connection.execute(
                "ALTER TABLE foods ADD COLUMN user_id INTEGER REFERENCES users(id)"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS foods_user_status ON foods(user_id, status)"
        )


def ensure_secret_key() -> None:
    if app.config["SECRET_KEY"]:
        return
    secret_path = Path(app.instance_path) / "secret_key"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if not secret_path.exists():
        try:
            with secret_path.open("x", encoding="utf-8") as secret_file:
                secret_file.write(secrets.token_hex(32))
            secret_path.chmod(0o600)
        except FileExistsError:
            pass
    app.config["SECRET_KEY"] = secret_path.read_text(encoding="utf-8").strip()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if not isinstance(user_id, int):
            return error_response("Inicia sesión para continuar.", 401)
        with get_db() as connection:
            user = connection.execute(
                "SELECT id, name, email FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if user is None:
            session.clear()
            return error_response("Inicia sesión para continuar.", 401)
        g.current_user = user
        return view(*args, **kwargs)

    return wrapped


def food_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    expiry = date.fromisoformat(item["expires_on"])
    days_left = (expiry - date.today()).days
    item["days_left"] = days_left
    item["urgency"] = "expired" if days_left < 0 else "soon" if days_left <= 3 else "fresh"
    return item


def error_response(message: str, status: int = 400):
    return jsonify({"error": message}), status


@app.route("/")
def home():
    return render_template("index.html")


@app.get("/api/session")
def current_session():
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return jsonify({"user": None})
    with get_db() as connection:
        user = connection.execute(
            "SELECT id, name, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if user is None:
        session.clear()
        return jsonify({"user": None})
    return jsonify({"user": dict(user)})


@app.post("/api/register")
def register():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("Envía los datos de registro en formato JSON.")
    name = payload.get("name")
    email = payload.get("email")
    password = payload.get("password")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        return error_response("Escribe tu nombre (máximo 80 caracteres).")
    if not isinstance(email, str) or len(email.strip()) > 254:
        return error_response("Escribe un correo electrónico válido.")
    normalized_email = email.strip().casefold()
    if (
        normalized_email.count("@") != 1
        or any(character.isspace() for character in normalized_email)
        or "." not in normalized_email.rsplit("@", 1)[1]
    ):
        return error_response("Escribe un correo electrónico válido.")
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        return error_response("La contraseña debe tener entre 8 y 128 caracteres.")

    try:
        with get_db() as connection:
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name.strip(), normalized_email, generate_password_hash(password)),
            )
            user_id = cursor.lastrowid
            connection.execute(
                "UPDATE foods SET user_id = ? WHERE user_id IS NULL", (user_id,)
            )
    except sqlite3.IntegrityError:
        return error_response("Ya existe una cuenta con ese correo.", 409)

    session.clear()
    session["user_id"] = user_id
    return jsonify(
        {"user": {"id": user_id, "name": name.strip(), "email": normalized_email}}
    ), 201


@app.post("/api/login")
def login():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("Envía tu correo y contraseña en formato JSON.")
    email = payload.get("email")
    password = payload.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return error_response("El correo y la contraseña son obligatorios.")
    with get_db() as connection:
        user = connection.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email.strip().casefold(),),
        ).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return error_response("Correo o contraseña incorrectos.", 401)
    session.clear()
    session["user_id"] = user["id"]
    return jsonify(
        {"user": {"id": user["id"], "name": user["name"], "email": user["email"]}}
    )


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"logged_out": True})


@app.get("/api/dashboard")
@login_required
def dashboard():
    with get_db() as connection:
        active = connection.execute(
            """
            SELECT * FROM foods
            WHERE user_id = ? AND status = 'available'
            ORDER BY expires_on, name
            """,
            (g.current_user["id"],),
        ).fetchall()
        used = connection.execute(
            "SELECT COUNT(*) FROM foods WHERE user_id = ? AND status = 'used'",
            (g.current_user["id"],),
        ).fetchone()[0]
        wasted = connection.execute(
            "SELECT COUNT(*) FROM foods WHERE user_id = ? AND status = 'wasted'",
            (g.current_user["id"],),
        ).fetchone()[0]

    foods = [food_to_dict(row) for row in active]
    urgent_count = sum(item["days_left"] <= 3 for item in foods)
    return jsonify(
        {
            "foods": foods,
            "stats": {
                "active": len(foods),
                "urgent": urgent_count,
                "used": used,
                "wasted": wasted,
            },
        }
    )


@app.post("/api/foods")
@login_required
def add_food():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("Envía los datos del alimento en formato JSON.")

    name = payload.get("name")
    category = payload.get("category")
    unit = payload.get("unit")
    expires_on = payload.get("expires_on")
    quantity = payload.get("quantity")

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        return error_response("Escribe un nombre de hasta 80 caracteres.")
    if not isinstance(category, str) or category not in CATEGORIES:
        return error_response("Selecciona una categoría válida.")
    if not isinstance(unit, str) or unit not in UNITS:
        return error_response("Selecciona una unidad válida.")
    if isinstance(quantity, bool):
        return error_response("La cantidad debe ser un número mayor que cero.")
    try:
        amount = float(quantity)
    except (TypeError, ValueError):
        return error_response("La cantidad debe ser un número mayor que cero.")
    if not 0 < amount <= 100000:
        return error_response("La cantidad debe ser mayor que cero y no superar 100 000.")
    try:
        expiry = date.fromisoformat(expires_on)
    except (TypeError, ValueError):
        return error_response("Indica una fecha de vencimiento válida.")
    if expiry < date.today() - timedelta(days=3650):
        return error_response("La fecha ingresada no es válida.")

    with get_db() as connection:
        cursor = connection.execute(
            """
            INSERT INTO foods (user_id, name, category, quantity, unit, expires_on)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (g.current_user["id"], name.strip(), category, amount, unit, expiry.isoformat()),
        )
        row = connection.execute(
            "SELECT * FROM foods WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return jsonify(food_to_dict(row)), 201


@app.patch("/api/foods/<int:food_id>")
@login_required
def update_food(food_id: int):
    payload = request.get_json(silent=True)
    status = payload.get("status") if isinstance(payload, dict) else None
    if not isinstance(status, str) or status not in {"used", "wasted"}:
        return error_response("La acción debe ser 'used' o 'wasted'.")

    with get_db() as connection:
        cursor = connection.execute(
            """
            UPDATE foods SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND status = 'available'
            """,
            (status, food_id, g.current_user["id"]),
        )
        if cursor.rowcount == 0:
            exists = connection.execute(
                "SELECT 1 FROM foods WHERE id = ? AND user_id = ?",
                (food_id, g.current_user["id"]),
            ).fetchone()
            if exists:
                return error_response("Este alimento ya fue registrado.", 409)
            return error_response("No encontramos ese alimento.", 404)
    return jsonify({"id": food_id, "status": status})


@app.delete("/api/foods/<int:food_id>")
@login_required
def delete_food(food_id: int):
    with get_db() as connection:
        cursor = connection.execute(
            """
            DELETE FROM foods
            WHERE id = ? AND user_id = ? AND status = 'available'
            """,
            (food_id, g.current_user["id"]),
        )
    if cursor.rowcount == 0:
        return error_response("No encontramos ese alimento en tu despensa.", 404)
    return jsonify({"deleted": food_id})


@app.get("/api/ideas")
@login_required
def recipe_ideas():
    with get_db() as connection:
        foods = connection.execute(
            "SELECT name FROM foods WHERE user_id = ? AND status = 'available'",
            (g.current_user["id"],),
        ).fetchall()
    names = [row["name"] for row in foods]
    recipes = [
        {
            "title": "Salteado salvavidas",
            "description": "Dora tus verduras con un poco de aceite y sírvelas con arroz, pasta o huevo.",
            "matches": [
                name for name in names
                if any(word in name.casefold() for word in ("tomate", "cebolla", "pimiento", "calabac", "zanahoria", "espinaca"))
            ],
            "icon": "🥘",
        },
        {
            "title": "Fruta lista para compartir",
            "description": "Combina la fruta madura en un bowl, licuado o compota para aprovecharla hoy.",
            "matches": [
                name for name in names
                if any(word in name.casefold() for word in ("plátano", "banana", "manzana", "pera", "fresa", "mango", "fruta"))
            ],
            "icon": "🍓",
        },
        {
            "title": "Tostada sin desperdicio",
            "description": "Aprovecha pan y acompáñalo con queso, huevo o las verduras que tengas.",
            "matches": [
                name for name in names
                if any(word in name.casefold() for word in ("pan", "queso", "huevo", "aguacate"))
            ],
            "icon": "🍞",
        },
    ]
    for recipe in recipes:
        recipe["matches"] = recipe["matches"][:4]
    return jsonify({"recipes": recipes, "has_food": bool(names)})


@app.get("/api/history")
@login_required
def history():
    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT id, name, category, quantity, unit, status, updated_at
            FROM foods
            WHERE user_id = ? AND status IN ('used', 'wasted')
            ORDER BY updated_at DESC LIMIT 20
            """,
            (g.current_user["id"],),
        ).fetchall()
    return jsonify({"events": [dict(row) for row in rows]})


ensure_secret_key()
initialize_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
