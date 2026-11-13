"""
Tests for rai/client.py

All tests are offline — no live RAI/Snowflake connection required.
We test config discovery, parsing, validation, and error handling
using temporary TOML files.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from rai.client import load_rai_config, RaiConfig, ConfigError

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_TOML = """
active_profile = "default"

[profile.default]
platform = "snowflake"
user = "test.user@example.com"
account = "myorg-myaccount"
role = "MY_ROLE"
warehouse = "MY_WH"
rai_app_name = "MY_RAI_APP"
engine = "MY_ENGINE"
database = "MY_DB"
schema = "API"
authenticator = "snowflake"
"""

MULTI_PROFILE_TOML = """
active_profile = "prod"

[profile.dev]
user = "dev@example.com"
account = "dev-account"
rai_app_name = "DEV_APP"

[profile.prod]
user = "prod@example.com"
account = "prod-account"
rai_app_name = "PROD_APP"
"""

MISSING_KEYS_TOML = """
active_profile = "default"

[profile.default]
platform = "snowflake"
user = "someone@example.com"
# account and rai_app_name are missing
"""

NO_ACTIVE_PROFILE_TOML = """
active_profile = "nonexistent"

[profile.default]
user = "x@x.com"
account = "acc"
rai_app_name = "app"
"""


@pytest.fixture
def valid_config_file(tmp_path):
    p = tmp_path / "raiconfig.toml"
    p.write_text(VALID_TOML)
    return p


@pytest.fixture
def multi_profile_file(tmp_path):
    p = tmp_path / "raiconfig.toml"
    p.write_text(MULTI_PROFILE_TOML)
    return p


# ── Happy-path tests ──────────────────────────────────────────────────────────

def test_load_returns_rai_config(valid_config_file):
    cfg = load_rai_config(valid_config_file)
    assert isinstance(cfg, RaiConfig)


def test_user_extracted(valid_config_file):
    cfg = load_rai_config(valid_config_file)
    assert cfg.user == "test.user@example.com"


def test_account_extracted(valid_config_file):
    cfg = load_rai_config(valid_config_file)
    assert cfg.account == "myorg-myaccount"


def test_rai_app_name_extracted(valid_config_file):
    cfg = load_rai_config(valid_config_file)
    assert cfg.rai_app_name == "MY_RAI_APP"


def test_optional_fields_extracted(valid_config_file):
    cfg = load_rai_config(valid_config_file)
    assert cfg.engine == "MY_ENGINE"
    assert cfg.database == "MY_DB"
    assert cfg.schema_ == "API"
    assert cfg.warehouse == "MY_WH"
    assert cfg.role == "MY_ROLE"
    assert cfg.authenticator == "snowflake"


def test_active_profile_selected(multi_profile_file):
    """active_profile = "prod" should pick the prod section."""
    cfg = load_rai_config(multi_profile_file)
    assert cfg.user == "prod@example.com"
    assert cfg.rai_app_name == "PROD_APP"


def test_raw_profile_available(valid_config_file):
    cfg = load_rai_config(valid_config_file)
    assert "user" in cfg._raw


def test_snowflake_account_normalisation(valid_config_file):
    """Underscores in account names should be replaced with hyphens."""
    cfg = load_rai_config(valid_config_file)
    # "myorg-myaccount" has no underscores — should pass through unchanged
    assert "-" in cfg.snowflake_account


def test_snowflake_account_normalisation_with_underscores(tmp_path):
    toml_content = """
active_profile = "default"
[profile.default]
user = "u@u.com"
account = "myorg_myaccount_region"
rai_app_name = "APP"
"""
    p = tmp_path / "raiconfig.toml"
    p.write_text(toml_content)
    cfg = load_rai_config(p)
    assert "_" not in cfg.snowflake_account
    assert "myorg-myaccount-region" == cfg.snowflake_account


# ── Error-path tests ──────────────────────────────────────────────────────────

def test_missing_file_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_rai_config("/tmp/does_not_exist_xyz/raiconfig.toml")


def test_missing_required_keys_raises(tmp_path):
    p = tmp_path / "raiconfig.toml"
    p.write_text(MISSING_KEYS_TOML)
    with pytest.raises(ConfigError, match="missing required keys"):
        load_rai_config(p)


def test_nonexistent_active_profile_raises(tmp_path):
    p = tmp_path / "raiconfig.toml"
    p.write_text(NO_ACTIVE_PROFILE_TOML)
    with pytest.raises(ConfigError, match="not found"):
        load_rai_config(p)


# ── Real config: ~/.rai/raiconfig.toml ───────────────────────────────────────

REAL_CONFIG = Path.home() / ".rai" / "raiconfig.toml"


@pytest.mark.skipif(
    not REAL_CONFIG.exists(),
    reason="~/.rai/raiconfig.toml not present"
)
class TestRealConfig:
    @pytest.fixture(scope="class")
    def cfg(self):
        return load_rai_config(REAL_CONFIG)

    def test_loads_without_error(self, cfg):
        assert isinstance(cfg, RaiConfig)

    def test_has_user(self, cfg):
        assert cfg.user and "@" in cfg.user

    def test_has_account(self, cfg):
        assert cfg.account

    def test_has_rai_app_name(self, cfg):
        assert cfg.rai_app_name

    def test_platform_is_snowflake(self, cfg):
        assert cfg.platform == "snowflake"
