"""Send email via SMTP (smtp4dev in development)."""

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


async def handle(arguments: dict, context: object) -> dict:
    """Send an email and return confirmation."""
    logger.info("send-email called with arguments: %s", arguments)
    # Unwrap if the LLM nested args under a 'properties' key
    if "properties" in arguments and isinstance(arguments["properties"], str):
        import json
        arguments = json.loads(arguments["properties"])
    elif "properties" in arguments and isinstance(arguments["properties"], dict):
        arguments = arguments["properties"]
    to = arguments.get("to") or arguments.get("recipient") or arguments.get("to_email", "engineering-team@example.com")
    subject = arguments.get("subject") or arguments.get("subject_line", "(no subject)")
    body = arguments.get("body") or arguments.get("content") or arguments.get("message", "")
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
