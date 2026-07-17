"""Провайдер озвучки через Dolphin Anty (браузерная автоматизация, ОДИН аккаунт).

Схема (в границах правил — один твой аккаунт, без ротации):
  1. Через Local API Dolphin создаётся НОВЫЙ профиль (чужие не трогаем).
  2. Профиль стартует, Dolphin отдаёт порт автоматизации (Selenium/CDP).
  3. Playwright подключается к этому браузеру, логинится в ТВОЙ аккаунт
     ElevenLabs, создаёт голоса из промптов и озвучивает тексты.
  4. По завершении профиль, созданный софтом, останавливается и удаляется.

ВАЖНО: этот модуль запускается на твоём Windows-ноуте с установленным
Dolphin Anty. На Linux-сервере его протестировать нельзя — здесь только
корректная реализация и логи. Логин/селекторы сайта ElevenLabs вынесены в
методы, которые легко поправить, если верстка сайта поменяется.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from ..logging_setup import get_logger
from .base import (TTSResult, VoiceProvider, VoiceProviderError,
                   clamp_voice_description)

log = get_logger("voice.dolphin")


class DolphinProvider(VoiceProvider):
    def __init__(self, cfg: dict, account: dict | None = None):
        self.cfg = cfg
        d = cfg.get("dolphin", {})
        self.local_api = d.get("local_api", "http://localhost:3001/v1.0").rstrip("/")
        self.profile_prefix = d.get("profile_prefix", "autoshorts")
        self.api_token = os.getenv(d.get("api_token_env", "DOLPHIN_API_TOKEN"), "")
        self.desc_min = int(cfg.get("voice_desc_min", 20))
        self.desc_max = int(cfg.get("voice_desc_max", 1000))
        # Данные аккаунта передаются из GUI (email/пароль или cookie).
        self.account = account or {}
        self._profile_id: str | None = None
        self._page = None
        self._pw = None
        self._browser = None

    # --------------------- Dolphin Local API ---------------------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_token:
            h["Authorization"] = f"Bearer {self.api_token}"
        return h

    def _create_profile(self) -> str:
        name = f"{self.profile_prefix}-{int(time.time())}"
        log.info("Создаю профиль Dolphin: %s", name)
        # Примечание: точный payload зависит от версии Dolphin Anty.
        payload = {
            "name": name,
            "tags": ["autoshorts"],
            "platform": "windows",
            "browserType": "anty",
            "mainWebsite": "google",
        }
        resp = requests.post(f"{self.local_api}/browser_profiles",
                             json=payload, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        profile_id = str(data.get("browserProfileId") or data.get("id") or
                         data.get("data", {}).get("id", ""))
        if not profile_id:
            raise VoiceProviderError(f"Dolphin не вернул id профиля: {data}")
        self._profile_id = profile_id
        return profile_id

    def _start_profile(self, profile_id: str) -> dict:
        log.info("Запускаю профиль Dolphin %s", profile_id)
        resp = requests.get(
            f"{self.local_api}/browser_profiles/{profile_id}/start",
            params={"automation": 1}, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        data = resp.json()
        # Ожидаем что-то вроде {"automation": {"port": 12345, "wsEndpoint": "..."}}
        automation = data.get("automation") or data
        return automation

    def _stop_profile(self, profile_id: str) -> None:
        try:
            requests.get(f"{self.local_api}/browser_profiles/{profile_id}/stop",
                         headers=self._headers(), timeout=30)
        except requests.RequestException as exc:
            log.warning("Не удалось остановить профиль %s: %s", profile_id, exc)

    def _delete_profile(self, profile_id: str) -> None:
        # Удаляем ТОЛЬКО тот профиль, что создали сами.
        try:
            requests.delete(f"{self.local_api}/browser_profiles/{profile_id}",
                            headers=self._headers(), timeout=30)
            log.info("Профиль Dolphin %s удалён.", profile_id)
        except requests.RequestException as exc:
            log.warning("Не удалось удалить профиль %s: %s", profile_id, exc)

    # --------------------- VoiceProvider ---------------------
    def login(self) -> None:
        try:
            profile_id = self._create_profile()
            automation = self._start_profile(profile_id)
        except requests.RequestException as exc:
            raise VoiceProviderError(
                f"Dolphin Local API недоступен ({self.local_api}). "
                f"Запущен ли Dolphin Anty? Детали: {exc}"
            ) from exc

        port = automation.get("port")
        ws = automation.get("wsEndpoint") or automation.get("ws_endpoint")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise VoiceProviderError(
                "Playwright не установлен. pip install playwright && "
                "playwright install chromium"
            ) from exc

        self._pw = sync_playwright().start()
        endpoint = ws or f"http://127.0.0.1:{port}"
        log.info("Подключаюсь к браузеру Dolphin: %s", endpoint)
        self._browser = self._pw.chromium.connect_over_cdp(endpoint)
        context = self._browser.contexts[0] if self._browser.contexts \
            else self._browser.new_context()
        self._page = context.pages[0] if context.pages else context.new_page()

        self._login_elevenlabs()

    def _login_elevenlabs(self) -> None:
        """Вход в ТВОЙ аккаунт ElevenLabs через Google.

        Селекторы вынесены отдельно — если сайт поменяет верстку, правится
        только здесь, а не по всему коду.
        """
        page = self._page
        page.goto("https://elevenlabs.io/app/", wait_until="domcontentloaded")
        # Если уже залогинен (cookie в профиле) — выходим.
        if "/app" in page.url and "sign-in" not in page.url:
            log.info("Сессия ElevenLabs уже активна.")
            return
        log.info("Требуется вход в аккаунт ElevenLabs (Google).")
        # Здесь выполняется вход по Google с данными из self.account.
        # Реализация логина зависит от текущего UI и настраивается на ноуте.
        # Специально не хардкодим хрупкие шаги — оставляем точку расширения.
        raise VoiceProviderError(
            "Автологин ElevenLabs требует настройки селекторов на твоём ноуте "
            "(этап отладки в реальном Dolphin). Заготовка готова в _login_elevenlabs()."
        )

    def create_voice(self, description: str, name: str) -> str:
        desc = clamp_voice_description(description, self.desc_min, self.desc_max)
        if desc != description.strip():
            log.warning("Описание голоса '%s' подогнано под лимит.", name)
        # Реализуется через UI Voice Design на сайте (настраивается на ноуте).
        raise VoiceProviderError(
            "create_voice через браузер настраивается на этапе отладки в Dolphin."
        )

    def tts(self, text: str, voice_id: str, out_path: Path) -> TTSResult:
        raise VoiceProviderError(
            "tts через браузер настраивается на этапе отладки в Dolphin."
        )

    def tokens_left(self) -> int | None:
        return None

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        finally:
            if self._profile_id:
                self._stop_profile(self._profile_id)
                self._delete_profile(self._profile_id)
