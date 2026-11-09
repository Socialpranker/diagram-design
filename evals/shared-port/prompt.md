---
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Skill, Read, Write, Edit, Bash, Glob, Grep]
---

Draw an architecture diagram: an API gateway forwards requests to a users service, an orders service and a billing service. All three services read and write the same Postgres database, and the orders service also calls the users service. Save it as one self-contained HTML file in the current directory. I am not available for questions: keep the default style and proceed with your best judgment.
