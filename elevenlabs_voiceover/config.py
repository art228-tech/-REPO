"""Настройки приложения и их хранение."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from .chunker import LINE_BREAK_MODES, LINE_BREAKS_KEEP
from .logging_setup import get_logger, register_secret
from .paths import config_path

log = get_logger("config")

ENV_API_KEY = "ELEVENLABS_API_KEY"

#: Один текст озвучивается одним голосом, голоса чередуются по кругу.
MODE_ROUND_ROBIN = "round_robin"
#: Каждый текст озвучивается всеми голосами (файлов на выходе больше в N раз).
MODE_ALL_VOICES = "all_voices"

VOICE_MODES = {
    MODE_ROUND_ROBIN: "Один файл на текст, голоса чередуются по кругу",
    MODE_ALL_VOICES: "Несколько файлов на текст — по одному на каждый голос",
}

#: Что делать с исходным текстом после того, как он озвучен.
DONE_KEEP = "keep"
DONE_MOVE = "move"
DONE_DELETE = "delete"

#: Подпапка, куда переносятся озвученные тексты.
DONE_FOLDER_NAME = "озвучено"

DONE_ACTIONS = {
    DONE_KEEP: "Оставлять на месте",
    DONE_MOVE: f"Переносить в подпапку «{DONE_FOLDER_NAME}»",
    DONE_DELETE: "Удалять безвозвратно",
}

#: Голоса создаются программой по промптам через Voice Design.
SOURCE_DESIGN = "design"
#: Голоса уже созданы в личном кабинете, программа только выбирает из них.
#: Нужен на бесплатном тарифе: слоты для голосов там есть, но заполнять их
#: разрешено только на сайте, через API создание отклоняется.
SOURCE_ACCOUNT = "account"

VOICE_SOURCES = {
    SOURCE_DESIGN: "Создавать по промптам из папки (нужен платный тариф)",
    SOURCE_ACCOUNT: "Брать готовые из личного кабинета",
}

#: Минимальная длина preview-текста, которую принимает Voice Design.
VOICE_PREVIEW_MIN_CHARS = 100
VOICE_PREVIEW_MAX_CHARS = 1000

#: Насколько строго Voice Design держится промпта. Шкала 0–100, в API по
#: умолчанию 5. Значение сохранено как у ElevenLabs, чтобы результат совпадал
#: с их веб-интерфейсом, хотя в примерах документации используют 25–40.
DEFAULT_GUIDANCE = 5.0
GUIDANCE_MIN = 0.0
GUIDANCE_MAX = 100.0

#: Короткий нейтральный preview. Voice Design списывает кредиты по длине этого
#: текста, поэтому по умолчанию берём минимально допустимую длину.
DEFAULT_PREVIEW_TEXT = (
    "Проверка звучания голоса. Этот короткий фрагмент нужен только для того, "
    "чтобы услышать тембр, темп речи и общую манеру подачи материала."
)


@dataclass
class Settings:
    # --- доступ ---
    api_key: str = ""
    remember_api_key: bool = True

    # --- папки ---
    prompts_dir: str = ""
    texts_dir: str = ""
    output_dir: str = ""

    # --- голоса ---
    voice_source: str = SOURCE_DESIGN
    selected_voice_ids: List[str] = field(default_factory=list)
    max_voices: int = 3
    voice_mode: str = MODE_ROUND_ROBIN
    recreate_voices: bool = False
    voice_design_model: str = "eleven_multilingual_ttv_v2"
    preview_text: str = DEFAULT_PREVIEW_TEXT
    auto_generate_preview: bool = False
    guidance_scale: float = DEFAULT_GUIDANCE

    # --- озвучка ---
    model_id: str = "eleven_flash_v2_5"
    output_format: str = "mp3_44100_128"
    chunk_target_chars: int = 2500
    language_code: str = ""
    line_breaks: str = LINE_BREAKS_KEEP

    # --- параметры голоса ---
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True
    speed: float = 1.0

    # --- бюджет и темп ---
    reserve_credits: int = 0
    pause_between_requests: float = 0.4
    request_timeout: int = 180
    max_retries: int = 5

    # --- сеть ---
    proxy_url: str = ""
    ignore_system_proxy: bool = False

    # --- вывод ---
    done_action: str = DONE_KEEP
    save_next_to_texts: bool = False
    keep_chunks: bool = False
    use_ffmpeg: bool = True

    def __post_init__(self) -> None:
        self.normalize()

    # ------------------------------------------------------------------
    def normalize(self) -> None:
        """Привести значения к допустимым диапазонам.

        Конфиг правится руками и переживает обновления программы, поэтому
        нормализация обязательна, иначе кривое значение уедет прямо в API.
        """
        self.max_voices = _clamp_int(self.max_voices, 1, 50, 3)
        if self.voice_mode not in VOICE_MODES:
            self.voice_mode = MODE_ROUND_ROBIN
        if self.voice_source not in VOICE_SOURCES:
            self.voice_source = SOURCE_DESIGN
        if self.line_breaks not in LINE_BREAK_MODES:
            self.line_breaks = LINE_BREAKS_KEEP
        if self.done_action not in DONE_ACTIONS:
            # Неизвестное значение трактуем как «ничего не трогать»: потеря
            # исходников из-за опечатки в конфиге недопустима.
            self.done_action = DONE_KEEP

        if isinstance(self.selected_voice_ids, str):
            self.selected_voice_ids = [self.selected_voice_ids]
        self.selected_voice_ids = [
            str(v).strip() for v in (self.selected_voice_ids or []) if str(v).strip()
        ]

        self.chunk_target_chars = _clamp_int(self.chunk_target_chars, 200, 40000, 2500)
        self.reserve_credits = max(0, _clamp_int(self.reserve_credits, 0, 10**9, 0))
        self.pause_between_requests = _clamp_float(self.pause_between_requests, 0.0, 60.0, 0.4)
        self.request_timeout = _clamp_int(self.request_timeout, 10, 3600, 180)
        self.max_retries = _clamp_int(self.max_retries, 0, 20, 5)

        self.stability = _clamp_float(self.stability, 0.0, 1.0, 0.5)
        self.similarity_boost = _clamp_float(self.similarity_boost, 0.0, 1.0, 0.75)
        self.style = _clamp_float(self.style, 0.0, 1.0, 0.0)
        self.speed = _clamp_float(self.speed, 0.25, 4.0, 1.0)
        self.guidance_scale = _clamp_float(
            self.guidance_scale, GUIDANCE_MIN, GUIDANCE_MAX, DEFAULT_GUIDANCE
        )

        preview = (self.preview_text or "").strip()
        if not preview:
            preview = DEFAULT_PREVIEW_TEXT
        if len(preview) > VOICE_PREVIEW_MAX_CHARS:
            preview = preview[:VOICE_PREVIEW_MAX_CHARS].rstrip()
        # Короткий preview дешевле, но API отвергает всё, что меньше 100 символов.
        if len(preview) < VOICE_PREVIEW_MIN_CHARS:
            preview = (preview + " " + DEFAULT_PREVIEW_TEXT).strip()[:VOICE_PREVIEW_MAX_CHARS]
        self.preview_text = preview

        self.language_code = (self.language_code or "").strip()
        self.proxy_url = normalize_proxy_url(self.proxy_url)

    # ------------------------------------------------------------------
    def voice_settings_payload(self) -> Dict[str, Any]:
        return {
            "stability": self.stability,
            "similarity_boost": self.similarity_boost,
            "style": self.style,
            "use_speaker_boost": self.use_speaker_boost,
            "speed": self.speed,
        }

    def resolved_api_key(self) -> str:
        """Ключ из настроек, иначе из переменной окружения."""
        key = (self.api_key or "").strip()
        if key:
            return key
        return (os.environ.get(ENV_API_KEY) or "").strip()

    # ------------------------------------------------------------------
    def to_dict(self, include_secrets: bool = True) -> Dict[str, Any]:
        data = asdict(self)
        if not include_secrets or not self.remember_api_key:
            data["api_key"] = ""
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            log.debug("В конфиге найдены незнакомые поля, игнорирую: %s", sorted(unknown))
        clean: Dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            try:
                clean[f.name] = _coerce(value, f.type)
            except (TypeError, ValueError):
                log.warning("Некорректное значение %s=%r в конфиге, беру значение по умолчанию", f.name, value)
        return cls(**clean)

    def save(self, path: Optional[Path] = None) -> Path:
        target = path or config_path()
        payload = self.to_dict(include_secrets=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        log.debug("Настройки сохранены: %s", target)
        return target

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Settings:
        target = path or config_path()
        if not target.exists():
            log.info("Конфиг не найден, использую значения по умолчанию: %s", target)
            return cls()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Не удалось прочитать конфиг %s (%s), использую значения по умолчанию", target, exc)
            return cls()
        if not isinstance(data, dict):
            log.error("Конфиг %s имеет неожиданную структуру, использую значения по умолчанию", target)
            return cls()
        settings = cls.from_dict(data)
        register_secret(settings.api_key)
        return settings


#: Схемы прокси, которые понимает requests. socks5h отдаёт разрешение имён
#: самому прокси — это важно там, где домен ломают ещё на уровне DNS.
PROXY_SCHEMES = ("http", "https", "socks5", "socks5h", "socks4")


def normalize_proxy_url(value: str) -> str:
    """Привести адрес прокси к виду, который примет requests.

    Принимаются все ходовые записи, потому что человек копирует адрес оттуда,
    где его выдали, а не переписывает под формат библиотеки:

        127.0.0.1:1080                      -> http://127.0.0.1:1080
        socks5h://127.0.0.1:1080            -> без изменений
        1.2.3.4:8000:логин:пароль           -> http://логин:пароль@1.2.3.4:8000
        socks5://1.2.3.4:8000:логин:пароль  -> socks5://логин:пароль@1.2.3.4:8000

    Третья строка — то, в каком виде прокси продают чаще всего.
    """
    text = (value or "").strip()
    if not text:
        return ""

    scheme, separator, rest = text.partition("://")
    if separator:
        scheme = scheme.lower()
    else:
        scheme, rest = "http", text

    if scheme not in PROXY_SCHEMES:
        log.warning("Схема прокси %r не поддерживается, адрес не будет использован", scheme)
        return ""

    rest = rest.strip("/").strip()
    if not rest:
        log.warning("В адресе прокси нет самого адреса, он не будет использован")
        return ""

    # Позиционную запись продавцов разбираем первой. В ней пароль вполне может
    # содержать @ и двоеточия, и поиск @ разорвал бы адрес не в том месте.
    seller = _parse_seller_format(rest)
    if seller:
        return f"{scheme}://{seller}"

    credentials = ""
    if "@" in rest:
        credentials, _, rest = rest.rpartition("@")
        credentials = f"{credentials}@"

    host_port = _parse_host_port(rest)
    if host_port is None:
        log.warning("Адрес прокси %r не разобран, он не будет использован", value)
        return ""

    host, port = host_port
    return f"{scheme}://{credentials}{host}:{port}" if port else f"{scheme}://{credentials}{host}"


def _parse_seller_format(rest: str) -> Optional[str]:
    """Разобрать запись адрес:порт:логин:пароль, если это она.

    Делим слева и не более чем на четыре части: пароль идёт последним и может
    содержать любые символы, включая двоеточия.
    """
    if rest.startswith("["):
        return None

    parts = rest.split(":", 3)
    if len(parts) != 4:
        return None

    host, port, user, password = parts
    if not port.isdigit() or "@" in host or "/" in host or not host:
        return None

    return f"{_encode_credential(user)}:{_encode_credential(password)}@{host}:{port}"


def _parse_host_port(rest: str) -> Optional[Tuple[str, str]]:
    """Разобрать адрес и порт."""
    # Адрес IPv6 записывают в скобках, двоеточия внутри трогать нельзя.
    if rest.startswith("["):
        closing = rest.find("]")
        if closing == -1:
            return None
        host = rest[: closing + 1]
        tail = rest[closing + 1 :]
        if not tail:
            return host, ""
        if tail.startswith(":") and tail[1:].isdigit():
            return host, tail[1:]
        return None

    parts = rest.split(":")
    if len(parts) == 1:
        return (parts[0], "") if parts[0] else None
    if len(parts) == 2:
        host, port = parts
        return (host, port) if port.isdigit() and host else None
    return None


def _encode_credential(value: str) -> str:
    """Подготовить логин или пароль к подстановке в адрес.

    В паролях к прокси регулярно встречаются @, : и /. Без кодирования такой
    пароль разрывает адрес на части, и запрос уходит не туда.
    """
    if not value.isascii():
        # HTTP Basic передаёт учётные данные в latin-1, и кириллица в них
        # приводит к обрыву глубоко внутри библиотеки. Предупредим заранее.
        log.warning(
            "Логин или пароль прокси содержит нелатинские символы — такие данные "
            "протокол не передаёт, прокси, скорее всего, откажет"
        )
    return quote(value, safe="")


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _coerce(value: Any, type_hint: Any) -> Any:
    """Мягкое приведение типа поля, прочитанного из JSON."""
    hint = type_hint if isinstance(type_hint, str) else getattr(type_hint, "__name__", "")
    if hint == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "да"}
        return bool(value)
    if hint == "int":
        return int(value)
    if hint == "float":
        return float(value)
    if hint == "str":
        return "" if value is None else str(value)
    return value
