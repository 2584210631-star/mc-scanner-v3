# -*- coding: utf-8 -*-
import config as config_mod


def test_env_override_web_token(monkeypatch):
    config_mod._GLOBAL_CFG = None
    config_mod._CONFIG_PATH = None
    monkeypatch.setenv("MC_WEB_TOKEN", "test-token-xyz")
    cfg = config_mod.load_config()
    assert cfg.get("web_token") == "test-token-xyz"
    config_mod._GLOBAL_CFG = None
    config_mod._CONFIG_PATH = None


def test_default_rate_positive():
    cfg = config_mod.DEFAULT_CONFIG
    assert cfg.get("rate", 0) > 0
    assert "ai_reply_cooldown" in cfg
