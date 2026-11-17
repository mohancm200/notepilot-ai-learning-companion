
import logging
import re
from functools import wraps

import pymysql
from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db_connection

auth = Blueprint("auth", __name__, url_prefix="/auth")

logger = logging.getLogger(__name__)


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Login required"}), 401
        return func(*args, **kwargs)
    return wrapper


def record_activity(cursor, user_id, activity_type, description):
    try:
        cursor.execute(
            """
            INSERT INTO activity_logs
            (user_id, activity_type, description)
            VALUES (%s, %s, %s)
            """,
            (user_id, activity_type, description)
        )
    except pymysql.MySQLError:
        logger.warning("Activity logging unavailable", exc_info=True)


@auth.post("/register")
def register():
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({"error": "All fields are required"}), 400

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify({"error": "Enter a valid email"}), 400

    if len(password) < 8:
        return jsonify({
            "error": "Password must contain at least 8 characters"
        }), 400

    password_hash = generate_password_hash(password)
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (%s, %s, %s, 'user')
                """,
                (name, email, password_hash)
            )

            user_id = cursor.lastrowid

            record_activity(
                cursor,
                user_id,
                "Registration",
                "Created a NotePilot account"
            )

        connection.commit()

        return jsonify({
            "message": "Registration successful. Please login.",
            "user_id": user_id
        }), 201

    except pymysql.err.IntegrityError:
        connection.rollback()
        return jsonify({"error": "Email already registered"}), 409

    except Exception:
        connection.rollback()
        logger.exception("Registration failed")
        return jsonify({"error": "Registration failed"}), 500

    finally:
        connection.close()


@auth.post("/login")
def login():
    data = request.get_json(silent=True) or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, email, password_hash,
                       role, is_active, is_verified
                FROM users
                WHERE email = %s
                """,
                (email,)
            )
            user = cursor.fetchone()

            if not user or not check_password_hash(
                user["password_hash"], password
            ):
                return jsonify({"error": "Invalid email or password"}), 401

            if not user["is_active"]:
                return jsonify({"error": "Your account is deactivated"}), 403

            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["role"] = user["role"]

            record_activity(
                cursor,
                user["id"],
                "Login",
                "Logged into NotePilot"
            )

        connection.commit()

        destination = (
            "/admin/" if user["role"] == "admin" else "/dashboard"
        )

        return jsonify({
            "message": "Login successful",
            "redirect_url": destination,
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "role": user["role"],
                "is_verified": bool(user["is_verified"])
            }
        }), 200

    except Exception:
        connection.rollback()
        logger.exception("Login failed")
        return jsonify({"error": "Unable to login"}), 500

    finally:
        connection.close()


@auth.post("/logout")
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200
