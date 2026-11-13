"""
RAI client: loads raiconfig.toml and initialises a relationalai.Config.

The client is intentionally lazy — it does not attempt a live connection
at import time, so the service can start and the parser can run even when
RAI credentials are not available (e.g. during unit tests).

Usage
-----
    from rai.client import get_rai_config, get_model

    config = get_rai_config()           # raises ConfigError if not found
    model  = get_model("my_model")      # returns a relationalai.Model
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import toml
except ImportError:  # pragma: no cover
    toml = None  # type: ignore[assignment]


# ── Exceptions ────────────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Raised when raiconfig.toml cannot be found or is missing required keys."""


# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass
class RaiConfig:
    """Normalised connection parameters extracted from raiconfig.toml."""
    platform: str
    user: str
    account: str
    role: str
    warehouse: str
    rai_app_name: str
    engine: Optional[str]
    database: Optional[str]
    schema_: Optional[str]      # 'schema' is a Python built-in; we shadow it
    authenticator: str
    # Raw profile dict (for passing directly to the SDK)
    _raw: dict

    @property
    def snowflake_account(self) -> str:
        """Normalise account identifier for snowflake-connector-python."""
        return self.account.replace("_", "-")


# ── Discovery ─────────────────────────────────────────────────────────────────

_DEFAULT_SEARCH_PATHS = [
    Path.home() / ".rai" / "raiconfig.toml",
    Path.cwd() / "raiconfig.toml",
    Path(__file__).parent.parent.parent / "raiconfig.toml",   # repo root
]

_REQUIRED_KEYS = {"user", "account", "rai_app_name"}


def _find_config_file(override: Optional[str | Path] = None) -> Path:
    """Return the first raiconfig.toml that exists."""
    if override:
        p = Path(override)
        if not p.exists():
            raise ConfigError(f"raiconfig.toml not found at {p}")
        return p

    env_path = os.environ.get("RAI_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    for p in _DEFAULT_SEARCH_PATHS:
        if p.exists():
            return p

    searched = "\n  ".join(str(p) for p in _DEFAULT_SEARCH_PATHS)
    raise ConfigError(
        f"raiconfig.toml not found. Searched:\n  {searched}\n"
        "Set RAI_CONFIG_PATH env var to point to your config file."
    )


def load_rai_config(path: Optional[str | Path] = None) -> RaiConfig:
    """
    Load and validate raiconfig.toml.

    Parameters
    ----------
    path:
        Explicit path to override auto-discovery.  If None, searches
        ~/.rai/raiconfig.toml, $RAI_CONFIG_PATH, and repo root.
    """
    if toml is None:
        raise ConfigError("'toml' package is not installed. Run: pip install toml")

    config_path = _find_config_file(path)
    raw = toml.load(str(config_path))

    active = raw.get("active_profile", "default")
    profiles = raw.get("profile", {})

    if active not in profiles:
        raise ConfigError(
            f"active_profile '{active}' not found in {config_path}. "
            f"Available profiles: {list(profiles)}"
        )

    profile = profiles[active]

    missing = _REQUIRED_KEYS - set(profile)
    if missing:
        raise ConfigError(
            f"raiconfig.toml profile '{active}' is missing required keys: {missing}"
        )

    return RaiConfig(
        platform=profile.get("platform", "snowflake"),
        user=profile["user"],
        account=profile["account"],
        role=profile.get("role", "ACCOUNTADMIN"),
        warehouse=profile.get("warehouse", ""),
        rai_app_name=profile["rai_app_name"],
        engine=profile.get("engine"),
        database=profile.get("database"),
        schema_=profile.get("schema"),
        authenticator=profile.get("authenticator", "snowflake"),
        _raw=profile,
    )


# ── Model factory ─────────────────────────────────────────────────────────────

def get_rai_model(model_name: str, config: Optional[RaiConfig] = None):
    """
    Return a ``relationalai.Model`` connected via the given (or auto-loaded) config.

    This import is deferred so the module can be loaded without relationalai
    installed (useful in test environments that mock the SDK).
    """
    try:
        import relationalai as rai  # type: ignore[import]
    except ImportError as exc:
        raise ConfigError(
            "relationalai package is not installed. "
            "Run: pip install relationalai"
        ) from exc

    cfg = config or load_rai_config()

    rai_config = rai.Config(
        account=cfg.account,
        user=cfg.user,
        role=cfg.role,
        warehouse=cfg.warehouse,
        rai_app=cfg.rai_app_name,
        engine=cfg.engine or "",
        database=cfg.database or "",
        schema=cfg.schema_ or "API",
        authenticator=cfg.authenticator,
    )

    return rai.Model(model_name, config=rai_config)
