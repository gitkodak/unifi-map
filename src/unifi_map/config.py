"""Environment handling.

This is the only module that reads ``os.environ``. Keeping it that way is what
makes swapping the ``.env`` file for OpenBao/Vault a single-file change later.
"""

from __future__ import annotations

import datetime
import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


# The credential variables. `UDM_*` spellings were accepted until 0.9.0 and
# warned from 0.7.0; they are gone. Anyone still on them gets the ordinary
# "missing required configuration" error, which names the variable to set.
_VARS: dict[str, str] = {
    "host": "UNIFI_HOST",
    "api_key": "UNIFI_API_KEY",
    "site": "UNIFI_SITE",
    "verify": "UNIFI_VERIFY_TLS",
}

# Settings that are not credentials: they change what gets drawn or where files
# land. Kept apart from the variables above because those are needed only for a
# live fetch, while these apply to `render` too, which needs no credentials.
#
# `UNIFI_*` is the controller's namespace and `UNIFI_MAP_*` is ours, which is
# the rule `UNIFI_MAP_ENV` already followed. Three of these shipped under the
# controller prefix before that line was drawn; see `_LEGACY_SETTING_VARS`.
_SETTING_VARS: dict[str, str] = {
    "cache_dir": "UNIFI_MAP_CACHE_DIR",
    "asset_cache": "UNIFI_MAP_ASSET_CACHE",
    "out_dir": "UNIFI_MAP_OUT_DIR",
    "overrides": "UNIFI_MAP_OVERRIDES",
    "theme": "UNIFI_MAP_THEME",
    "layout": "UNIFI_MAP_LAYOUT",
    "icons": "UNIFI_MAP_ICONS",
    "formats": "UNIFI_MAP_FORMATS",
}

# Accepted, warned about, and slated for removal. Same treatment the `UDM_*`
# credential aliases got: warn for a release or two, then delete. Kept because
# they are documented in `docs/credentials.md` and are in real credential files
# already, so dropping them outright would break a working setup silently.
_LEGACY_SETTING_VARS: dict[str, str] = {
    "cache_dir": "UNIFI_CACHE_DIR",
    "asset_cache": "UNIFI_ASSET_CACHE",
    "out_dir": "UNIFI_OUT_DIR",
}

# Settings whose value is a filesystem path, so `~` is expanded and the value
# becomes a `Path`. Everything else stays a string for the CLI to validate:
# this module deliberately does not know what a legal theme is, because the
# choices live beside the arguments in `cli.py` and duplicating them here is
# how the two would drift.
_PATH_SETTINGS = frozenset({"cache_dir", "asset_cache", "out_dir", "overrides"})

# Settings taking several values. Written space-separated in the environment,
# matching how they are typed on the command line (`-f svg pdf png`), and as a
# real TOML array in the config file.
_LIST_SETTINGS = frozenset({"formats"})

# Searched in order; the first existing file wins. Set UNIFI_MAP_ENV to point at
# a credential file kept outside the project directory.
ENV_FILE_VAR = "UNIFI_MAP_ENV"

# Preferences, as opposed to credentials. A separate file from `env` on purpose:
# one holds an API key and wants mode 600, the other is a handful of harmless
# display choices somebody may well want in a dotfiles repository.
CONFIG_FILE_VAR = "UNIFI_MAP_CONFIG"


def default_env_files() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get(ENV_FILE_VAR)
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(Path.cwd() / ".env")
    candidates.append(config_home() / "env")
    return candidates


def config_home() -> Path:
    """Where our own files live, honouring `XDG_CONFIG_HOME`."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "unifi-map"


def default_config_file() -> Path:
    override = os.environ.get(CONFIG_FILE_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return config_home() / "config.toml"


def _value(key: str, values: dict[str, str]) -> str | None:
    """The value for *key*, treating empty as absent.

    An empty assignment in a credential file (`UNIFI_SITE=`) reads as "not set"
    rather than as the empty string, which is what somebody commenting a line
    out halfway means by it.
    """
    return values.get(key) or None


@dataclass(frozen=True)
class ExporterConfig:
    host: str
    api_key: str
    site: str = "default"
    verify_tls: bool | str = True

    @property
    def base_url(self) -> str:
        host = self.host
        # A controller is never contacted over plaintext HTTP.  Treating an
        # explicit legacy scheme as its HTTPS endpoint keeps a mistyped
        # credential file from silently weakening the connection.
        insecure_scheme = "http" + "://"
        if host.startswith(insecure_scheme):
            host = f"https://{host.removeprefix(insecure_scheme)}"
        elif not host.startswith("https://"):
            host = f"https://{host}"
        return host.rstrip("/")


@dataclass(frozen=True)
class Resolved:
    """One setting, and where it came from.

    The source is carried because a value arriving from somewhere the reader is
    not looking is the whole cost of supporting a config file and environment
    variables at all. `cmd_render` prints it, which is what makes "why does it
    look different on your machine" answerable in one line.
    """

    value: object
    source: str


def _coerce_setting(key: str, raw: object, *, from_toml: bool) -> object:
    """Turn a config-file or environment value into what the CLI expects.

    Values are shaped here and validated in `cli.py`, which is where the legal
    themes and layouts are declared. This function will happily return
    ``"chartreuse"`` for a theme; the parser is what rejects it.
    """
    if key in _LIST_SETTINGS:
        if from_toml and isinstance(raw, list):
            return [str(item) for item in raw]
        if isinstance(raw, list):
            return [str(item) for item in raw]
        # Space-separated, matching how it is typed: `-f svg pdf png`.
        return str(raw).split()
    if key in _PATH_SETTINGS:
        return Path(str(raw).strip()).expanduser()
    return str(raw).strip()


def read_config_file(path: Path) -> dict[str, object]:
    """Parse a preferences file, refusing anything it does not recognise.

    Loud on an unknown key, matching the overrides loader. A typo in a
    preferences file is otherwise indistinguishable from the setting having no
    effect, and silently ignoring it is how somebody spends an afternoon
    wondering why `them = "dark"` does nothing.
    """
    if not path.is_file():
        return {}
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot be read: {exc}") from exc

    unknown = sorted(set(payload) - set(_SETTING_VARS))
    if unknown:
        known = ", ".join(sorted(_SETTING_VARS))
        raise ConfigError(
            f"{path}: unknown key(s) {', '.join(repr(k) for k in unknown)}. Accepts: {known}."
        )
    return payload


def resolved_settings(
    env_file: Path | None = None, config_file: Path | None = None
) -> dict[str, Resolved]:
    """Non-credential settings, from the environment or a config file.

    Separate from `load_config` because that requires a host and an API key and
    raises without them, while these apply to `render`, which needs neither.

    The motivating case for the directory settings: a snapshot is a complete
    inventory of a network, and the default cache sits inside the working
    directory, which for anyone working on this tool is a git repository.
    Pointing it somewhere else should not mean retyping a flag every time.

    Precedence within this function is environment over config file. A flag
    beats both, which `cli.py` arranges by only consulting this for settings no
    flag supplied. Environment above file is deliberate and is the container
    case: a config file can be baked into an image and overridden per
    deployment with `-e`, which does not work the other way round.

    Note the settings are independent. Setting only the snapshot cache leaves
    artwork in `cache/assets`, because the two are deliberately separate:
    `--cache-dir examples/demo` must not cause downloads to be written into the
    shipped demo dataset.
    """
    searched: list[Path] = [env_file] if env_file is not None else default_env_files()
    from_env_file: dict[str, str] = {}
    env_file_path: Path | None = None
    for candidate in searched:
        if candidate.is_file():
            from_env_file = read_dotenv(candidate)
            env_file_path = candidate
            break

    path = config_file if config_file is not None else default_config_file()
    from_config = read_config_file(path)

    resolved: dict[str, Resolved] = {}
    for key, name in _SETTING_VARS.items():
        legacy = _LEGACY_SETTING_VARS.get(key)

        raw: object | None = None
        source: str | None = None
        for candidate_name, where in (
            (name, "environment"),
            (legacy, "environment"),
        ):
            if candidate_name is None:
                continue
            value = os.environ.get(candidate_name)
            if value is None or not value.strip():
                value = from_env_file.get(candidate_name)
                where = f"credential file {env_file_path}" if env_file_path else where
            if value is not None and value.strip():
                if candidate_name == legacy:
                    log.warning(
                        "%s is deprecated; rename it to %s. The old name still "
                        "works but will be removed.",
                        legacy,
                        name,
                    )
                raw, source = value, f"{where} ({candidate_name})"
                break

        if raw is not None:
            resolved[key] = Resolved(_coerce_setting(key, raw, from_toml=False), source or "")
            continue

        if key in from_config:
            resolved[key] = Resolved(
                _coerce_setting(key, from_config[key], from_toml=True),
                f"config file {path}",
            )
    return resolved


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


# Not every variable this module reads is about reaching a controller. This one
# changes nothing about the data and is off unless deliberately set.
_FLOURISH_VAR = "HOOPY_FROOD"


def source_date() -> datetime.datetime | None:
    """`SOURCE_DATE_EPOCH` as a local datetime, or None.

    The reproducible-builds convention. A rendered map stamps itself with the
    time it was drawn, which is right for a real map and wrong for one committed
    to a repository: regenerating it produced a diff every run, from the clock
    alone, so a genuine rendering change was indistinguishable from a tick.

    Read here because this module owns the environment.
    """
    raw = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if not raw.isdigit():
        return None
    return datetime.datetime.fromtimestamp(int(raw), datetime.UTC)


def flourish() -> str | None:
    """A rendering nicety, or None. Read here because this module owns the
    environment; see the note at the top of `cli.py` about why that matters."""
    return os.environ.get(_FLOURISH_VAR) or None


def load_config(env_file: Path | None = None, site: str | None = None) -> ExporterConfig:
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

    host = _value(_VARS["host"], values)
    api_key = _value(_VARS["api_key"], values)

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

    assert host and api_key  # narrowed above
    if api_key == "CHANGE_ME":
        raise ConfigError("UNIFI_API_KEY is still the placeholder value CHANGE_ME.")

    return ExporterConfig(
        host=host,
        api_key=api_key,
        # An explicit --site beats the environment, which beats the default.
        # Resolved here rather than in the CLI so precedence lives in one
        # place alongside the environment lookup it is competing with.
        site=site or _value(_VARS["site"], values) or "default",
        verify_tls=_parse_verify(_value(_VARS["verify"], values) or "true"),
    )
