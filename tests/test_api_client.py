import base64
import json

import pytest
import requests

from elevenlabs_voiceover.api_client import ElevenLabsClient
from elevenlabs_voiceover.errors import (
    AuthError,
    ElevenLabsError,
    InvalidResponse,
    NetworkError,
    QuotaExceeded,
    ScopeError,
    ServerError,
    ValidationFailed,
    VoiceLimitReached,
)


def response(status=200, json_body=None, content=b"", headers=None, reason=""):
    resp = requests.Response()
    resp.status_code = status
    resp.reason = reason
    resp.headers.update(headers or {})
    if json_body is not None:
        resp._content = json.dumps(json_body).encode("utf-8")
        resp.headers["Content-Type"] = "application/json"
    else:
        resp._content = content
    return resp


class FakeSession:
    """Отдаёт заранее подготовленные ответы по очереди.

    Когда очередь исчерпана, повторяет последний ответ: иначе тест на повторы
    незаметно получал бы успех и проверял не то, что задумано.
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self):
        pass


@pytest.fixture
def client():
    instance = ElevenLabsClient("sk_test_key_1234567890", max_retries=3)
    # Ретраи не должны замедлять тесты.
    instance._sleep = lambda seconds: None
    return instance


def use(client, *outcomes) -> FakeSession:
    session = FakeSession(outcomes)
    client._session = session
    return session


# ----------------------------------------------------------------------
def test_empty_key_is_rejected():
    with pytest.raises(AuthError):
        ElevenLabsClient("   ")


def test_key_goes_into_header():
    instance = ElevenLabsClient("sk_test_key_1234567890")
    assert instance._session.headers["xi-api-key"] == "sk_test_key_1234567890"
    instance.close()


# ----------------------------------------------------------------------
def test_quota_exceeded_by_status_field(client):
    use(client, response(401, {"detail": {"status": "quota_exceeded", "message": "нет кредитов"}}))
    with pytest.raises(QuotaExceeded):
        client.get_subscription()


def test_quota_exceeded_by_message_text(client):
    use(client, response(401, {"detail": "You have exceeded your quota"}))
    with pytest.raises(QuotaExceeded):
        client.get_subscription()


def test_missing_permissions_is_scope_error(client):
    use(client, response(401, {"detail": {"status": "missing_permissions", "message": "нет прав"}}))
    with pytest.raises(ScopeError):
        client.get_subscription()


def test_ip_restriction_is_scope_error(client):
    use(client, response(403, {"detail": {"status": "ip_not_allowed", "message": "чужой ip"}}))
    with pytest.raises(ScopeError):
        client.get_subscription()


def test_invalid_key_is_auth_error(client):
    use(client, response(401, {"detail": {"status": "invalid_api_key", "message": "ключ неверен"}}))
    with pytest.raises(AuthError):
        client.get_subscription()


def test_voice_limit_is_own_error(client):
    use(client, response(400, {"detail": {"status": "voice_limit_reached", "message": "слотов нет"}}))
    with pytest.raises(VoiceLimitReached):
        client.get_subscription()


def test_validation_error_is_not_retried(client):
    session = use(client, response(422, {"detail": [{"loc": ["body", "text"], "msg": "пусто", "type": "value_error"}]}))
    with pytest.raises(ValidationFailed) as exc:
        client.get_subscription()
    assert len(session.calls) == 1
    assert "text" in str(exc.value)


def test_fatal_errors_are_not_retried(client):
    session = use(
        client,
        response(401, {"detail": {"status": "invalid_api_key"}}),
        response(200, {"tier": "free"}),
    )
    with pytest.raises(AuthError):
        client.get_subscription()
    assert len(session.calls) == 1


# ----------------------------------------------------------------------
def test_rate_limit_is_retried_then_succeeds(client):
    session = use(
        client,
        response(429, {"detail": "too many"}, headers={"Retry-After": "0"}),
        response(200, _subscription_body()),
    )
    result = client.get_subscription()
    assert len(session.calls) == 2
    assert result.tier == "free"


def test_server_error_is_retried(client):
    session = use(
        client,
        response(500, {"detail": "internal"}),
        response(502, {"detail": "bad gateway"}),
        response(200, _subscription_body()),
    )
    client.get_subscription()
    assert len(session.calls) == 3


def test_retries_give_up_after_limit(client):
    session = use(client, *[response(500, {"detail": "internal"}) for _ in range(10)])
    with pytest.raises(ServerError):
        client.get_subscription()
    assert len(session.calls) == 4  # первая попытка плюс три повтора


def test_network_error_is_retried(client):
    session = use(
        client,
        requests.exceptions.ConnectionError("сеть недоступна"),
        response(200, _subscription_body()),
    )
    client.get_subscription()
    assert len(session.calls) == 2


def test_timeout_is_network_error(client):
    use(client, *[requests.exceptions.Timeout("долго") for _ in range(10)])
    with pytest.raises(NetworkError):
        client.get_subscription()


def test_retry_after_header_is_respected(client):
    delays = []
    client._sleep = lambda seconds: delays.append(seconds)
    use(
        client,
        response(429, {"detail": "slow down"}, headers={"Retry-After": "7"}),
        response(200, _subscription_body()),
    )
    client.get_subscription()
    assert delays == [7.0]


def test_html_page_instead_of_json_is_explained(client):
    page = b"<!DOCTYPE html><html><head><title>Blocked</title></head><body>nope</body></html>"
    use(client, response(200, content=page, headers={"Content-Type": "text/html; charset=utf-8"}))

    with pytest.raises(InvalidResponse) as exc:
        client.get_subscription()

    message = str(exc.value)
    assert "веб-страница" in message
    assert "text/html" in message
    # В сообщении должно быть начало ответа, иначе причину не разобрать.
    assert "DOCTYPE" in message


def test_cloudflare_page_is_named(client):
    page = b"<html><body>Attention Required! | Cloudflare</body></html>"
    use(client, response(200, content=page, headers={"cf-ray": "8a2b3c4d", "Content-Type": "text/html"}))

    with pytest.raises(InvalidResponse) as exc:
        client.get_subscription()
    assert "Cloudflare" in str(exc.value)


def test_plain_garbage_body_is_reported(client):
    use(client, response(200, content=b"\x00\x01\x02 not json at all",
                         headers={"Content-Type": "application/octet-stream"}))

    with pytest.raises(InvalidResponse) as exc:
        client.get_subscription()
    assert "не похоже ни на JSON" in str(exc.value)


def test_bad_body_is_retried(client):
    session = use(
        client,
        response(200, content="<html>перехват</html>".encode(), headers={"Content-Type": "text/html"}),
        response(200, _subscription_body()),
    )

    result = client.get_subscription()

    assert result.tier == "free"
    assert len(session.calls) == 2


def test_bad_body_gives_up_after_retries(client):
    session = use(client, response(200, content="<html>всегда так</html>".encode(),
                                   headers={"Content-Type": "text/html"}))
    with pytest.raises(InvalidResponse):
        client.get_subscription()
    assert len(session.calls) == 4


def test_api_key_is_not_leaked_into_bad_body_message(client):
    # Заглушка может отразить запрос вместе с заголовками.
    page = b"<html>rejected request with xi-api-key: sk_test_key_1234567890</html>"
    use(client, response(200, content=page, headers={"Content-Type": "text/html"}))

    with pytest.raises(InvalidResponse) as exc:
        client.get_subscription()
    assert "sk_test_key_1234567890" not in str(exc.value)


def test_empty_body_with_success_is_not_an_error(client):
    use(client, response(200, content=b""))
    assert client.list_voices() == []


def test_non_json_error_body_is_handled(client):
    use(client, response(503, content=b"<html>Service Unavailable</html>", reason="Service Unavailable"))
    with pytest.raises(ServerError) as exc:
        client.get_subscription()
    assert "Service Unavailable" in str(exc.value)


# ----------------------------------------------------------------------
def _subscription_body():
    return {
        "tier": "free",
        "status": "free",
        "character_count": 2500,
        "character_limit": 10000,
        "voice_slots_used": 1,
        "voice_limit": 3,
        "next_character_count_reset_unix": 1738356858,
        "can_use_instant_voice_cloning": False,
    }


def test_subscription_is_parsed(client):
    use(client, response(200, _subscription_body()))
    sub = client.get_subscription()

    assert sub.tier == "free"
    assert sub.credits_left == 7500
    assert sub.voice_slots_left == 2
    assert "free" in sub.summary()


def test_subscription_handles_missing_fields(client):
    use(client, response(200, {"tier": "free"}))
    sub = client.get_subscription()
    assert sub.character_limit == 0
    assert sub.credits_left == 0


def test_credits_left_never_negative(client):
    body = _subscription_body()
    body["character_count"] = 99999
    use(client, response(200, body))
    assert client.get_subscription().credits_left == 0


# ----------------------------------------------------------------------
def test_models_are_parsed_with_cost(client):
    use(client, response(200, [
        {
            "model_id": "eleven_flash_v2_5",
            "name": "Flash v2.5",
            "can_do_text_to_speech": True,
            "maximum_text_length_per_request": 40000,
            "model_rates": {"character_cost_multiplier": 1.0, "cost_discount_multiplier": 0.5},
            "languages": [{"language_id": "ru", "name": "Russian"}],
        },
        {"model_id": "scribe_v1", "can_do_text_to_speech": False},
    ]))

    models = client.list_models()
    assert len(models) == 2
    flash = models[0]
    assert flash.cost_multiplier == 0.5
    assert flash.max_chars_per_request == 40000
    assert "ru" in flash.languages


def test_models_tolerate_missing_rates(client):
    use(client, response(200, [{"model_id": "m1", "can_do_text_to_speech": True}]))
    assert client.list_models()[0].cost_multiplier == 1.0


def test_models_skip_entries_without_id(client):
    use(client, response(200, [{"name": "без id"}, {"model_id": "ok"}]))
    assert [m.model_id for m in client.list_models()] == ["ok"]


# ----------------------------------------------------------------------
def test_design_voice_parses_previews(client):
    sample = "звук".encode()
    audio = base64.b64encode(sample).decode()
    session = use(client, response(200, {
        "previews": [
            {"audio_base_64": audio, "generated_voice_id": "g1", "media_type": "audio/mpeg",
             "duration_secs": 3.5, "language": "ru"},
            {"audio_base_64": audio, "generated_voice_id": "g2", "media_type": "audio/mpeg",
             "duration_secs": 3.5, "language": "ru"},
        ],
        "text": "текст прослушивания",
    }))

    previews = client.design_voice("Спокойный мужской голос", preview_text="а" * 120)

    assert [p.generated_voice_id for p in previews] == ["g1", "g2"]
    assert previews[0].audio == sample

    body = session.calls[0][2]["json"]
    assert body["voice_description"] == "Спокойный мужской голос"
    assert body["text"] == "а" * 120
    assert "auto_generate_text" not in body


def test_design_voice_with_auto_text_omits_text(client):
    session = use(client, response(200, {
        "previews": [{"audio_base_64": "", "generated_voice_id": "g1", "media_type": "audio/mpeg",
                      "duration_secs": 1, "language": None}],
        "text": "",
    }))
    client.design_voice("Голос", auto_generate_text=True)

    body = session.calls[0][2]["json"]
    assert body["auto_generate_text"] is True
    assert "text" not in body


def test_design_voice_without_previews_raises(client):
    use(client, response(200, {"previews": [], "text": ""}))
    with pytest.raises(ElevenLabsError):
        client.design_voice("Голос", preview_text="а" * 120)


def test_design_voice_tolerates_broken_base64(client):
    use(client, response(200, {
        "previews": [{"audio_base_64": "не base64!!!", "generated_voice_id": "g1",
                      "media_type": "audio/mpeg", "duration_secs": 1, "language": None}],
        "text": "",
    }))
    assert client.design_voice("Голос", preview_text="а" * 120)[0].generated_voice_id == "g1"


# ----------------------------------------------------------------------
def test_create_voice_returns_payload(client):
    session = use(client, response(200, {"voice_id": "v-123", "name": "Диктор"}))
    created = client.create_voice_from_preview(
        voice_name="Диктор", voice_description="описание",
        generated_voice_id="g1", played_not_selected=["g2", "g3"],
    )

    assert created["voice_id"] == "v-123"
    body = session.calls[0][2]["json"]
    assert body["generated_voice_id"] == "g1"
    assert body["played_not_selected_voice_ids"] == ["g2", "g3"]


def test_create_voice_without_id_raises(client):
    use(client, response(200, {"name": "без идентификатора"}))
    with pytest.raises(ElevenLabsError):
        client.create_voice_from_preview(
            voice_name="Д", voice_description="о", generated_voice_id="g1"
        )


# ----------------------------------------------------------------------
def test_tts_returns_audio_and_request_id(client):
    payload = b"\xff\xfb" + b"\x00" * 64
    session = use(client, response(200, content=payload, headers={"request-id": "req-9"}))
    result = client.text_to_speech("v1", "Привет", model_id="eleven_flash_v2_5")

    assert result.audio == payload
    assert result.request_id == "req-9"
    assert result.characters == len("Привет")

    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/v1/text-to-speech/v1")
    assert kwargs["params"]["output_format"] == "mp3_44100_128"


def test_tts_sends_context_and_settings(client):
    session = use(client, response(200, content=b"audio"))
    client.text_to_speech(
        "v1", "текст", model_id="m",
        voice_settings={"stability": 0.4},
        previous_text="что было раньше",
        next_text="что будет дальше",
        previous_request_ids=["r1", "r2", "r3", "r4", "r5"],
        language_code="ru",
    )

    body = session.calls[0][2]["json"]
    assert body["voice_settings"] == {"stability": 0.4}
    assert body["previous_text"] == "что было раньше"
    assert body["next_text"] == "что будет дальше"
    assert body["language_code"] == "ru"
    # API принимает не больше трёх идентификаторов.
    assert body["previous_request_ids"] == ["r3", "r4", "r5"]


def test_tts_omits_optional_fields_when_absent(client):
    session = use(client, response(200, content=b"audio"))
    client.text_to_speech("v1", "текст", model_id="m")

    body = session.calls[0][2]["json"]
    assert set(body) == {"text", "model_id"}


def test_empty_audio_response_raises(client):
    use(client, response(200, content=b""))
    with pytest.raises(ElevenLabsError):
        client.text_to_speech("v1", "текст", model_id="m")


def test_tts_quota_error_propagates(client):
    use(client, response(401, {"detail": {"status": "quota_exceeded", "message": "всё"}}))
    with pytest.raises(QuotaExceeded):
        client.text_to_speech("v1", "текст", model_id="m")


# ----------------------------------------------------------------------
def test_list_voices_extracts_array(client):
    use(client, response(200, {"voices": [{"voice_id": "a"}, {"voice_id": "b"}]}))
    assert [v["voice_id"] for v in client.list_voices()] == ["a", "b"]


def test_list_voices_handles_unexpected_shape(client):
    use(client, response(200, {"нет": "голосов"}))
    assert client.list_voices() == []


def test_decoder_support_always_lists_gzip():
    from elevenlabs_voiceover.api_client import decoder_support

    assert "gzip" in decoder_support()
    assert "deflate" in decoder_support()


def test_probe_reports_healthy_api(monkeypatch):
    from elevenlabs_voiceover import api_client

    monkeypatch.setattr(
        api_client.requests, "get",
        lambda url, **kwargs: response(200, {"models": []}, headers={"Content-Type": "application/json"}),
    )

    results = api_client.probe_connection("sk_test_key_1234567890")

    assert len(results) == 3
    assert all(r.json_ok for r in results)
    assert "JSON разобран" in results[0].line()


def test_probe_without_key_checks_only_public_endpoint(monkeypatch):
    from elevenlabs_voiceover import api_client

    monkeypatch.setattr(api_client.requests, "get", lambda url, **kwargs: response(200, {"ok": True}))

    results = api_client.probe_connection("")

    assert len(results) == 1


def test_probe_exposes_non_json_body(monkeypatch):
    from elevenlabs_voiceover import api_client

    page = b"<!DOCTYPE html><html>stub page</html>"
    monkeypatch.setattr(
        api_client.requests, "get",
        lambda url, **kwargs: response(200, content=page, headers={"Content-Type": "text/html"}),
    )

    results = api_client.probe_connection("sk_test_key_1234567890")

    assert not results[0].json_ok
    line = results[0].line()
    assert "ОТВЕТ НЕ JSON" in line
    assert "DOCTYPE" in line


def test_probe_survives_network_failure(monkeypatch):
    from elevenlabs_voiceover import api_client

    def boom(url, **kwargs):
        raise requests.exceptions.ConnectionError("сеть недоступна")

    monkeypatch.setattr(api_client.requests, "get", boom)

    results = api_client.probe_connection("sk_test_key_1234567890")

    assert all(r.error for r in results)
    assert "не удалось" in results[0].line()


def test_probe_sends_key_only_where_needed(monkeypatch):
    from elevenlabs_voiceover import api_client

    seen = []

    def capture(url, **kwargs):
        seen.append((url, "xi-api-key" in kwargs.get("headers", {})))
        return response(200, {"ok": True})

    monkeypatch.setattr(api_client.requests, "get", capture)
    api_client.probe_connection("sk_test_key_1234567890")

    assert seen[0][1] is False
    assert seen[1][1] is True
    assert seen[2][0].endswith("/v1/user/subscription")


def test_probe_does_not_leak_key_into_snippet(monkeypatch):
    from elevenlabs_voiceover import api_client

    echoed = b"<html>xi-api-key: sk_test_key_1234567890</html>"
    monkeypatch.setattr(
        api_client.requests, "get",
        lambda url, **kwargs: response(200, content=echoed, headers={"Content-Type": "text/html"}),
    )

    results = api_client.probe_connection("sk_test_key_1234567890")

    assert all("sk_test_key_1234567890" not in r.snippet for r in results)


def test_proxy_summary_hides_credentials(monkeypatch):
    from elevenlabs_voiceover import api_client

    monkeypatch.setattr(
        api_client.requests.utils, "getproxies",
        lambda: {"https": "http://логин:пароль@proxy.local:8080"},
    )

    summary = api_client.safe_proxy_summary()

    assert "proxy.local:8080" in summary
    assert "пароль" not in summary


def test_proxy_summary_empty_without_proxy(monkeypatch):
    from elevenlabs_voiceover import api_client

    monkeypatch.setattr(api_client.requests.utils, "getproxies", lambda: {})
    assert api_client.safe_proxy_summary() == ""


def test_delete_voice_uses_delete_method(client):
    session = use(client, response(200, {}))
    client.delete_voice("v-1")
    assert session.calls[0][0] == "DELETE"
    assert session.calls[0][1].endswith("/v1/voices/v-1")
