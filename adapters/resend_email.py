"""Email delivery via Resend (free tier). No-op unless configured.

Env: RESEND_API_KEY, REPORT_EMAIL_TO (required to send),
     REPORT_EMAIL_FROM (optional; Resend's onboarding sender by default).

Failures are reported as a reason string rather than silently returning
False — a missing variable and a rejected send look identical otherwise,
and neither is visible in the daily log.
"""

from __future__ import annotations

import os

import requests

DEFAULT_FROM = "Quant PM <onboarding@resend.dev>"


def send_email(subject: str, markdown_body: str) -> tuple[bool, str]:
    """Returns (sent, reason). Reason is safe to log — it never holds the key."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    to = os.environ.get("REPORT_EMAIL_TO", "").strip()

    missing = [
        name
        for name, value in (("RESEND_API_KEY", api_key), ("REPORT_EMAIL_TO", to))
        if not value
    ]
    if missing:
        return False, f"{', '.join(missing)} not set"

    sender = os.environ.get("REPORT_EMAIL_FROM", "").strip() or DEFAULT_FROM
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": sender, "to": [to], "subject": subject, "text": markdown_body},
        timeout=30,
    )
    if resp.status_code >= 400:
        # Resend's error bodies explain the rejection (e.g. the onboarding
        # sender may only mail the account owner until a domain is verified)
        # and contain no credentials, so they are safe to surface.
        return False, f"Resend HTTP {resp.status_code}: {resp.text[:300]}"
    return True, "sent"
