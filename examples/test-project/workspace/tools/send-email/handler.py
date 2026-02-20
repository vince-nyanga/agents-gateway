"""Send email via SMTP (smtp4dev in development)."""

import os
import smtplib
from email.message import EmailMessage


async def handle(to: str, subject: str, body: str) -> dict:
    """Send an email and return confirmation."""
    smtp_host = os.environ.get("SMTP_HOST", "localhost")
    smtp_port = int(os.environ.get("SMTP_PORT", "2525"))
    from_addr = os.environ.get("SMTP_FROM", "agent@example.com")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.send_message(msg)
        return {
            "status": "sent",
            "to": to,
            "subject": subject,
            "message": f"Email sent to {to} via {smtp_host}:{smtp_port}",
        }
    except Exception as e:
        return {
            "status": "error",
            "to": to,
            "subject": subject,
            "error": str(e),
        }
