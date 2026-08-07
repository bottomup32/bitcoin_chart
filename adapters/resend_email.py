"""Email delivery via Resend (free tier). No-op unless configured.

Env: RESEND_API_KEY, REPORT_EMAIL_TO (required to send),
     REPORT_EMAIL_FROM (optional; Resend's onboarding sender by default).
"""

from __future__ import annotations

import os

import requests


def send_email(subject: str, markdown_body: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("REPORT_EMAIL_TO")
    if not api_key or not to:
        return False
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": os.environ.get("REPORT_EMAIL_FROM", "Quant PM <onboarding@resend.dev>"),
            "to": [to],
            "subject": subject,
            "text": markdown_body,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return True
