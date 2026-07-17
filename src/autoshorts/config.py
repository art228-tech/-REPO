"""Загрузка и валидация конфига (config.yaml)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Понятная ошибка конфига (показывается пользователю, не роняет трейсом)."""


@dataclass
class FolderRule:
    path: str
    mode: str  # "cycle" | "consume"

    def validate(self, name: str) -> None:
        if self.mode not in ("cycle", "consume"):
            raise ConfigError(
                f"folders.{name}.mode должен быть 'cycle' или 'consume', "
                f"а не '{self.mode}'"
            )


@dataclass
class Config:
    raw: dict[str, Any]
    project: dict[str, Any]
    video: dict[str, Any]
    voice: dict[str, Any]
    folders: dict[str, FolderRule]
    montage: dict[str, Any]
    logging: dict[str, Any] = field(default_factory=dict)

    # ---- удобные геттеры ----
    @property
    def output_dir(self) -> str:
        return self.project.get("output_dir", "output")

    @property
    def logs_dir(self) -> str:
        return self.project.get("logs_dir", "logs")

    @property
    def state_dir(self) -> str:
        return self.project.get("state_dir", "state")

    @property
    def voice_provider(self) -> str:
        return self.voice.get("provider", "dolphin")

    def validate(self) -> None:
        if self.voice_provider not in ("dolphin", "elevenlabs_api"):
            raise ConfigError(
                f"voice.provider должен быть 'dolphin' или 'elevenlabs_api', "
                f"а не '{self.voice_provider}'"
            )
        renderer = self.montage.get("renderer", "capcut")
        if renderer not in ("capcut", "ffmpeg"):
            raise ConfigError(
                f"montage.renderer должен быть 'capcut' или 'ffmpeg', "
                f"а не '{renderer}'"
            )
        for name, rule in self.folders.items():
            rule.validate(name)


def load_config(path: str | Path = "config.yaml") -> Config:
    """Прочитать config.yaml. Если его нет — подсказать про config.example.yaml."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        example = cfg_path.parent / "config.example.yaml"
        hint = (f" Скопируй {example.name} в {cfg_path.name} и заполни."
                if example.exists() else "")
        raise ConfigError(f"Конфиг не найден: {cfg_path}.{hint}")

    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Ошибка разбора YAML в {cfg_path}: {exc}") from exc

    folders = {
        name: FolderRule(path=spec.get("path", ""),
                         mode=spec.get("mode", "cycle"))
        for name, spec in (raw.get("folders") or {}).items()
    }

    cfg = Config(
        raw=raw,
        project=raw.get("project", {}),
        video=raw.get("video", {}),
        voice=raw.get("voice", {}),
        folders=folders,
        montage=raw.get("montage", {}),
        logging=raw.get("logging", {}),
    )
    cfg.validate()
    return cfg
