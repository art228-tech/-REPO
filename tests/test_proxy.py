from __future__ import annotations

import pytest

from tgparser.userbot.proxy import ProxyError, parse_proxy, redact_proxy


class TestParseProxy:
    def test_none_and_blank(self):
        assert parse_proxy(None) is None
        assert parse_proxy("   ") is None

    def test_bare_host_port_defaults_to_socks5(self):
        assert parse_proxy("1.2.3.4:1080") == {
            "proxy_type": "socks5",
            "addr": "1.2.3.4",
            "port": 1080,
            "rdns": True,
        }

    def test_with_credentials(self):
        config = parse_proxy("socks5://user:pass@1.2.3.4:1080")
        assert config["username"] == "user"
        assert config["password"] == "pass"

    def test_percent_encoded_credentials(self):
        config = parse_proxy("socks5://user:p%40ss@1.2.3.4:1080")
        assert config["password"] == "p@ss"

    def test_https_maps_to_http(self):
        assert parse_proxy("https://1.2.3.4:8080")["proxy_type"] == "http"

    @pytest.mark.parametrize(
        ("raw", "match"),
        [
            ("ftp://1.2.3.4:21", "схема"),
            ("socks5://:1080", "хост"),
            ("socks5://1.2.3.4", "порт"),
        ],
    )
    def test_rejects_bad_input(self, raw, match):
        with pytest.raises(ProxyError, match=match):
            parse_proxy(raw)


class TestRedactProxy:
    def test_password_is_hidden(self):
        assert redact_proxy("socks5://user:secret@1.2.3.4:1080") == (
            "socks5://user:***@1.2.3.4:1080"
        )
        assert "secret" not in redact_proxy("socks5://user:secret@1.2.3.4:1080")

    def test_without_credentials(self):
        assert redact_proxy("1.2.3.4:1080") == "socks5://1.2.3.4:1080"

    def test_none(self):
        assert redact_proxy(None) == "нет"

    def test_invalid(self):
        assert redact_proxy("ftp://x:1") == "некорректный"
