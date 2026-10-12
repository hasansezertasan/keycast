---
priority: high
---

# Pull requests

CI blocks a PR whose branch name or title breaks these conventions — follow them
before opening one:

- **Branch names** follow [Conventional Branch](https://conventionalbranch.org/):
  `<type>/<short-description>` (e.g. `feat/add-login`). Allowed types are
  `feature`/`feat`, `bugfix`/`fix`, `hotfix`, `release`, `chore`, plus the
  AI-agent prefixes `ai`, `copilot`, `cursor`, `claude`, `codex`. The description
  is lowercase alphanumerics separated by single `-` or `.` (no leading, trailing,
  or consecutive separators). Enforced by `check-branch-name.yml`, which also
  whitelists the `renovate/*` and `release-please--*` automation branches — leave
  those as-is.
- **PR titles** follow [Conventional Commits](https://www.conventionalcommits.org/)
  (e.g. `feat: add login`) — the title becomes the squash commit release-please
  parses, so it drives versioning. Enforced by `check-pr-title.yml`.
- Every human-authored PR must **link an issue** (a `Closes #N` keyword in the
  body) unless it carries the `no-issue` label. Enforced by
  `check-linked-issues.yml`, which auto-skips PRs opened by a bot account (login
  ending in `[bot]`) — don't fabricate an issue reference for those.
