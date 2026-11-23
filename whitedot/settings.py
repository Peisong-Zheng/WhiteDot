"""Public preferences and endpoint-scoped system credentials."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from threading import RLock

from .provider import PRESETS, ProviderConfig

_SERVICE = "WhiteDot AI"


class StorageError(RuntimeError):
    """A preference or system keychain error with a safe user-facing message."""


def _path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "WhiteDot" / "settings.json"


def _vault():
    # Select the OS vault explicitly. Avoid a plaintext third-party keyring
    # selected by environment variables or an unrelated application's config.
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring
        return Keyring()
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    raise StorageError("当前系统缺少受支持的凭据存储。")


def _account(config: ProviderConfig) -> str:
    # Keys are bound to the exact endpoint; changing a service URL cannot
    # silently reuse credentials belonging to another server.
    identity = config.provider + "\n" + config.base_url.strip().rstrip("/")
    return hashlib.sha256(identity.encode()).hexdigest()


class Settings:
    def __init__(self, path: Path | None = None):
        self._path = path if path is not None else _path()
        self._lock = RLock()
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(self._data, dict):
                raise ValueError
        except FileNotFoundError:
            self._data = {}
        except (OSError, ValueError, RecursionError):
            raise StorageError("无法读取设置文件，请检查文件格式及系统读写权限。") from None

    @property
    def config(self) -> ProviderConfig:
        raw = self.get("provider")
        if isinstance(raw, dict) and all(
            isinstance(raw.get(k), str) and raw[k] for k in ("provider", "base_url", "model")
        ):
            return ProviderConfig(raw["provider"], raw["base_url"], raw["model"])
        return PRESETS["DeepSeek"]

    def get(self, name: str, default=None):
        with self._lock:
            return self._data.get(name, default)

    def _write(self, data: dict) -> None:
        tmp = None
        try:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self._path.parent, delete=False
            ) as f:
                tmp = Path(f.name)
                json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self._path)
        except (OSError, ValueError, TypeError):
            raise StorageError("保存设置失败，请检查磁盘空间和目录权限。") from None
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        self._data = data

    def set(self, name: str, value) -> None:
        with self._lock:
            self._write({**self._data, name: value})

    def get_key(self, config: ProviderConfig | None = None) -> str:
        with self._lock:
            target = config or self.config
            # Avoid an unnecessary keychain prompt on the first run.
            if _account(target) not in self.get("accounts", []):
                return ""
            try:
                return _vault().get_password(_SERVICE, _account(target)) or ""
            except Exception:
                raise StorageError("无法读取系统凭据，请解锁钥匙串或检查 Windows 凭据管理器。") from None

    def save_provider(self, config: ProviderConfig, key: str) -> None:
        """Call after successful validation. A failed update preserves the active profile."""
        if not key.strip():
            raise StorageError("API Key 不能为空。")
        with self._lock:
            account = _account(config)
            try:
                vault = _vault()
                previous = vault.get_password(_SERVICE, account)
                vault.set_password(_SERVICE, account, key.strip())
            except Exception:
                raise StorageError("无法保存 API Key，请允许访问系统钥匙串或 Windows 凭据管理器。") from None
            try:
                accounts = sorted(set(self.get("accounts", [])) | {account})
                self._write({**self._data, "provider": asdict(config), "accounts": accounts})
            except Exception:
                try:
                    if previous is not None:
                        vault.set_password(_SERVICE, account, previous)
                    else:
                        vault.delete_password(_SERVICE, account)
                except Exception:
                    raise StorageError("保存设置失败，系统凭据可能已更新。请重新验证并保存。") from None
                raise
