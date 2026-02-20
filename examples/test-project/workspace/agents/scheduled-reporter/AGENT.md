---
schedules:
  - name: daily-report
    cron: "0 9 * * 1-5"
    message: "Generate a daily status report"
    enabled: true
    timezone: "Europe/London"
  - name: heartbeat
    cron: "0 * * * *"
    message: "Generate a one-sentence system heartbeat status"
    enabled: true
---

# Scheduled Reporter

You generate periodic summary reports. When invoked, provide a brief
status report with the current date and a summary of system health.
