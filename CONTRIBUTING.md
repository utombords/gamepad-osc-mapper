# Contributing to Gamepad OSC Mapper

Thanks for your interest in contributing! This document outlines how to build, run, and propose changes.

## Getting started
- Fork this repository and create a feature branch from `main`.
- Use Python 3.10+ on Windows (primary target). Other OSes may work but are not officially supported.

## Build and run (dev)
```bash
pip install -r requirements.txt
python -m app.main
```
Open the UI at `http://127.0.0.1:5000`.

## Build one-file executable
```bash
pip install pyinstaller
pyinstaller --clean --noconfirm main.spec
```
The EXE will be in `dist/`.

## Coding guidelines
- Python
  - Prefer clarity over cleverness; add concise docstrings for modules/classes/methods.
  - Strongly type public APIs when practical.
  - No print-based debugging in committed code; use `logging`.
  - Keep functions short, use guard clauses, handle edge cases first.
- JavaScript
  - Keep file headers concise; avoid noisy logs.
  - Use explicit names and small functions.

## Style and linting
- Match existing formatting. If in doubt:
  - Python: PEP 8, docstrings per PEP 257.
  - JS: Prettier-like spacing; no semicolons required.
- Prefer small, focused edits.

## Branching, commits, and PRs
- Branch naming: `feat/`, `fix/`, `docs/`, `chore/` prefixes.
- Commits: present-tense, concise subject, include rationale when non-obvious.
- Pull Requests
  - Describe the problem, the solution, and testing performed.
  - Link related issues, add screenshots if UI changes.
  - Keep PRs small and focused; large PRs may be asked to split.
  - CI must pass (lint/build). Mark PRs as draft until ready.

## Triage labels and review
- Maintainers use labels: `bug`, `enhancement`, `question`, `good first issue`, `help wanted`.
- Expected initial triage response: 3 business days.
- Review SLA for small PRs: aim for review within 5 business days.

## Issue reporting
- Use the issue templates (bug report / feature request).
- For bugs: include steps to reproduce, expected vs actual, logs, and environment (OS, app version, controllers).

## Security
- Do not file security issues publicly. See `SECURITY.md` for responsible disclosure.

## Licensing
- By contributing, you agree your contributions are licensed under the project license (MIT).
