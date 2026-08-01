"""Клиент my.telegram.org: разбор страниц и все ветки отказов.

Портал — не API, а HTML-формы, поэтому проверяем именно разбор разметки и то,
что каждый вид отказа превращается в понятное сообщение с подсказкой про
ручной путь.
"""

from __future__ import annotations

import pytest

from tgparser.userbot.appkeys import (
    AppKeys,
    PortalClient,
    PortalError,
    PortalLogin,
    extract_csrf,
    extract_keys,
    looks_like_error,
)

APPS_PAGE = """
<html><body>
<h3>App configuration</h3>
<label>App api_id:</label>
<span class="form-control input-xlarge uneditable-input" onclick="this.select();">27482913</span>
<label>App api_hash:</label>
<span class="form-control input-xlarge uneditable-input" onclick="this.select();">a1b2c3d4e5f60718293a4b5c6d7e8f90</span>
</body></html>
"""

# Порядок полей на портале уже менялся, поэтому разбор не должен зависеть от него.
APPS_PAGE_REVERSED = """
<span class="form-control input-xlarge uneditable-input">a1b2c3d4e5f60718293a4b5c6d7e8f90</span>
<span class="form-control input-xlarge uneditable-input">27482913</span>
"""

CREATE_FORM = """
<form method="post" action="/apps/create">
<input type="hidden" name="hash" value="2d5d8ecfe2eba66183"/>
<input type="text" name="app_title"/>
</form>
"""


class TestExtractKeys:
    def test_reads_both_values(self):
        keys = extract_keys(APPS_PAGE)
        assert keys == AppKeys(api_id=27482913, api_hash="a1b2c3d4e5f60718293a4b5c6d7e8f90")

    def test_order_does_not_matter(self):
        keys = extract_keys(APPS_PAGE_REVERSED)
        assert keys.api_id == 27482913
        assert keys.api_hash == "a1b2c3d4e5f60718293a4b5c6d7e8f90"

    def test_uppercase_hash_is_normalized(self):
        page = APPS_PAGE.replace("a1b2c3d4e5f60718293a4b5c6d7e8f90", "A1B2C3D4E5F60718293A4B5C6D7E8F90")
        assert extract_keys(page).api_hash == "a1b2c3d4e5f60718293a4b5c6d7e8f90"

    def test_no_app_yet(self):
        assert extract_keys(CREATE_FORM) is None

    def test_empty_page(self):
        assert extract_keys("") is None

    def test_ignores_wrong_shaped_values(self):
        page = '<span class="uneditable-input">не ключ</span>'
        assert extract_keys(page) is None


class TestExtractCsrf:
    def test_finds_hidden_field(self):
        assert extract_csrf(CREATE_FORM) == "2d5d8ecfe2eba66183"

    def test_absent(self):
        assert extract_csrf(APPS_PAGE) is None


class TestLooksLikeError:
    @pytest.mark.parametrize("body", ["ERROR", "error", '"ERROR"', "false", "  Error: nope"])
    def test_detects(self, body):
        assert looks_like_error(body) is True

    @pytest.mark.parametrize("body", ['{"random_hash":"abc"}', "true", ""])
    def test_passes_good_bodies(self, body):
        assert looks_like_error(body) is False


class FakePortalHTTP:
    """Подменяет только сетевой слой PortalClient."""

    def __init__(self, posts: dict[str, str], gets: list[str]) -> None:
        self.posts = posts
        self.gets = list(gets)
        self.calls: list[tuple[str, str]] = []

    async def post(self, path: str, data: dict[str, str]) -> str:
        self.calls.append(("POST", path))
        return self.posts.get(path, "ERROR")

    async def get(self, path: str) -> str:
        self.calls.append(("GET", path))
        return self.gets.pop(0) if self.gets else ""


def wire(client: PortalClient, http: FakePortalHTTP) -> PortalClient:
    client._post = http.post
    client._get = http.get
    return client


class TestRequestCode:
    async def test_returns_random_hash(self):
        http = FakePortalHTTP({"/auth/send_password": '{"random_hash":"abc123"}'}, [])
        client = wire(PortalClient(), http)
        login = await client.request_code("+79991234567")
        assert login.random_hash == "abc123"

    async def test_unknown_number(self):
        http = FakePortalHTTP({"/auth/send_password": '{"error":"PHONE_INVALID"}'}, [])
        client = wire(PortalClient(), http)
        with pytest.raises(PortalError, match="не знает такого номера"):
            await client.request_code("+79991234567")

    async def test_generic_refusal_mentions_manual_path(self):
        http = FakePortalHTTP({"/auth/send_password": "ERROR"}, [])
        client = wire(PortalClient(), http)
        with pytest.raises(PortalError, match=r"my\.telegram\.org"):
            await client.request_code("+79991234567")


class TestLogin:
    async def test_accepts_success(self):
        http = FakePortalHTTP({"/auth/login": "true"}, [])
        client = wire(PortalClient(), http)
        await client.login(PortalLogin("+79991234567", "abc"), "12345")

    async def test_rejects_bad_code(self):
        http = FakePortalHTTP({"/auth/login": "false"}, [])
        client = wire(PortalClient(), http)
        with pytest.raises(PortalError, match="не принял код"):
            await client.login(PortalLogin("+79991234567", "abc"), "00000")


class TestObtainKeys:
    async def test_reads_existing_app_without_creating(self):
        http = FakePortalHTTP({}, [APPS_PAGE])
        client = wire(PortalClient(), http)
        keys = await client.obtain_keys()
        assert keys.api_id == 27482913
        assert ("POST", "/apps/create") not in http.calls

    async def test_creates_app_when_missing(self):
        http = FakePortalHTTP({"/apps/create": "ok"}, [CREATE_FORM, APPS_PAGE])
        client = wire(PortalClient(), http)
        keys = await client.obtain_keys()
        assert keys.api_id == 27482913
        assert ("POST", "/apps/create") in http.calls

    async def test_no_form_and_no_keys(self):
        http = FakePortalHTTP({}, ["<html>nothing useful</html>"])
        client = wire(PortalClient(), http)
        with pytest.raises(PortalError, match="форму создания"):
            await client.obtain_keys()

    async def test_creation_rejected(self):
        http = FakePortalHTTP({"/apps/create": "ERROR"}, [CREATE_FORM])
        client = wire(PortalClient(), http)
        with pytest.raises(PortalError, match="отклонил создание"):
            await client.obtain_keys()

    async def test_created_but_unreadable(self):
        http = FakePortalHTTP({"/apps/create": "ok"}, [CREATE_FORM, "<html></html>"])
        client = wire(PortalClient(), http)
        with pytest.raises(PortalError, match="прочитать не удалось"):
            await client.obtain_keys()

    async def test_all_errors_offer_the_manual_route(self):
        for gets, posts in (
            (["<html></html>"], {}),
            ([CREATE_FORM], {"/apps/create": "ERROR"}),
        ):
            client = wire(PortalClient(), FakePortalHTTP(posts, gets))
            with pytest.raises(PortalError) as info:
                await client.obtain_keys()
            assert "my.telegram.org" in str(info.value)


class TestSessionGuard:
    async def test_requires_open_session(self):
        client = PortalClient()
        with pytest.raises(PortalError, match="не открыта"):
            await client.request_code("+79991234567")
