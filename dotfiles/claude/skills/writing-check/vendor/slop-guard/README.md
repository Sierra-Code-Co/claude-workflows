# Packed slop-guard

`slop-guard.pyz` is [slop-guard](https://github.com/eric-tramel/slop-guard) by Eric W. Tramel, MIT licence (`LICENSE` here is upstream's, unmodified). It is packed as one file so the writing check runs with plain `python3` (3.11 or newer) and nothing to install.

## What is upstream and what is ours

Every file from the published wheel is inside the pack byte for byte, including its `dist-info` folder. `VENDOR.json` records the version, the wheel's sha256 as published on PyPI, and the pack's own sha256. A test re-checks every packed file against the hashes in the wheel's own `RECORD`.

Two files at the root of the pack are ours, and listed under `overlay` in `VENDOR.json`:

- `typing_extensions.py` re-exports `TypedDict` from the standard library. slop-guard's `models.py` imports it from the third-party `typing_extensions` package, which is the only thing that would otherwise need installing.
- `__main__.py` runs slop-guard's `sg` command-line entry point.

No upstream file is edited.

## Running it

```bash
python3 slop-guard.pyz -v -t 80 draft.txt
```

Same arguments as `sg`. Exit 0 pass, 1 below the threshold.

## Updating

Never automatic. The weekly `check-speckit-update.yml` job opens an issue when PyPI has a newer release. Then:

```bash
python3 scripts/pull-slop-guard.py --version X.Y.Z --sha256 <wheel sha256 from pypi.org/pypi/slop-guard/X.Y.Z/json>
.venv/bin/python -m pytest tests/unit/test_slop_guard_vendor.py tests/unit/test_writing_check.py -q
```

The phrase-list coverage test fails if the new release added words or phrases; decide for each whether it goes in `banned-phrases.txt` or on a `# read-by-hand:` line, then open a normal PR.
