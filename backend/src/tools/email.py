"""MCP tool for sending emails via SMTP."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from ..config import Settings

logger = structlog.get_logger()


async def send_email(settings: Settings, to: str, subject: str,
                     body: str, html: str | None = None) -> str:
    """Send an email via SMTP.

    Args:
        to: Recipient email address (comma-separated for multiple)
        subject: Email subject
        body: Plain text body
        html: Optional HTML body
    """
    if not settings.smtp_host or not settings.smtp_user:
        return "Error: SMTP not configured (missing SMTP_HOST or SMTP_USER)"

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.smtp_user
        msg["To"] = to
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

        logger.info("Email sent", to=to, subject=subject)
        return f"Email sent to {to}: {subject}"

    except Exception as e:
        logger.error("Email failed", to=to, error=str(e))
        return f"Email error: {e}"
