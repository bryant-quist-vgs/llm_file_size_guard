"""Configuration and central path handling for llm_file_size_guard.py, built against contract v1."""

from __future__ import annotations

from pathlib import Path
import sys
import tomllib
from typing import Any

from llm_file_size_guard_core import APP_NAME, DEFAULT_THRESHOLDS, RepoIdentity, UsageError


DEFAULT_REPO_CONFIG_FILE = ".llm-file-size-guard.toml"


def user_support_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform.startswith("win"):
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    return Path.home() / ".config" / APP_NAME


def system_support_dir() -> Path:
    if sys.platform == "darwin":
        return Path("/Library/Application Support") / APP_NAME
    if sys.platform.startswith("win"):
        return Path("C:/ProgramData") / APP_NAME
    return Path("/etc") / APP_NAME


def default_state_dir() -> Path:
    if sys.platform == "darwin" or sys.platform.startswith("win"):
        return user_support_dir() / "state"
    return Path.home() / ".local" / "state" / APP_NAME


def standard_config_paths(repo_root: Path) -> list[Path]:
    return [
        system_support_dir() / "config.toml",
        user_support_dir() / "config.toml",
        repo_root / DEFAULT_REPO_CONFIG_FILE,
    ]


def resolve_state_path(
    repo_root: Path,
    state: str | None,
    local_state_dir: str | None,
    repo_identity: RepoIdentity,
) -> Path:
    if state is None:
        if local_state_dir is None:
            state_dir = default_state_dir()
        else:
            state_dir = Path(local_state_dir).expanduser()
            if not state_dir.is_absolute():
                state_dir = repo_root / state_dir
        return (state_dir / "repos" / f"{repo_identity.key}.json").resolve()
    path = Path(state).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def require_positive_int(value: Any, label: str, path: Path) -> int:
    if not isinstance(value, int) or value < 1:
        raise UsageError(f"config file {path} field {label} must be a positive integer")
    return value


def require_string(value: Any, label: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError(f"config file {path} field {label} must be a non-empty string")
    return value


def flatten_config(data: dict[str, Any], path: Path) -> dict[str, Any]:
    allowed_sections = {"thresholds", "selection", "tracking"}
    unknown_sections = sorted(set(data) - allowed_sections)
    if unknown_sections:
        raise UsageError(
            f"config file {path} contains unsupported section(s): {', '.join(unknown_sections)}"
        )

    values: dict[str, Any] = {}
    thresholds = data.get("thresholds", {})
    if thresholds is not None:
        if not isinstance(thresholds, dict):
            raise UsageError(f"config file {path} section [thresholds] must be a table")
        for key in DEFAULT_THRESHOLDS:
            if key in thresholds:
                values[key] = require_positive_int(thresholds[key], f"thresholds.{key}", path)
        unknown = sorted(set(thresholds) - set(DEFAULT_THRESHOLDS))
        if unknown:
            raise UsageError(f"config file {path} contains unsupported threshold(s): {', '.join(unknown)}")

    selection = data.get("selection", {})
    if selection is not None:
        if not isinstance(selection, dict):
            raise UsageError(f"config file {path} section [selection] must be a table")
        if "extensions" in selection:
            extensions = selection["extensions"]
            if isinstance(extensions, str):
                values["extensions"] = extensions
            elif isinstance(extensions, list) and all(isinstance(item, str) for item in extensions):
                values["extensions"] = extensions
            else:
                raise UsageError(
                    f"config file {path} field selection.extensions must be a string or list of strings"
                )
        unknown = sorted(set(selection) - {"extensions"})
        if unknown:
            raise UsageError(f"config file {path} contains unsupported selection field(s): {', '.join(unknown)}")

    tracking = data.get("tracking", {})
    if tracking is not None:
        if not isinstance(tracking, dict):
            raise UsageError(f"config file {path} section [tracking] must be a table")
        if "local_state_dir" in tracking:
            values["local_state_dir"] = require_string(
                tracking["local_state_dir"], "tracking.local_state_dir", path
            )
        if "state_path" in tracking:
            values["state"] = require_string(tracking["state_path"], "tracking.state_path", path)
        unknown = sorted(set(tracking) - {"local_state_dir", "state_path"})
        if unknown:
            raise UsageError(f"config file {path} contains unsupported tracking field(s): {', '.join(unknown)}")
    return values


def load_config_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UsageError(f"could not read config file {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"config file {path} is not valid TOML: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError(f"config file {path} must contain a TOML table")
    return flatten_config(data, path)


def load_configuration(repo_root: Path, no_config: bool) -> tuple[dict[str, Any], list[Path], list[Path]]:
    paths = standard_config_paths(repo_root)
    if no_config:
        return {}, [], paths
    values: dict[str, Any] = {}
    loaded: list[Path] = []
    for path in paths:
        file_values = load_config_file(path)
        if file_values is None:
            continue
        values.update(file_values)
        loaded.append(path)
    return values, loaded, paths
