---
name: ship
description: Final checks and commit. Runs the full verification, scans the diff for leftovers and secrets, writes a Conventional Commit, and optionally pushes and opens a PR.
disable-model-invocation: true
argument-hint: "[pr]  (add 'pr' to also push and open a pull request)"
---

Prepare the current changes for commit. Option: $ARGUMENTS

## 1. Inspect

- Run `git status` and `git diff HEAD --stat`, and note the current branch.
- If you are on the default branch (`main`/`master`) and the user wants a PR, propose a branch name and create the branch after the user confirms.
- If there are no changes, say so and stop.

## 2. Verify

- Delegate to the `test-runner` subagent: full test suite, plus build, lint and typecheck if CLAUDE.md lists them.
- If anything fails, stop and report. Don't commit failing work unless the user explicitly says to.

## 3. Scan the diff

Read the full `git diff HEAD`, including untracked files that will be added, and flag:
- secrets: API keys, tokens, passwords, private keys, `.env` content
- leftovers: debug prints, commented-out code blocks, `TODO`s added in this diff, focused or skipped tests (`.only`, `@Disabled`, `skip`), temporary files
- unrelated changes that don't belong in this commit

Show what you found and ask how to handle each item. Never commit a secret.

## 4. Commit

- If the project has a CHANGELOG or docs that this change affects, offer to update them.
- Write a Conventional Commit message: `type(scope): summary` (types: feat, fix, refactor, perf, test, docs, build, ci, chore), a body explaining *why*, and `BREAKING CHANGE:` if it applies. Write it in English.
- Show the message and the list of files to stage. After the user confirms, stage those specific files (not `git add -A` blindly) and commit.
- If a pre-commit hook fails, fix the cause and make a new commit. Don't use `--no-verify`.

## 5. Push and PR (only if the argument contains `pr`)

- Push with `git push -u origin <branch>`. The project settings ask for confirmation before a push.
- If `gh` is available, create the PR with `gh pr create`. Use a title that matches the commit, and a body with a Summary, How it was tested (paste the test-runner result) and any risks. Return the PR URL.
