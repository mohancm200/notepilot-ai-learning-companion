
from functools import wraps

from flask import Blueprint, jsonify, render_template, session
from db import get_db_connection

admin = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Login required"}), 401

        if session.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403

        return func(*args, **kwargs)

    return wrapper


@admin.get("/")
@admin_required
def dashboard():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:

            cursor.execute("SELECT COUNT(*) AS total FROM users")
            total_users = cursor.fetchone()["total"]

            cursor.execute(
                "SELECT COUNT(*) AS total FROM users WHERE is_active = TRUE"
            )
            active_users = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS total FROM notes")
            total_notes = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS total FROM quizzes")
            total_quizzes = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS total FROM flashcards")
            total_flashcards = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT id, name, email, role, is_active, created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT 100
            """)
            users = cursor.fetchall()

            cursor.execute("""
                SELECT
                    activity_logs.id,
                    activity_logs.activity_type,
                    activity_logs.description,
                    activity_logs.created_at,
                    users.name,
                    users.email
                FROM activity_logs
                JOIN users ON users.id = activity_logs.user_id
                ORDER BY activity_logs.created_at DESC
                LIMIT 20
            """)
            activities = cursor.fetchall()

        return render_template(
            "admin_dashboard.html",
            total_users=total_users,
            active_users=active_users,
            total_notes=total_notes,
            total_quizzes=total_quizzes,
            total_flashcards=total_flashcards,
            users=users,
            activities=activities
        )

    finally:
        connection.close()


@admin.post("/users/<int:user_id>/toggle")
@admin_required
def toggle_user(user_id):
    if user_id == session["user_id"]:
        return jsonify({"error": "You cannot deactivate your own account"}), 400

    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT is_active FROM users WHERE id = %s",
                (user_id,)
            )
            user = cursor.fetchone()

            if not user:
                return jsonify({"error": "User not found"}), 404

            new_status = not bool(user["is_active"])

            cursor.execute(
                "UPDATE users SET is_active = %s WHERE id = %s",
                (new_status, user_id)
            )

        connection.commit()

        return jsonify({
            "message": "User status updated",
            "is_active": new_status
        }), 200

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
