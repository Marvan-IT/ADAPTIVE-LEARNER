"""
Email utility for sending OTP codes.

In development (SMTP_HOST not set), the OTP is logged to the console so
developers can test the flow without configuring an SMTP server.
In production, emails are sent via SMTP with STARTTLS.
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

logger = logging.getLogger(__name__)


async def send_otp_email(to_email: str, otp: str, purpose: str) -> None:
    """Send an OTP code to the given email address.

    Falls back to console logging when SMTP credentials are not configured.
    Never raises — a failed email must not abort the registration flow; the
    user can request a resend.
    """
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        # Development / CI mode: log OTP so it can be used without real email
        logger.warning("[DEV] OTP for %s (%s): %s", to_email, purpose, otp)
        return

    subject = (
        "Your ADA verification code"
        if purpose == "email_verify"
        else "Your ADA password reset code"
    )

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #7c3aed;">ADA Learning Platform</h2>
        <p>Your verification code is:</p>
        <p style="font-size: 32px; letter-spacing: 8px; font-weight: bold;
                  color: #7c3aed; text-align: center; padding: 16px;
                  background: #f5f3ff; border-radius: 8px;">{otp}</p>
        <p style="color: #6b7280; font-size: 14px;">
            This code expires in 10 minutes. Do not share it with anyone.
        </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    def _send() -> None:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())

    try:
        await asyncio.to_thread(_send)
        logger.info("[email] OTP sent to %s (purpose=%s)", to_email, purpose)
    except Exception:
        logger.exception("[email] Failed to send OTP to %s", to_email)
        # Intentionally swallowed — the OTP record is already in the DB;
        # the student can request a resend via /api/v1/auth/resend-otp
