---
name: spec
description: Interview the user about a feature or change, then write a self-contained spec to docs/specs/. Use before building anything that touches several files or has unclear requirements.
disable-model-invocation: true
argument-hint: "<feature idea in a sentence>"
---

Write a spec for: $ARGUMENTS

## 1. Look before asking

Spend a few minutes on the code this feature will touch: the relevant modules, their data models and their existing patterns. For broad searches, use the Explore subagent. Don't ask the user anything the code already answers.

## 2. Interview

Use AskUserQuestion to interview the user, in rounds of 1–4 questions. Skip obvious questions and dig into the hard parts:
- who uses it and what problem it solves; what "done" looks like
- behavior at the edges: empty, invalid and huge inputs, concurrent use, failures of dependencies
- data: new fields or tables, migrations, backward compatibility
- API/UI contract: endpoints, messages, screens, error states
- non-goals: what this explicitly does not do
- constraints: performance, security, compatibility, deadlines

Where you have a sensible recommendation, offer it as the first option. Stop when another round would not change the design.

## 3. Write the spec

Write `docs/specs/<YYYY-MM-DD>-<kebab-slug>.md` using today's date. Create the folder if it doesn't exist. Structure:

```markdown
# <Title>

Status: draft · Date: <YYYY-MM-DD>

## Problem
## Goals
## Non-goals
## Design
<Files and modules to change, new interfaces and data shapes, the main flow. Name real paths.>
## Data and API changes
<Schema or migration, endpoints and messages, config. Write "None" if there are none.>
## Edge cases and errors
## Test plan
<Unit/integration tests by name or behavior, plus one end-to-end check that proves the feature works.>
## Acceptance criteria
- [ ] <observable, testable statement>
## Open questions
```

Keep it as short as precision allows. Every acceptance criterion must be something a test or a command can check.

## 4. Hand off

Tell the user the spec path and suggest: review it, then run `/clear` and `/feature <spec path>` so the build starts from a clean context.
