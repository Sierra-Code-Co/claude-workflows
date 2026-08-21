"""Load .coderabbit.yaml + .review-plan-v2.yaml. Graceful degradation per T007."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

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


def _warn(cfg, message: str) -> None:
    """Record a config problem so --strict-config can exit 5 on it.

    A malformed context key must not degrade SILENTLY to "no context": the
    operator would read a clean review as covered when the reviewers were never
    given what the config promised them.
    """
    msg = f".review-plan-v2.yaml: {message}"
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


def load_config(repo_root: str | Path, cli_config_override: str | None = None) -> RunConfig:
    """Load both YAML config files. Returns RunConfig with config_warnings populated on degradation."""
    cfg = RunConfig()
    repo_root = Path(repo_root)

    coderabbit_path = Path(cli_config_override) if cli_config_override else repo_root / ".coderabbit.yaml"
    rpv2_path = repo_root / ".review-plan-v2.yaml"

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
        except (subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            cfg.config_warnings.append(f"could not parse {rpv2_path}: {e}")
            cfg.config_has_error = True
            print(f"WARNING: {cfg.config_warnings[-1]}", file=sys.stderr)

    return cfg


def has_config_error(cfg: RunConfig) -> bool:
    """True if a config parse error or missing-dep warning was raised during load."""
    return cfg.config_has_error
