---
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Skill, Read, Write, Edit, Bash, Glob, Grep]
---

Draw a flowchart of a webhook delivery worker: dequeue event, sign payload, POST to the customer endpoint, check the response. On 2xx mark delivered. On 5xx or timeout wait with exponential backoff and go back to POST, up to 5 attempts; after the fifth failure move the event to the dead-letter queue. Save it as one self-contained HTML file in the current directory. I am not available for questions: keep the default style and proceed with your best judgment.
