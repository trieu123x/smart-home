---
name: feature
description: Build a feature end to end. Plan, implement with tests, verify with test-runner, review with reviewer, then summarize with evidence. Takes a spec path from /spec or a short description.
disable-model-invocation: true
argument-hint: "<docs/specs/...md | short description>"
---

Build: $ARGUMENTS

## 1. Load the requirements

- If the argument is a spec file, read it in full. Its acceptance criteria are the definition of done.
- If it's a description and the work clearly spans several files, has unclear behavior, or changes data or API contracts, stop and suggest `/spec` first. If it's small and clear, carry on.

## 2. Plan

- Read the code you will change and its tests. Use the Explore subagent for broad searches so the file dumps stay out of this context.
- If the work touches more than two or three files, write a short plan: the files to change, the order of steps, and the tests to add. Wait for the user's OK before editing. For smaller work, state the plan in two lines and go.

## 3. Implement

- Work in small steps that each leave the code buildable.
- Follow existing patterns in the codebase: naming, error handling, structure, test style.
- Write or update tests with the code, covering the acceptance criteria and the edge cases in the spec.
- Don't add dependencies, change public APIs, or refactor unrelated code without asking.

## 4. Verify

- Delegate to the `test-runner` subagent: first the tests you touched, then the full test suite, plus lint and typecheck if CLAUDE.md lists them.
- Fix failures and run test-runner again. If the same failure survives three rounds, stop and report what you tried, rather than weakening or skipping tests.

## 5. Review

- Delegate to the `reviewer` subagent, passing it the spec path (if any) and the instruction to review the uncommitted changes.
- If the change touches auth, user input parsing, SQL, shell commands, file handling or network calls, also delegate to `security-reviewer`.
- Fix BLOCKER and SHOULD-FIX findings that you agree with, then re-run test-runner. If you disagree with a finding, say why. Don't chase Optional items unless they are trivial.

## 6. Summarize

Report:
- **What changed:** files and one line for each
- **Evidence:** the test-runner result (command plus PASS/FAIL counts) and the reviewer verdict
- **Acceptance criteria:** each one marked ✅ or ❌
- **Follow-ups:** known limitations or open questions
- **Suggested commit message** (Conventional Commits)

Don't commit. The user runs `/ship` when ready.
