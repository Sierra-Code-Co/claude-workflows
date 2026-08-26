"""Load .coderabbit.yaml + .review-plan-v2.yaml. Graceful degradation per T007."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .types import HighRiskPath, PathInstruction, RunConfig


def _yq_is_mikefarah() -> tuple[bool, str]:
    """Check the yq variant. Returns (is_mikefarah, version_text)."""
    try:
        out = subprocess.run(["yq", "--version"], capture_output=True, text=True, timeout=5)
        text = (out.stdout + out.stderr).strip()
        lower = text.lower()
        is_mike = "mikefarah" in lower or "version v4" in lower or "version 4" in lower
        return is_mike, text
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False, ""


def _warn(cfg, message: str, prefix: str = ".review-plan-v2.yaml") -> None:
    """Record a config problem so --strict-config can exit 5 on it.

    A malformed context key must not degrade SILENTLY to "no context": the
    operator would read a clean review as covered when the reviewers were never
    given what the config promised them.

    `prefix` names where the bad value came from. It defaults to the config file
    because almost everything here is loaded from it, but settings that can also
    arrive by environment variable must say so: reporting an env-var typo as a
    YAML error sends the operator to edit a file that is already correct.
    """
    msg = f"{prefix}: {message}"
    cfg.config_warnings.append(msg)
    cfg.config_has_error = True
    print(f"WARNING: {msg}", file=sys.stderr)


def _validate_int_field(data: dict, yaml_key: str, cfg, cfg_attr: str, min_value: int) -> None:
    """Apply a numeric YAML field to cfg.<cfg_attr> if int and >= min_value, else warn + flag error."""
    if yaml_key not in data:
        return
    raw = data.get(yaml_key)
    if not isinstance(raw, int) or isinstance(raw, bool):
        msg = f".review-plan-v2.yaml: {yaml_key} must be an integer (got {type(raw).__name__}); ignored."
        cfg.config_warnings.append(msg)
        cfg.config_has_error = True
        print(f"WARNING: {msg}", file=sys.stderr)
        return
    if raw < min_value:
        msg = f".review-plan-v2.yaml: {yaml_key}={raw} invalid (must be >= {min_value}); ignored."
        cfg.config_warnings.append(msg)
        cfg.config_has_error = True
        print(f"WARNING: {msg}", file=sys.stderr)
        return
    setattr(cfg, cfg_attr, raw)


def _yq_to_json(yaml_path: Path, query: str = ".") -> object:
    """Run `yq -o=json '<query>' <file>` and return parsed JSON. Raises on yq error."""
    out = subprocess.run(
        ["yq", "-o=json", query, str(yaml_path)],
        capture_output=True, text=True, check=True, timeout=10,
    )
    text = out.stdout.strip()
    if not text or text == "null":
        return None
    return json.loads(text)


def _load_yaml_files(cfg: RunConfig, coderabbit_path: Path, rpv2_path: Path,
                     cli_config_override: str | None) -> None:
    """Read both YAML files into `cfg`. Returns early, and only from here, if yq is absent.

    Split out of `load_config` so the yq-missing bail cannot skip anything that
    does not need yq. It used to be an early `return cfg` in the middle of
    `load_config`, sitting ABOVE the REVIEW_PLAN_V2_BROAD_PROVIDER override — so
    on a machine with no yq the documented env escape hatch was silently dropped
    and the run printed `broad pass: google (…) [default]`, naming the wrong
    source on the one line CLAUDE.md tells an operator to trust for where their
    diff went. A repo that set the var to satisfy an egress policy got the
    default instead, and nothing said so.

    That is the shape this branch exists to remove — the registry docstring's "a
    default that is wrong only when a parser is missing is a default that is
    wrong" — reappearing one level out, on the override rather than on the
    default. The env var is a plain string that needs no YAML parser, so nothing
    about it belonged behind a yq check. Keeping the bail local to this function
    is what makes that structural rather than a thing to remember.
    """
    # If user passed --config explicitly, the file MUST exist — silently
    # falling back to defaults on a typo would disable filters/instructions
    # without telling the user.
    if cli_config_override and not coderabbit_path.exists():
        cfg.config_warnings.append(
            f"--config {cli_config_override} does not exist; running with defaults."
        )
        cfg.config_has_error = True
        print(f"WARNING: {cfg.config_warnings[-1]}", file=sys.stderr)

    if shutil.which("yq") is None:
        cfg.config_warnings.append(
            "yq not installed; project-aware path_filters/instructions disabled. "
            "Install with: brew install yq"
        )
        cfg.config_has_error = True
        print(f"WARNING: {cfg.config_warnings[-1]}", file=sys.stderr)
        return cfg

    is_mike, version_text = _yq_is_mikefarah()
    if not is_mike:
        cfg.config_warnings.append(
            f"yq on PATH may not be mikefarah's go binary (review-plan-v2 expects v4+). "
            f"yq --version: {version_text}. Install with: brew install yq"
        )
        cfg.config_has_error = True
        print(f"WARNING: {cfg.config_warnings[-1]}", file=sys.stderr)
        # Continue anyway — best-effort

    # .coderabbit.yaml
    if coderabbit_path.exists():
        try:
            data = _yq_to_json(coderabbit_path)
            if isinstance(data, dict):
                # CR's schema allows path_filters at top level OR nested under reviews.
                pf_top = data.get("path_filters") or []
                pf_reviews = (data.get("reviews") or {}).get("path_filters") if isinstance(data.get("reviews"), dict) else None
                pf = pf_top if isinstance(pf_top, list) and pf_top else (pf_reviews or [])
                if isinstance(pf, list):
                    cfg.path_filters = [str(x) for x in pf if isinstance(x, str)]
                # CR's reviews.path_instructions[] OR top-level path_instructions[]
                pi_raw = (data.get("reviews") or {}).get("path_instructions") if isinstance(data.get("reviews"), dict) else None
                if pi_raw is None:
                    pi_raw = data.get("path_instructions")
                if isinstance(pi_raw, list):
                    for item in pi_raw:
                        if isinstance(item, dict) and "path" in item and "instructions" in item:
                            cfg.path_instructions.append(
                                PathInstruction(path_glob=str(item["path"]), instructions=str(item["instructions"]))
                            )
        except (subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            cfg.config_warnings.append(f"could not parse {coderabbit_path}: {e}")
            cfg.config_has_error = True
            print(f"WARNING: {cfg.config_warnings[-1]}", file=sys.stderr)

    # .review-plan-v2.yaml
    if rpv2_path.exists():
        try:
            data = _yq_to_json(rpv2_path)
            if isinstance(data, dict):
                hrp = data.get("high_risk_paths") or []
                if isinstance(hrp, list):
                    for item in hrp:
                        if isinstance(item, dict) and "path" in item:
                            cfg.high_risk_paths.append(
                                HighRiskPath(path_glob=str(item["path"]), reason=str(item.get("reason", "")))
                            )
                # Numeric values: validate ranges + types, warn + ignore on bad input.
                # On failure also set config_has_error so --strict-config exits 5
                # (otherwise a typo'd value is silently dropped).
                _validate_int_field(data, "max_concurrency", cfg, "max_concurrency", min_value=1)
                _validate_int_field(data, "auto_pause_n", cfg, "auto_pause_n", min_value=1)
                _validate_int_field(data, "dedup_line_window", cfg, "dedup_window", min_value=0)
                _validate_int_field(data, "context_budget_chars", cfg, "context_budget_chars", min_value=0)
                # US5 (#18): files every reviewer should always see.
                aif = data.get("always_include_files")
                if aif is not None:
                    if isinstance(aif, list):
                        cfg.always_include_files = [x for x in aif if isinstance(x, str)]
                        # A silently dropped entry is a standing file the
                        # operator believes is attached and is not — the same
                        # failure the empty-glob report exists to prevent, one
                        # layer earlier.
                        bad = len(aif) - len(cfg.always_include_files)
                        if bad:
                            _warn(cfg, f"always_include_files: {bad} non-string "
                                       "entr(y/ies) ignored.")
                    else:
                        _warn(cfg, f"always_include_files must be a list (got "
                                   f"{type(aif).__name__}); ignored.")
                # US5 (#19): module-specifier aliases, e.g. {"$lib": "web/src/lib"}.
                aliases = data.get("import_aliases")
                if aliases is not None:
                    if isinstance(aliases, dict):
                        cfg.import_aliases = {
                            str(k): v for k, v in aliases.items() if isinstance(v, str)
                        }
                        dropped = sorted(set(map(str, aliases)) - set(cfg.import_aliases))
                        if dropped:
                            # An alias that vanishes turns every import through
                            # it into an "unresolved" line, which reads as a
                            # missing file rather than as a config error.
                            _warn(cfg, "import_aliases: non-string value(s) ignored for "
                                       + ", ".join(dropped[:5]))
                    else:
                        _warn(cfg, f"import_aliases must be a mapping (got "
                                   f"{type(aliases).__name__}); ignored.")
                # Which vendor sees every file in the diff. A repo under a
                # data-egress policy sets this; everyone else inherits the default.
                bp = data.get("broad_provider")
                if bp is not None:
                    _apply_broad_provider(cfg, bp, prefix=str(rpv2_path))
        except (subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            cfg.config_warnings.append(f"could not parse {rpv2_path}: {e}")
            cfg.config_has_error = True
            print(f"WARNING: {cfg.config_warnings[-1]}", file=sys.stderr)


def load_config(repo_root: str | Path, cli_config_override: str | None = None) -> RunConfig:
    """Load both YAML config files. Returns RunConfig with config_warnings populated on degradation."""
    cfg = RunConfig()
    repo_root = Path(repo_root)

    coderabbit_path = Path(cli_config_override) if cli_config_override else repo_root / ".coderabbit.yaml"
    rpv2_path = repo_root / ".review-plan-v2.yaml"

    _load_yaml_files(cfg, coderabbit_path, rpv2_path, cli_config_override)

    # Env wins over the file, so a one-off run can redirect the broad pass without
    # editing a committed config. Applied last for that reason, and OUTSIDE
    # _load_yaml_files so that a machine without yq still honours it — see that
    # function's docstring for the fail-open this placement fixes. Exactly one
    # call site, so the precedence is expressed once.
    env_bp = os.environ.get("REVIEW_PLAN_V2_BROAD_PROVIDER")
    if env_bp:
        _apply_broad_provider(cfg, env_bp, prefix="env REVIEW_PLAN_V2_BROAD_PROVIDER")

    return cfg


def _apply_broad_provider(cfg: RunConfig, raw: Any, prefix: str) -> None:
    """Validate and apply a broad_provider selection, or warn and keep the default.

    Rejected at load rather than at call time. An unvalidated tag reaches
    registry.module() once per reviewer per file and surfaces as N identical
    provider errors, which reads as an outage rather than as a typo in a config
    file — and `anthropic`, the one a reader is most likely to try, is refused for
    a design reason no error at the HTTP layer could ever explain.
    """
    from .providers import registry

    # `prefix` is the caller's already-formatted display label — a path for the file
    # origin, "env NAME" for the environment one. This setting has two possible
    # origins and the warning must name the real one: blaming the YAML for an env-var
    # typo sends the operator to edit a file that is already correct.
    #
    # It used to be inferred here with source.endswith(".review-plan-v2.yaml"), which
    # was correct only because the one file origin is always that exact basename. Any
    # future caller passing another path would have had it labelled "env <path>". The
    # caller knows which origin it is; a callee guessing from a string shape does not.

    if not isinstance(raw, str):
        _warn(cfg, f"broad_provider must be a string (got "
                   f"{type(raw).__name__}); keeping {cfg.broad_provider}.", prefix=prefix)
        return
    tag = raw.strip().lower()
    if tag not in registry.REVIEW_CAPABLE:
        try:
            registry.module(tag)
        except registry.UnknownProvider as e:
            _warn(cfg, f"broad_provider: {e}. Keeping {cfg.broad_provider}.", prefix=prefix)
            return
        # Reachable only if REVIEW_CAPABLE and _MODULES ever disagree.
        _warn(cfg, f"broad_provider: {tag!r} is not review-capable. "
                   f"Keeping {cfg.broad_provider}.", prefix=prefix)
        return
    cfg.broad_provider = tag
    # Record the origin only on success. A rejected value keeps the previous
    # provider, so it must keep that provider's source too — labelling the run
    # with the file that was refused would point the operator at the wrong place.
    cfg.broad_provider_source = prefix


def has_config_error(cfg: RunConfig) -> bool:
    """True if a config parse error or missing-dep warning was raised during load."""
    return cfg.config_has_error
