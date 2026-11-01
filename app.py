
import streamlit as st
import pandas as pd
import requests
import sqlite3
from datetime import datetime, timezone

# ------------------------------------------
# 1. APP SETUP
# ------------------------------------------

st.set_page_config(
    page_title="E-commerce Customer Feedback",
    page_icon="🛍️",
    layout="centered"
)

URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"
DB_PATH = "feedback.db"

ALLOWED = [
    "Product Quality",
    "Delivery",
    "Customer Service",
    "Positive / No Issue",
    "Other / Unclear"
]

# ------------------------------------------
# 2. LABELING GUIDE
# ------------------------------------------

LABELING_GUIDE = """
You classify customer feedback for an online store.

Choose exactly ONE of these labels:

Product Quality:
Complaints about defects, damage, incorrect items,
or poor product performance.

Delivery:
Complaints about shipping delays, missing packages,
or delivery problems.

Customer Service:
Complaints about customer support, communication,
returns, or refunds.

Positive / No Issue:
Satisfaction without a substantive complaint.

Other / Unclear:
Ambiguous feedback, unrelated topics, questions
without feedback, or insufficient information.

Rules:
1. Assign exactly one label.
2. Prioritize substantive complaints over praise.
3. Choose the main complaint when multiple issues appear.
4. If complaints are equally important, use Other / Unclear.
5. Recognize sarcasm.
6. Do not invent information.
7. Return ONLY the exact label.
"""

# ------------------------------------------
# 3. LABEL: CALL GROQ API
# ------------------------------------------

def label_comment(text):
    api_key = st.secrets.get("GROQ-API-KEY", "")

    if not api_key:
        raise RuntimeError("Groq API key is not configured.")

    response = requests.post(
        URL,
        headers={
            "Authorization": f"Bearer {api_key}"
        },
        json={
            "model": MODEL,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": LABELING_GUIDE
                },
                {
                    "role": "user",
                    "content": (
                        "Classify this customer comment:\n"
                        + text
                    )
                }
            ]
        },
        timeout=30
    )

    response.raise_for_status()

    answer = response.json()[
        "choices"
    ][0]["message"]["content"].strip()

    for allowed in ALLOWED:
        if answer.lower() == allowed.lower():
            return allowed

    raise ValueError("LLM returned an invalid label.")

# ------------------------------------------
# 4. CHECK: MANUAL REVIEW RULES
# ------------------------------------------

def check_review(comment, rating, label, error=False):
    reasons = []

    if error:
        reasons.append("Classification could not be verified")

    if label == "Other / Unclear":
        reasons.append("Unclear or unclassified feedback")

    # Preliminary safety screening; not comprehensive.
    safety_terms = [
        "overheat", "smoke", "caught fire",
        "burn", "injur", "electric shock",
        "explod"
    ]

    if comment and any(
        term in comment.lower() for term in safety_terms
    ):
        reasons.append("Possible safety concern")

    # Rating and comment mismatch checks
    if rating is not None and comment:
        if rating <= 2 and label == "Positive / No Issue":
            reasons.append("Low rating conflicts with positive text")

        if rating >= 4 and label in [
            "Product Quality",
            "Delivery",
            "Customer Service"
        ]:
            reasons.append("High rating with complaint")

    # Negative rating without an explanation
    if not comment and rating is not None and rating <= 2:
        reasons.append("Low rating without written feedback")

    return bool(reasons), "; ".join(reasons)

# ------------------------------------------
# 5. COLLECT: SAVE FEEDBACK LOCALLY
# ------------------------------------------

def initialize_database():
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submitted_at TEXT NOT NULL,
                rating INTEGER,
                comment TEXT,
                label TEXT NOT NULL,
                needs_review INTEGER NOT NULL,
                review_reason TEXT,
                classification_error INTEGER NOT NULL
            )
        """)


def save_feedback(
    rating, comment, label,
    needs_review, review_reason,
    classification_error
):
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO feedback (
                submitted_at, rating, comment,
                label, needs_review, review_reason,
                classification_error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                rating,
                comment,
                label,
                int(needs_review),
                review_reason,
                int(classification_error)
            )
        )


initialize_database()

# ------------------------------------------
# 6. CUSTOMER FEEDBACK PAGE
# ------------------------------------------

st.title("🛍️ Customer Feedback")

st.write(
    "We value your feedback! "
    "Please rate your shopping experience "
    "or share a written comment."
)

with st.form("feedback_form", clear_on_submit=True):

    rating = st.selectbox(
        "Star Rating (Optional)",
        options=[None, 1, 2, 3, 4, 5],
        format_func=lambda x: (
            "Select a rating" if x is None
            else f"{x} Star{'s' if x > 1 else ''}"
        )
    )

    comment = st.text_area(
        "Your Comment (Optional)",
        placeholder="Tell us about your experience...",
        max_chars=2000
    )

    submitted = st.form_submit_button(
        "Submit Feedback",
        type="primary"
    )

if submitted:

    comment = comment.strip()

    if rating is None and not comment:
        st.warning(
            "Please provide a star rating "
            "or a written comment."
        )

    else:
        classification_error = False

        if comment:
            try:
                with st.spinner("Analyzing feedback..."):
                    label = label_comment(comment)

            except (requests.RequestException,
                    ValueError, KeyError,
                    IndexError, TypeError,
                    RuntimeError):
                label = "Other / Unclear"
                classification_error = True

        else:
            label = "No Written Comment"

        needs_review, review_reason = check_review(
            comment,
            rating,
            label,
            error=classification_error
        )

        try:
            save_feedback(
                rating,
                comment,
                label,
                needs_review,
                review_reason,
                classification_error
            )
            st.success("Thank you! Your feedback has been saved.")

            if needs_review:
                st.info(
                    "Your feedback has been flagged "
                    "for additional review."
                )

        except sqlite3.Error:
            st.error(
                "Feedback could not be saved. "
                "Please try again."
            )

st.caption(
    "Educational prototype. Please do not submit "
    "personal, financial, or sensitive information."
)
