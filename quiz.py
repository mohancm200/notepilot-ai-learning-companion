import os
import json
import logging
import urllib.request
import urllib.error

from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from db import get_db_connection

quiz_bp = Blueprint("quiz_bp", __name__, url_prefix="/quiz")
logger = logging.getLogger(__name__)

GEMINI_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-flash-latest"
]


def student_id():
    if "user_id" not in session or session.get("role") != "user":
        return None
    return session["user_id"]


def generate_quiz_questions(study_material, number_of_questions=10):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from .env.")

    prompt = f"""
Create exactly {number_of_questions} multiple-choice questions using ONLY the study material below.
Return ONLY valid JSON in this exact structure:
{{
  "questions": [
    {{
      "question": "Question text",
      "options": {{
        "A": "Option A",
        "B": "Option B",
        "C": "Option C",
        "D": "Option D"
      }},
      "correct_answer": "A",
      "explanation": "Short explanation based on the study material"
    }}
  ]
}}
Rules:
- Exactly {number_of_questions} questions.
- Four options labelled A, B, C, D for every question.
- correct_answer must be exactly one of A, B, C, D.
- Avoid duplicate questions.
- Do not use information absent from the study material.
- Explanations should be concise.
STUDY MATERIAL:
{study_material[:24000]}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.25, "responseMimeType": "application/json"}
    }
    errors = []

    for model in GEMINI_MODELS:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))

            candidates = result.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned no candidates.")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts or not parts[0].get("text"):
                raise ValueError("Gemini returned an empty response.")

            raw = parts[0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(raw)
            questions = parsed.get("questions")

            if not isinstance(questions, list) or len(questions) != number_of_questions:
                raise ValueError(f"Expected exactly {number_of_questions} questions.")

            cleaned = []
            for item in questions:
                options = item.get("options", {})
                answer = str(item.get("correct_answer", "")).strip().upper()
                question_text = str(item.get("question", "")).strip()
                if (
                    not question_text
                    or not isinstance(options, dict)
                    or any(not str(options.get(letter, "")).strip() for letter in "ABCD")
                    or answer not in "ABCD"
                ):
                    raise ValueError("Gemini returned an invalid question or options.")
                cleaned.append({
                    "question": question_text,
                    "options": {letter: str(options[letter]).strip() for letter in "ABCD"},
                    "correct_answer": answer,
                    "explanation": str(item.get("explanation", "")).strip()
                })
            return cleaned

        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            logger.error("Quiz Gemini HTTP %s on %s: %s", error.code, model, detail)
            errors.append(f"{model}: HTTP {error.code}")
        except Exception as error:
            logger.exception("Quiz generation failed on model %s", model)
            errors.append(f"{model}: {error}")

    raise RuntimeError("Could not generate quiz. " + " | ".join(errors))


@quiz_bp.get("/")
def index():
    uid = student_id()
    if uid is None:
        return redirect(url_for("login_page"))

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, created_at FROM notes WHERE user_id=%s ORDER BY created_at DESC",
                (uid,)
            )
            notes = cursor.fetchall()

            cursor.execute(
                """
                SELECT qa.id, qa.score, qa.total_questions, qa.attempted_at,
                       q.note_id, n.title AS note_title
                FROM quiz_attempts qa
                JOIN quizzes q ON q.id = qa.quiz_id
                JOIN notes n ON n.id = q.note_id
                WHERE qa.user_id = %s
                ORDER BY qa.attempted_at DESC
                LIMIT 20
                """,
                (uid,)
            )
            attempts = cursor.fetchall()

        return render_template("quiz.html", notes=notes, attempts=attempts)
    finally:
        connection.close()


@quiz_bp.post("/generate/<int:note_id>")
def generate(note_id):
    uid = student_id()
    if uid is None:
        return redirect(url_for("login_page"))

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, source_text FROM notes WHERE id=%s AND user_id=%s",
                (note_id, uid)
            )
            note = cursor.fetchone()

        if not note:
            flash("Note not found or you do not have access to it.", "error")
            return redirect(url_for("quiz_bp.index"))

        if not (note.get("source_text") or "").strip():
            flash("This note has no study material for quiz generation.", "error")
            return redirect(url_for("quiz_bp.index"))

        questions = generate_quiz_questions(note["source_text"], 10)

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quizzes (note_id, questions_json) VALUES (%s, %s)",
                (note_id, json.dumps(questions, ensure_ascii=False))
            )
            quiz_id = cursor.lastrowid
        connection.commit()

        return redirect(url_for("quiz_bp.take_quiz", quiz_id=quiz_id))

    except Exception as error:
        connection.rollback()
        logger.exception("Could not create quiz for note %s", note_id)
        flash(f"Quiz generation failed: {error}", "error")
        return redirect(url_for("quiz_bp.index"))
    finally:
        connection.close()


@quiz_bp.get("/take/<int:quiz_id>")
def take_quiz(quiz_id):
    uid = student_id()
    if uid is None:
        return redirect(url_for("login_page"))

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.id, q.questions_json, n.title AS note_title
                FROM quizzes q
                JOIN notes n ON n.id = q.note_id
                WHERE q.id=%s AND n.user_id=%s
                """,
                (quiz_id, uid)
            )
            quiz = cursor.fetchone()

        if not quiz:
            flash("Quiz not found or you do not have access.", "error")
            return redirect(url_for("quiz_bp.index"))

        questions = json.loads(quiz["questions_json"])
        # Never send correct answers or explanations to the browser before submission.
        public_questions = [
            {
                "question": item["question"],
                "options": item["options"]
            }
            for item in questions
        ]
        return render_template(
            "quiz_take.html",
            quiz_id=quiz_id,
            note_title=quiz["note_title"],
            questions=public_questions
        )
    except Exception:
        logger.exception("Unable to open quiz %s", quiz_id)
        flash("Unable to open this quiz.", "error")
        return redirect(url_for("quiz_bp.index"))
    finally:
        connection.close()


@quiz_bp.post("/submit/<int:quiz_id>")
def submit_quiz(quiz_id):
    uid = student_id()
    if uid is None:
        return redirect(url_for("login_page"))

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.id, q.questions_json, n.title AS note_title
                FROM quizzes q
                JOIN notes n ON n.id = q.note_id
                WHERE q.id=%s AND n.user_id=%s
                """,
                (quiz_id, uid)
            )
            quiz = cursor.fetchone()

        if not quiz:
            flash("Quiz not found or you do not have access.", "error")
            return redirect(url_for("quiz_bp.index"))

        questions = json.loads(quiz["questions_json"])
        score = 0
        answers = []

        for index, question in enumerate(questions):
            selected = request.form.get(f"q{index}", "").strip().upper()
            correct = str(question.get("correct_answer", "")).strip().upper()
            is_correct = selected == correct and selected in "ABCD"
            if is_correct:
                score += 1
            answers.append({
                "question": question["question"],
                "selected": selected if selected in "ABCD" else "",
                "correct_answer": correct,
                "options": question["options"],
                "explanation": question.get("explanation", ""),
                "is_correct": is_correct
            })

        total = len(questions)
        percentage = round((score / total) * 100, 1) if total else 0

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO quiz_attempts (quiz_id, user_id, score, total_questions)
                VALUES (%s, %s, %s, %s)
                """,
                (quiz_id, uid, score, total)
            )
            attempt_id = cursor.lastrowid
        connection.commit()

        return render_template(
            "quiz_result.html",
            note_title=quiz["note_title"],
            score=score,
            total=total,
            percentage=percentage,
            answers=answers,
            attempt_id=attempt_id
        )
    except Exception:
        connection.rollback()
        logger.exception("Quiz submission failed for quiz %s", quiz_id)
        flash("Could not submit your quiz. Please try again.", "error")
        return redirect(url_for("quiz_bp.index"))
    finally:
        connection.close()
