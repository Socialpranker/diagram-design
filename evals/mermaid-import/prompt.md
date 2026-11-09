---
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Skill, Read, Write, Edit, Bash, Glob, Grep]
---

Redraw this Mermaid diagram as a proper diagram. Save it as one self-contained HTML file in the current directory. I am not available for questions: keep the default style and proceed with your best judgment.

```mermaid
flowchart LR
  U[User] --> FE[Frontend]
  FE --> API[API]
  API --> Q{Cached?}
  Q -- yes --> C[(Redis)]
  Q -- no --> DB[(Postgres)]
  DB --> API
  API --> W[Worker]
  W --> S3[(Object store)]
  W -.-> M[Metrics]
```
