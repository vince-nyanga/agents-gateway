---
name: send-email
description: "Send an email via SMTP (uses smtp4dev in development)"
parameters:
  type: object
  properties:
    to:
      type: string
      description: "Recipient email address"
    subject:
      type: string
      description: "Email subject line"
    body:
      type: string
      description: "Email body (plain text)"
  required:
    - to
    - subject
    - body
---

# Send Email Tool

Sends an email using SMTP. In development, emails are captured by smtp4dev
and can be viewed at http://localhost:3000.
