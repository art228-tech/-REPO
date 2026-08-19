from elevenlabs_voiceover.logging_setup import forget_secrets, redact, register_secret


def teardown_function():
    forget_secrets()


def test_sk_key_is_redacted():
    text = "Отправляю запрос с ключом sk_abcdef0123456789abcdef и жду ответ"
    assert "sk_abcdef0123456789abcdef" not in redact(text)
    assert "REDACTED" in redact(text)


def test_header_form_is_redacted():
    assert "supersecretvalue" not in redact("xi-api-key: supersecretvalue")


def test_json_form_is_redacted():
    assert "abcdef1234567890" not in redact('{"api_key": "abcdef1234567890"}')


def test_registered_secret_is_redacted_even_in_odd_format():
    register_secret("ZZZ-custom-token-9999")
    assert "ZZZ-custom-token-9999" not in redact("токен ZZZ-custom-token-9999 внутри строки")


def test_short_values_are_not_registered():
    register_secret("abc")
    assert redact("значение abc осталось") == "значение abc осталось"


def test_plain_text_is_untouched():
    text = "Обычное сообщение без секретов"
    assert redact(text) == text


def test_empty_input():
    assert redact("") == ""


def test_multiple_keys_in_one_line():
    text = "первый sk_aaaaaaaaaaaaaaaa второй sk_bbbbbbbbbbbbbbbb"
    cleaned = redact(text)
    assert "sk_aaaaaaaaaaaaaaaa" not in cleaned
    assert "sk_bbbbbbbbbbbbbbbb" not in cleaned


def test_traceback_text_is_redacted():
    text = 'File "x.py", line 1\n  headers={"xi-api-key": "sk_leak_9999999999"}'
    assert "sk_leak_9999999999" not in redact(text)
