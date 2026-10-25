---
name: kit-setup
description: One-time setup of the starter kit for this project. Detects the stack and real commands, fills in CLAUDE.md, adds safe allow rules, and optionally adds a format-on-edit hook. Run after installing the kit or when the stack changes.
disable-model-invocation: true
argument-hint: "[short description of the project, for an empty repo]"
---

Set up the Claude starter kit for this project. Work through these steps in order and show the user what you will change before you write it.

User notes: $ARGUMENTS

## 0. Prepare the kit folder

The kit was cloned straight into `.claude/`, so its instructions live in `.claude/CLAUDE.md`.
- If `.claude/.git` exists, the project's own git will treat `.claude` as a nested repo and won't commit its files. Ask the user whether to delete `.claude/.git` so `.claude` can be committed with the project. Delete it only after they agree.
- Delete `.claude/README.md`. It explains the kit on GitHub and isn't needed in the project.
- If the project also has a root `CLAUDE.md` or `AGENTS.md`, both load into every session. Merge the project-specific content into `.claude/CLAUDE.md`, show the user the result, and after they confirm, replace the root file's content with a pointer or remove it. Don't lose existing project content.
- Add `CLAUDE.local.md` and `.claude/settings.local.json` to the root `.gitignore` if they aren't already listed. Create the file if needed.

## 1. Understand the project

- Read the README, manifests (`package.json`, `pom.xml`, `build.gradle*`, `settings.gradle*`, `pyproject.toml`, `requirements*.txt`, `go.mod`, `Cargo.toml`, `*.csproj`, `composer.json`, `Gemfile`), `Makefile`/`justfile`, `docker-compose*.yml`, CI workflows (`.github/workflows/*`), and the top two levels of the tree.
- For a monorepo, list each package or app and its stack.
- **Empty or near-empty repo (no code yet):** read any planning documents first, such as `plan.md`, `PLAN.md`, `SPEC*.md`, `docs/**/*.md`, `README*` and design notes. Take the language, framework, libraries, layout and conventions from them. Use AskUserQuestion only for what they leave open (language, framework, database, package manager, test framework). Fill CLAUDE.md, point it at the plan file, and mark the commands as "not verified yet: no code exists".

## 2. Find and verify the commands

For each of Install, Dev, Build, Test (all), Test (one), Lint, Format and Typecheck:
- Take the command from CI config or manifest scripts. CI shows what actually runs.
- Run each one that is quick and side-effect free (build, test, lint, typecheck) to confirm it works. Ask before running anything slow, anything that needs services, or anything that writes outside the repo. Don't start the dev server.
- For "Test (one)", give the real syntax for running a single test file or test name with this test framework.
- Drop any line that doesn't apply. Don't keep placeholders.

## 3. Fill in .claude/CLAUDE.md

Replace every placeholder in `.claude/CLAUDE.md` and remove the `<!-- -->` guidance comments. Rules:
- Keep it short, under ~100 lines. Include only what Claude can't work out by reading code: exact commands, non-default conventions, gotchas, generated directories not to edit, required env var *names* (never values).
- Keep the "How we work" section as it is, unless the user asks for changes.
- For conventions that only matter in part of the tree (for example, only in `frontend/`), offer to put them in `.claude/rules/<name>.md` with `paths:` frontmatter instead.

## 4. Permissions

In `.claude/settings.json`, add `permissions.allow` rules for the verified build, test, lint, format and typecheck commands, so they run without prompts. Use the narrowest pattern that works, for example `"Bash(npm run test *)"` or `"Bash(./gradlew test *)"`, and add a matching `PowerShell(...)` rule when the command also runs from PowerShell on Windows. Don't touch the existing `deny`/`ask` rules or the guard hook.

## 5. Optional: format on edit

If the project has a formatter that can format one file quickly (Prettier, Black, gofmt, rustfmt, Spotless, ktlint), ask the user whether to add a PostToolUse hook that formats each file after Claude edits it. If they agree, add it to `.claude/settings.json` under `hooks.PostToolUse` with matcher `Edit|Write`. Use exec form (`"command"` plus `"args"`) where possible, and keep the hook from failing on files the formatter doesn't handle.

## 6. Report

Show:
- the detected stack,
- each command and whether you verified it (✅ ran OK / ⚠️ not run / ❌ failed, with the error),
- the files you changed,
- anything the user should fill in by hand.

Then suggest committing `.claude/` and `.gitignore`.
