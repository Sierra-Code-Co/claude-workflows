# Quickstart: validate the first release

```bash
# 1. tests (from repo root, in the project venv)
.venv/bin/python -m pytest tests/unit/test_writing_check.py tests/unit/test_slop_guard_vendor.py \
  tests/unit/test_copilot_zip.py tests/unit/test_marketplace.py \
  tests/unit/test_personal_skill_links.py tests/unit/test_slop_guard_version_check.py -q

# 2. the path the global instructions name
~/.claude/skills/writing-check/scripts/prose-check.sh some-draft.txt; echo "exit=$?"

# 3. no install needed: hide sg and run again
env PROSE_CHECK_PYTHON="$(command -v python3.13)" PATH=/usr/bin:/bin ~/.claude/skills/writing-check/scripts/prose-check.sh some-draft.txt

# 4. zip current?
python3 scripts/build-copilot-zips.py --check

# 5. mirror dry run (needs Jason's yes only for --apply/--push)
./scripts/sync-public.sh
```

Expected: tests pass; step 2 prints a score and exits 0 or 1; step 3 identical; step 4 exits 0; step 5 prints `denylist gate: clean`.
