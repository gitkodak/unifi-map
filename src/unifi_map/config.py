"""Environment handling.

This is the only module that reads ``os.environ``. Keeping it that way is what
makes swapping the ``.env`` file for OpenBao/Vault a single-file change later.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


# Both naming schemes are accepted so the tool works with an existing UDM_*
# credential file or with UNIFI_* names from other UniFi tooling.
_ALIASES: dict[str, tuple[str, ...]] = {
    "host": ("UNIFI_HOST", "UDM_HOST"),
    "api_key": ("UNIFI_API_KEY", "UDM_API_KEY"),
    "site": ("UNIFI_SITE", "UDM_SITE"),
    "verify": ("UNIFI_VERIFY_TLS", "UDM_VERIFY_TLS"),
}

# Searched in order; the first existing file wins. Set UNIFI_MAP_ENV to point at
# a credential file kept outside the project directory.
ENV_FILE_VAR = "UNIFI_MAP_ENV"


def default_env_files() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get(ENV_FILE_VAR)
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path.home() / ".config" / "unifi-map" / "env")
    return candidates


def _first(
    keys: tuple[str, ...], values: dict[str, str], used: list[str] | None = None
) -> str | None:
    """First non-empty value among *keys*, so either naming scheme works.

    The first name in each tuple is the current one. Anything after it is a
    legacy spelling, and resolving from one appends it to *used* so the caller
    can say so once rather than per variable.
    """
    for index, key in enumerate(keys):
        value = values.get(key)
        if value:
            if index > 0 and used is not None:
                used.append(key)
            return value
    return None


def _warn_deprecated(used: list[str]) -> None:
    """Name the legacy variables in one line, with what to use instead.

    One message rather than one per variable: a credential file written before
    the rename uses the old spelling for everything, and four warnings for a
    single decision is noise rather than information.

    No removal date is promised, deliberately. Everything about this interface
    is unstable before 1.0, and committing to a version here would be a promise
    made for the sake of sounding organised.
    """
    if not used:
        return
    current = {legacy: keys[0] for keys in _ALIASES.values() for legacy in keys[1:]}
    pairs = ", ".join(f"{name} -> {current[name]}" for name in used)
    log.warning(
        "Using deprecated environment variable names (%s). They still work, and "
        "will be removed in a future version. The UNIFI_ spelling is the "
        "supported one.",
        pairs,
    )


@dataclass(frozen=True)
class ExporterConfig:
    host: str
    api_key: str
    site: str = "default"
    verify_tls: bool | str = True

    @property
    def base_url(self) -> str:
        host = self.host
        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return host.rstrip("/")


def _parse_verify(raw: str) -> bool | str:
    """Interpret UNIFI_VERIFY_TLS as a bool, or a path to a CA bundle."""
    lowered = raw.strip().lower()
    if lowered in {"false", "0", "no", "off", ""}:
        return False
    if lowered in {"true", "1", "yes", "on"}:
        return True
    # Anything else is treated as a CA bundle path, which requests accepts
    # directly in place of a bool.
    return raw.strip()


def _warn_if_readable_by_others(path: Path) -> None:
    """Say so if a credential file is not private.

    The file holds an API key carrying the permissions of the account that
    created it, and UniFi offers no narrower scope. A plain `cp` of the example
    file inherits the user's umask, which on most systems leaves it
    world-readable, so this is the likely state rather than an unusual one.

    A warning rather than a refusal: the file may be deliberately shared in some
    setups, and failing outright would be worse than saying what is true.
    Windows has no meaningful equivalent, so the check is skipped there.
    """
    if os.name != "posix":
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        log.warning(
            "%s is readable by other users (mode %o). It holds an API key with "
            "your account's permissions. Fix with: chmod 600 %s",
            path,
            mode & 0o777,
            path,
        )


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from *path*.

    Deliberately returns a mapping rather than writing into `os.environ`. An
    API key placed in the process environment is inherited by every child
    process this tool starts, which includes Graphviz, and Graphviz is resolved
    from `PATH`. Keeping the key out of the environment means a compromised or
    shadowed `dot` has nothing to read.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    _warn_if_readable_by_others(path)
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_config(env_file: Path | None = None) -> ExporterConfig:
    """Build config from *env_file*, or the first file in the default search path.

    Real environment variables always win over file contents, so a one-off run
    can override a credential without editing any file.
    """
    searched: list[Path] = [env_file] if env_file is not None else default_env_files()
    from_file: dict[str, str] = {}
    for candidate in searched:
        if candidate.is_file():
            # Named because `./.env` is searched before the home config, so
            # running from an unfamiliar directory can pick up its credentials
            # rather than yours. Knowing which file was read makes that visible
            # instead of surprising.
            log.info("Reading credentials from %s", candidate)
            from_file = read_dotenv(candidate)
            break

    # Real environment variables win over file contents, so a one-off run can
    # override a credential without editing anything. Merged here rather than
    # pushed into os.environ, so the key never becomes inheritable.
    values = {**from_file, **{k: v for k, v in os.environ.items() if v}}

    legacy: list[str] = []
    host = _first(_ALIASES["host"], values, legacy)
    api_key = _first(_ALIASES["api_key"], values, legacy)

    locations = ", ".join(str(p) for p in searched)
    missing = [
        name
        for name, value in (("host (UNIFI_HOST)", host), ("API key (UNIFI_API_KEY)", api_key))
        if not value
    ]
    if missing:
        raise ConfigError(
            "Missing required configuration: "
            + ", ".join(missing)
            + f". Checked the environment and: {locations}. "
            "Create .env with `install -m 600 .env.example .env`, or set "
            f"{ENV_FILE_VAR} to a credential file."
        )

    _warn_deprecated(legacy)

    assert host and api_key  # narrowed above
    if api_key == "CHANGE_ME":
        raise ConfigError("UNIFI_API_KEY is still the placeholder value CHANGE_ME.")

    return ExporterConfig(
        host=host,
        api_key=api_key,
        site=_first(_ALIASES["site"], values, legacy) or "default",
        verify_tls=_parse_verify(_first(_ALIASES["verify"], values, legacy) or "true"),
    )
