---
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Skill, Read, Write, Edit, Bash, Glob, Grep]
---

Draw an architecture diagram of our checkout system. Components: web app, mobile app, API gateway, auth service, cart service, order service, payment service, inventory service, Postgres, Redis cache, and a Kafka event bus. The apps call the gateway, the gateway routes to the auth, cart and order services, order service publishes to Kafka, payment and inventory consume from it, services use Postgres, cart uses Redis. Save it as one self-contained HTML file in the current directory. I am not available for questions: keep the default style and proceed with your best judgment.
