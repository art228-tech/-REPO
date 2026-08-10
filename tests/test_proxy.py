import requests

from elevenlabs_voiceover.api_client import (
    ElevenLabsClient,
    _explain_network_error,
    apply_proxy,
    describe_route,
    hide_credentials,
)
from elevenlabs_voiceover.config import Settings, normalize_proxy_url

KEY = "sk_test_key_1234567890"


# ----------------------------------------------------------------------
# Разбор адреса
# ----------------------------------------------------------------------
def test_empty_proxy_stays_empty():
    assert normalize_proxy_url("") == ""
    assert normalize_proxy_url("   ") == ""


def test_bare_host_and_port_gets_http_scheme():
    assert normalize_proxy_url("127.0.0.1:1080") == "http://127.0.0.1:1080"


def test_socks_scheme_is_preserved():
    assert normalize_proxy_url("socks5h://127.0.0.1:1080") == "socks5h://127.0.0.1:1080"


def test_scheme_is_lowercased():
    assert normalize_proxy_url("HTTP://proxy.local:3128") == "http://proxy.local:3128"


def test_unsupported_scheme_is_dropped():
    assert normalize_proxy_url("ftp://proxy") == ""


def test_scheme_without_host_is_dropped():
    assert normalize_proxy_url("socks5://") == ""


def test_credentials_survive_normalisation():
    assert normalize_proxy_url("socks5://user:pass@host:1080") == "socks5://user:pass@host:1080"


# ----------------------------------------------------------------------
# Запись адрес:порт:логин:пароль — в таком виде прокси обычно и продают.
# Именно на ней программа падала.
# ----------------------------------------------------------------------
def test_seller_format_becomes_url():
    assert normalize_proxy_url("1.2.3.4:8000:wVgThP:kjSdfL") == "http://wVgThP:kjSdfL@1.2.3.4:8000"


def test_seller_format_with_scheme():
    assert (
        normalize_proxy_url("socks5://1.2.3.4:8000:wVgThP:kjSdfL")
        == "socks5://wVgThP:kjSdfL@1.2.3.4:8000"
    )


def test_seller_format_with_hostname():
    assert (
        normalize_proxy_url("proxy.example.com:3128:vasya:secret")
        == "http://vasya:secret@proxy.example.com:3128"
    )


def test_seller_format_requires_numeric_port():
    assert normalize_proxy_url("host:порт:user:pass") == ""


def test_three_parts_are_rejected():
    assert normalize_proxy_url("host:8000:token") == ""


def test_non_numeric_port_is_rejected():
    assert normalize_proxy_url("1.2.3.4:порт") == ""


def test_host_without_port_is_accepted():
    assert normalize_proxy_url("proxy.local") == "http://proxy.local"


def test_ipv6_address_survives():
    assert normalize_proxy_url("[::1]:8080") == "http://[::1]:8080"


def test_ipv6_without_closing_bracket_is_rejected():
    assert normalize_proxy_url("[::1:8080") == ""


def test_trailing_slash_is_trimmed():
    assert normalize_proxy_url("http://127.0.0.1:8080/") == "http://127.0.0.1:8080"


def test_scheme_only_is_rejected():
    assert normalize_proxy_url("socks5://") == ""


def test_settings_normalise_proxy():
    assert Settings(proxy_url=" 127.0.0.1:1080 ").proxy_url == "http://127.0.0.1:1080"


def test_settings_drop_broken_proxy():
    assert Settings(proxy_url="ftp://nope").proxy_url == ""


def test_proxy_survives_save_and_load(tmp_path):
    path = tmp_path / "config.json"
    Settings(proxy_url="socks5h://127.0.0.1:1080", ignore_system_proxy=True).save(path)

    loaded = Settings.load(path)
    assert loaded.proxy_url == "socks5h://127.0.0.1:1080"
    assert loaded.ignore_system_proxy is True


# ----------------------------------------------------------------------
# Скрытие учётных данных
# ----------------------------------------------------------------------
def test_credentials_are_hidden():
    hidden = hide_credentials("socks5://user:secret@proxy.local:1080")
    assert "secret" not in hidden
    assert "user" not in hidden
    assert "proxy.local:1080" in hidden


def test_plain_proxy_is_shown_as_is():
    assert hide_credentials("http://127.0.0.1:8080") == "http://127.0.0.1:8080"


def test_hide_credentials_never_raises():
    # Функция вызывается при создании клиента: исключение здесь роняет запуск
    # ещё до первого запроса. Именно так и падала прошлая версия.
    for value in (
        "1.2.3.4:8000:wVgThP:kjSdfL",
        "http://1.2.3.4:8000:wVgThP:kjSdfL",
        "[::1",
        "host:порт",
        "://",
        ":::::",
        "",
        None,
    ):
        assert isinstance(hide_credentials(value), str)


def test_hide_credentials_on_seller_format():
    assert hide_credentials("http://1.2.3.4:8000:wVgThP:kjSdfL") == "http://1.2.3.4:8000:wVgThP:kjSdfL"


def test_describe_route_never_raises_on_broken_input():
    for value in ("1.2.3.4:8000:u:p", "[::1", "://", ":::::"):
        assert isinstance(describe_route(value), str)


def test_client_starts_with_unparsed_proxy():
    # Раньше такой адрес ронял конструктор клиента.
    client = ElevenLabsClient(KEY, proxy_url="1.2.3.4:8000:wVgThP:kjSdfL")
    try:
        assert client._session.proxies["https"] == "1.2.3.4:8000:wVgThP:kjSdfL"
    finally:
        client.close()


def test_settings_convert_seller_format_before_use():
    settings = Settings(proxy_url="1.2.3.4:8000:wVgThP:kjSdfL")
    client = ElevenLabsClient(KEY, proxy_url=settings.proxy_url)
    try:
        assert client._session.proxies["https"] == "http://wVgThP:kjSdfL@1.2.3.4:8000"
    finally:
        client.close()


def test_password_never_reaches_the_log():
    settings = Settings(proxy_url="1.2.3.4:8000:wVgThP:kjSdfL")
    route = describe_route(settings.proxy_url)
    assert "kjSdfL" not in route
    assert "wVgThP" not in route
    assert "1.2.3.4:8000" in route


# ----------------------------------------------------------------------
# Применение к сессии
# ----------------------------------------------------------------------
def test_own_proxy_is_applied_to_session():
    session = requests.Session()
    apply_proxy(session, "socks5h://127.0.0.1:1080")

    assert session.proxies == {"http": "socks5h://127.0.0.1:1080", "https": "socks5h://127.0.0.1:1080"}
    # Свой прокси должен вытеснить системный, иначе смысл настройки теряется.
    assert session.trust_env is False


def test_no_proxy_leaves_session_alone():
    session = requests.Session()
    apply_proxy(session, "")

    assert session.proxies == {}
    assert session.trust_env is True


def test_system_proxy_can_be_switched_off():
    session = requests.Session()
    apply_proxy(session, "", ignore_system_proxy=True)

    assert session.proxies == {}
    assert session.trust_env is False


def test_client_uses_given_proxy():
    client = ElevenLabsClient(KEY, proxy_url="socks5h://127.0.0.1:1080")
    try:
        assert client._session.proxies["https"] == "socks5h://127.0.0.1:1080"
    finally:
        client.close()


def test_client_can_ignore_system_proxy():
    client = ElevenLabsClient(KEY, ignore_system_proxy=True)
    try:
        assert client._session.trust_env is False
    finally:
        client.close()


# ----------------------------------------------------------------------
# Описание маршрута
# ----------------------------------------------------------------------
def test_route_names_own_proxy():
    assert "127.0.0.1:1080" in describe_route("socks5h://127.0.0.1:1080")


def test_route_hides_proxy_password():
    assert "secret" not in describe_route("socks5://user:secret@host:1080")


def test_route_mentions_disabled_system_proxy():
    assert "отключён" in describe_route("", ignore_system_proxy=True)


def test_route_without_proxy(monkeypatch):
    from elevenlabs_voiceover import api_client

    monkeypatch.setattr(api_client.requests.utils, "getproxies", lambda: {})
    assert describe_route("") == "напрямую"


# ----------------------------------------------------------------------
# Объяснение сетевых ошибок
# ----------------------------------------------------------------------
def test_connection_reset_is_named_as_filtering():
    exc = requests.exceptions.ConnectionError("('Connection aborted.', ConnectionResetError(10054, ...))")
    text = _explain_network_error(exc)
    assert "фильтрация трафика" in text
    assert "VPN" in text


def test_tls_eof_is_named_as_filtering():
    exc = requests.exceptions.SSLError("EOF occurred in violation of protocol")
    assert "фильтрация трафика" in _explain_network_error(exc)


def test_timeout_is_named_plainly():
    exc = requests.exceptions.Timeout("Read timed out.")
    assert "не дождались" in _explain_network_error(exc)


def test_dns_failure_is_named():
    exc = requests.exceptions.ConnectionError("Failed to resolve: [Errno -2] Name or service not known")
    assert "DNS" in _explain_network_error(exc)


def test_proxy_failure_points_at_settings():
    exc = requests.exceptions.ProxyError("Unable to connect to proxy")
    assert "прокси" in _explain_network_error(exc)


def test_unknown_error_is_passed_through():
    assert "что-то своё" in _explain_network_error(RuntimeError("что-то своё"))
