# scripts/

Operational tooling for Phase 0 of [../IMPROVEMENTS.md](../IMPROVEMENTS.md).

| Script | What it does |
|---|---|
| [`audit_secrets.py`](audit_secrets.py) | Compares your live `backend/.env` against every `.env` blob in git history. Answers "is a leaked value still in use?" Never prints a secret — only an irreversible hash prefix. |
| [`check_llm_health.py`](check_llm_health.py) | Probes each provider: reachable? does the configured model still exist? `--live` sends a real completion through the router and reports which vendor served it. |
| [`pre-commit`](pre-commit) | Git hook. Blocks `.env` files, credential patterns, and vendored dirs (`venv/`, `node_modules/`) from being committed. Zero dependencies; uses `gitleaks` as an extra layer when installed. |
| [`install-hooks.sh`](install-hooks.sh) | Installs the hook into `.git/hooks/`. Safe to re-run. |
| [`purge-history.sh`](purge-history.sh) | Rewrites history to drop `backend/.env` and `backend/venv`. Dry-run by default; **never pushes**. |

## Everyday use

```bash
# After rotating any key — confirm nothing leaked is still live
python scripts/audit_secrets.py

# After rotating GOOGLE_API_KEY or changing a model ID
python scripts/check_llm_health.py --live

# New clone / new machine
bash scripts/install-hooks.sh
```

## Why the hook exists

`backend/.env` was committed in `62927b7` and deleted in `9f68825`. The blob survived in history,
reachable from the public `origin/main`, and Google revoked the Gemini key with
*"Your API key was reported as leaked."*

Deleting a file in a later commit does not unpublish it. Rotation is the only real fix — the hook
is here so there is no next time.

## Note on the checked-in venv

`backend/venv/` is tracked: 12,669 files, ~35 MB, 110 compiled binaries. The hook blocks *new*
venv paths, but removing the existing ones is a separate step (see Phase 1 in IMPROVEMENTS.md):

```bash
git rm -r --cached backend/venv && git commit -m "chore: untrack committed virtualenv"
```
