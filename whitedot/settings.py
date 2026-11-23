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
    raise StorageError("Secure credential storage is unavailable on this system.")


def _account(config: ProviderConfig) -> str:
    # Keys are bound to the exact endpoint; changing a service URL cannot
    # silently reuse credentials belonging to another server.
    identity = config.provider + "\n" + config.base_url.strip().rstrip("/")
    return hashlib.sha256(identity.encode()).hexdigest()


def _read_config(raw) -> ProviderConfig | None:
    if isinstance(raw, dict) and all(
        isinstance(raw.get(k), str) and raw[k] for k in ("provider", "base_url", "model")
    ):
        return ProviderConfig(raw["provider"], raw["base_url"], raw["model"])
    return None


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
            raise StorageError("WhiteDot could not read its settings. Check the file format and permissions.") from None

    @property
    def config(self) -> ProviderConfig:
        return _read_config(self.get("provider")) or PRESETS["DeepSeek"]

    def config_for(self, provider: str) -> ProviderConfig:
        current = self.config
        if current.provider == provider:
            return current
        profiles = self.get("profiles", {})
        saved = _read_config(profiles.get(provider)) if isinstance(profiles, dict) else None
        return saved if saved and saved.provider == provider else PRESETS[provider]

    def _accounts(self) -> set[str]:
        raw = self.get("accounts")
        return {s for s in raw if isinstance(s, str)} if isinstance(raw, list) else set()

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
            raise StorageError("Settings could not be saved. Check disk space and folder permissions.") from None
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
            if _account(target) not in self._accounts():
                return ""
            try:
                return _vault().get_password(_SERVICE, _account(target)) or ""
            except Exception:
                raise StorageError("Unlock your system credential store and try again.") from None

    def save_provider(self, config: ProviderConfig, key: str) -> None:
        """Call after successful validation. A failed update preserves the active profile."""
        if not key.strip():
            raise StorageError("Enter an API key.")
        with self._lock:
            account = _account(config)
            try:
                vault = _vault()
                previous = vault.get_password(_SERVICE, account)
                vault.set_password(_SERVICE, account, key.strip())
            except Exception:
                raise StorageError("Allow access to your system credential store to save the API key.") from None
            try:
                # Before per-provider profiles, only the active one was saved.
                # Preserve it the first time an upgrading user switches providers.
                saved = self.get("profiles")
                profiles = dict(saved) if isinstance(saved, dict) else {}
                previous_config = _read_config(self.get("provider"))
                if previous_config:
                    profiles[previous_config.provider] = asdict(previous_config)
                profiles[config.provider] = asdict(config)
                accounts = sorted(self._accounts() | {account})
                self._write({**self._data, "provider": asdict(config), "profiles": profiles,
                             "accounts": accounts})
            except Exception:
                try:
                    if previous is not None:
                        vault.set_password(_SERVICE, account, previous)
                    else:
                        vault.delete_password(_SERVICE, account)
                except Exception:
                    raise StorageError("Settings could not be saved. The stored key may have changed. Validate and save again.") from None
                raise
