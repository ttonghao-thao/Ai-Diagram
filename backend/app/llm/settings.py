"""Versioned workbench configuration shared by all LLM request paths."""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, replace
from tempfile import NamedTemporaryFile
from typing import Literal, Optional
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.config import Settings
from app.schemas.api import ApiException, ErrorCode
from app.storage.db import Database

API_KEY_MASK = "****"
KEY_FILENAME = "llm-settings.key"
RUNTIME_FIELDS = {
    "enabled": "llm_enabled",
    "provider": "llm_provider",
    "baseUrl": "llm_base_url",
    "model": "llm_model",
    "timeoutSeconds": "llm_timeout_seconds",
    "maxRetries": "llm_max_retries",
    "reasoningEffort": "llm_reasoning_effort",
    "privateEndpoint": "llm_private_endpoint",
}
logger = logging.getLogger(__name__)


class LlmOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = False
    provider: Literal["mock", "openai"] = "mock"
    baseUrl: str = Field("", max_length=2048)
    model: str = Field("", max_length=300)
    timeoutSeconds: int = Field(60, ge=1, le=86400)
    maxRetries: int = Field(2, ge=0, le=10)
    reasoningEffort: str = Field("", max_length=40, pattern=r"^[a-zA-Z0-9_-]*$")
    privateEndpoint: bool = False

    @field_validator("baseUrl")
    @classmethod
    def provider_url(cls, value: str) -> str:
        if not value:
            return value
        message = "服务地址必须是无凭据、查询参数或片段的 HTTP(S) URL"
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
            raise ValueError(message)
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError:
            raise ValueError(message) from None
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
                or port == 0 or "?" in value or "#" in value):
            raise ValueError(message)
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _validate_active(options: LlmOptions) -> None:
    if options.enabled and options.provider == "openai" and not (options.baseUrl and options.model):
        raise ApiException(ErrorCode.SCHEMA_INVALID, "启用 OpenAI-compatible 时请填写服务地址和模型名称")


def _validated_key(value: str) -> str:
    key = value.strip()
    if len(key) > 4096 or any(not 32 <= ord(char) < 127 for char in key):
        raise ValueError("API key 须使用可打印的 ASCII 字符，长度最多 4096")
    return key


class LlmSettingsUpdate(LlmOptions):
    baseVersion: int = Field(ge=1)
    apiKey: Optional[SecretStr] = Field(None, max_length=4096)

    @field_validator("apiKey")
    @classmethod
    def validate_key(cls, value: Optional[SecretStr]) -> Optional[SecretStr]:
        return SecretStr(_validated_key(value.get_secret_value())) if value is not None else None


@dataclass(frozen=True)
class LlmSnapshot:
    version: int
    options: LlmOptions
    encrypted_key: Optional[bytes]

    def public_fields(self) -> dict:
        return {
            **self.options.model_dump(),
            "version": self.version,
            "apiKey": API_KEY_MASK if self.encrypted_key else "",
        }


class LlmSettingsStore:
    def __init__(self, db: Database, bootstrap: Settings) -> None:
        self.db = db
        self.key_path = bootstrap.storage_root / KEY_FILENAME
        self.deployment = replace(bootstrap, llm_api_key="")
        with db.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._read(conn) is None:
                self._initialize(conn, bootstrap)

    def _initialize(self, conn: sqlite3.Connection, bootstrap: Settings) -> None:
        try:
            options = LlmOptions.model_validate({
                name: getattr(bootstrap, field) for name, field in RUNTIME_FIELDS.items()
            })
            _validate_active(options)
            key = _validated_key(bootstrap.llm_api_key)
        except (ValueError, ApiException):
            logger.warning("Legacy LLM configuration is invalid; initialize defaults for the workbench")
            options, key = LlmOptions(), ""

        ciphertext = self._encrypt(key) if key and key != API_KEY_MASK and options.baseUrl else None
        conn.execute(
            "INSERT INTO llm_settings (id, version, options_json, api_key_ciphertext) VALUES (1, 1, ?, ?)",
            (options.model_dump_json(), ciphertext),
        )

    @staticmethod
    def _read(conn: sqlite3.Connection) -> Optional[LlmSnapshot]:
        row = conn.execute("SELECT version, options_json, api_key_ciphertext FROM llm_settings WHERE id = 1").fetchone()
        if row is None:
            return None
        return LlmSnapshot(row["version"], LlmOptions.model_validate_json(row["options_json"]), row["api_key_ciphertext"])

    def _current(self, conn: sqlite3.Connection) -> LlmSnapshot:
        result = self._read(conn)
        if result is None:
            raise ApiException(ErrorCode.INTERNAL_ERROR, "LLM 配置未初始化")
        return result

    def current(self) -> LlmSnapshot:
        with self.db.transaction() as conn:
            return self._current(conn)

    def update(self, update: LlmSettingsUpdate) -> LlmSnapshot:
        with self.db.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._current(conn)
            if current.version != update.baseVersion:
                raise ApiException(
                    ErrorCode.VERSION_CONFLICT, "LLM 配置已更新，请重新加载后保存",
                    {"currentVersion": current.version},
                )
            changes = update.model_dump(include=set(LlmOptions.model_fields), exclude_unset=True)
            options = LlmOptions.model_validate(current.options.model_dump() | changes)
            _validate_active(options)

            ciphertext = current.encrypted_key if options.baseUrl == current.options.baseUrl else None
            if "apiKey" in update.model_fields_set:
                if update.apiKey is None:
                    ciphertext = None
                else:
                    key = update.apiKey.get_secret_value()
                    if key and key != API_KEY_MASK:
                        if not options.baseUrl:
                            raise ApiException(ErrorCode.SCHEMA_INVALID, "保存 API key 时请填写服务地址")
                        ciphertext = self._encrypt(key)

            saved = LlmSnapshot(current.version + 1, options, ciphertext)
            conn.execute(
                "UPDATE llm_settings SET version = ?, options_json = ?, api_key_ciphertext = ? WHERE id = 1",
                (saved.version, options.model_dump_json(), ciphertext),
            )
            return saved

    def runtime_settings(self) -> Settings:
        snapshot = self.current()
        key = ""
        if snapshot.options.enabled and snapshot.options.provider == "openai" and snapshot.encrypted_key:
            try:
                key = Fernet(self.key_path.read_bytes()).decrypt(snapshot.encrypted_key).decode("ascii")
            except (OSError, ValueError, InvalidToken):
                raise ApiException(ErrorCode.LLM_UNAVAILABLE, "已保存的 API key 无法读取，请在门户重新保存密钥") from None
        return replace(self.deployment, llm_api_key=key, **{
            field: getattr(snapshot.options, name) for name, field in RUNTIME_FIELDS.items()
        })

    def _encrypt(self, value: str) -> bytes:
        try:
            if not self.key_path.is_file():
                # Publish a fully written 0600 file without replacing an
                # existing encryption key, including under concurrent startup.
                with NamedTemporaryFile(dir=self.key_path.parent, prefix=".llm-", suffix=".key") as temporary:
                    temporary.write(Fernet.generate_key())
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    try:
                        os.link(temporary.name, self.key_path)
                    except FileExistsError:
                        pass
            return Fernet(self.key_path.read_bytes()).encrypt(value.encode("ascii"))
        except (OSError, ValueError):
            raise ApiException(ErrorCode.INTERNAL_ERROR, "LLM 密钥存储不可用") from None
