---
name: fix
description: Fix a bug by reproducing it with a failing test, fixing the root cause, and proving the fix. Takes a bug description, an error message, or a GitHub issue number.
disable-model-invocation: true
argument-hint: "<bug description | error message | #issue>"
---

Fix: $ARGUMENTS

## 1. Understand

- If the argument is an issue number like `#123` and `gh` is available, run `gh issue view <n> --comments` to read it.
- Restate the bug in one line: the expected behavior, the actual behavior, and the conditions.
- Find the code path involved. Use the Explore subagent if you don't know where to look. Check `git log -p` on the suspect files for recent changes.

## 2. Reproduce

- Write a test that fails because of this bug, in the project's test style, next to the related tests.
- Run it with the `test-runner` subagent and confirm it fails **for the reason described**, not because of a setup error.
- If a test isn't practical (UI-only, timing, environment), write the smallest reproduction script or exact manual steps instead, and say why.
- If you can't reproduce the bug, stop. Report what you tried and what information would help.

## 3. Fix the root cause

- Fix the cause, not the symptom. Don't wrap it in try/catch, special-case the test input, or weaken an assertion.
- Keep the diff small. If the real fix needs a larger change, explain it and ask before making it.
- Look for the same bug pattern elsewhere (grep for similar code) and list the occurrences. Fix them only if they are clearly the same bug.

## 4. Prove it

- With `test-runner`, run the new test (it must pass), then the related suite, then the full suite.
- For a non-trivial fix, delegate to the `reviewer` subagent for the uncommitted changes.

## 5. Report

- **Root cause:** one or two sentences, with `file:line`
- **Fix:** what changed
- **Evidence:** the failing test before the fix, and test-runner's results after
- **Same pattern elsewhere:** occurrences found, and whether you fixed them
- **Suggested commit message:** `fix: ...`

Don't commit. The user runs `/ship` when ready.
