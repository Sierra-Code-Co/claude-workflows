"""Exit 0 must not be able to mean "I reviewed nothing" silently (T005k).

Hit live: changes were STAGED but not committed, so the branch tip equalled the
base. The run printed `reviewing 0 of 0 changed file(s)` and returned 0 — which
under the documented contract (`0 = ... clean diff`) is byte-identical to a full
clean review. `review-plan-v2 && git push` would have pushed unreviewed code
while reporting success.

HALF OF THE ORIGINAL CLAIM WAS WRONG, and it is worth writing down. I filed
this as "rpv2 exits 0 when it reviews nothing" as though the exit code were a
bug. `contracts/cli-flags.md` explicitly documents exit 0 for a clean diff, and
`|| exit 1` pre-push hooks are a documented use — so failing by default would
break them for a case that is usually harmless (an empty diff has nothing to
push either). The real gap is narrower: nothing DISTINGUISHED the two states.

So: a banner always, and `--require-changes` for callers that need the strict
reading. The banner is the part that matters — a flag nobody passes changes
nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import types

import pytest
from review_plan_v2 import orchestrator
from review_plan_v2.types import Diff, RunConfig, merge_cli_into_config


def _args(**over):
    base = dict(
        config=None, base="main", scope=None, strict_config=False,
        dry_run=False, no_verify=False, require_changes=False,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.fixture()
def empty_run(monkeypatch, tmp_path):
    """Drive run() to the empty-diff branch with no git, network or provider."""
    monkeypatch.chdir(tmp_path)

    def _drive(require_changes: bool, dropped=None):
        cfg = RunConfig()
        cfg.require_changes = require_changes
        monkeypatch.setattr(orchestrator.config_mod, "load_config", lambda *a, **k: cfg)
        monkeypatch.setattr(orchestrator, "merge_cli_into_config", lambda args, c: c)
        monkeypatch.setattr(
            orchestrator.diff_capture, "capture_diff",
            lambda *a, **k: Diff(base_ref="main", head_ref="HEAD", files=()),
        )
        return orchestrator.run(_args(require_changes=require_changes))

    return _drive


def test_the_default_still_exits_zero(empty_run):
    """The documented contract, unchanged. Breaking it would break every
    `review-plan-v2 || exit 1` pre-push hook for a case that is harmless."""
    assert empty_run(require_changes=False) == 0


def test_but_it_SAYS_it_reviewed_nothing(empty_run, capsys):
    """The part that actually closes the gap.

    A flag nobody passes changes nothing; the banner reaches every caller,
    including the human who was about to read exit 0 as "clean".
    """
    empty_run(require_changes=False)
    err = capsys.readouterr().err
    assert "[NOTHING REVIEWED]" in err
    assert "NOT a clean review" in err
    assert "COMMITTED" in err, (
        "the message must name the cause I actually hit — uncommitted changes — "
        "or it tells the reader a fact without a next step"
    )


def test_require_changes_makes_it_a_failure(empty_run):
    """For CI, where 'prove you reviewed this' is the whole point."""
    assert empty_run(require_changes=True) == 2


def test_the_banner_names_WHICH_emptiness(empty_run, capsys):
    """"No changes vs base" and "your filters excluded everything" need
    different fixes, so they must not print the same sentence. The second is
    the more dangerous one: files DID change and none were examined."""
    empty_run(require_changes=False)
    assert "no changes vs the base ref" in capsys.readouterr().err


# --- delivery: the flag must actually reach the config ----------------------


def _parsed(*extra):
    """Build args the way the CLI does, so the merge sees a real namespace."""
    from review_plan_v2.__main__ import build_parser
    return build_parser().parse_args(["--plain", "--base", "main", *extra])


def test_the_flag_reaches_the_run_config():
    """A CLI flag that never lands in RunConfig is a flag that does nothing,
    and the run looks identical either way — the same one-line gap that made
    `needs_manifest=False` a four-times-a-session false positive.

    Built from the REAL parser rather than a hand-made namespace: my first
    version used SimpleNamespace and blew up on `args.type`, which is exactly
    the sort of divergence a hand-made fixture hides."""
    assert merge_cli_into_config(_parsed("--require-changes"), RunConfig()).require_changes is True


def test_the_flag_defaults_off():
    assert merge_cli_into_config(_parsed(), RunConfig()).require_changes is False


def test_the_flag_is_exposed_on_the_cli():
    """Constructed AND reachable: the parser is what a user actually touches."""
    from review_plan_v2.__main__ import build_parser

    parsed = build_parser().parse_args(["--plain", "--base", "main", "--require-changes"])
    assert parsed.require_changes is True
