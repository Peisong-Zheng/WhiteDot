"""Public preferences and local, endpoint-scoped AI connections."""
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


class StorageError(RuntimeError):
    """A local storage error safe to display to the user."""


def _path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "WhiteDot" / "settings.json"


def _account(config: ProviderConfig) -> str:
    # Keep earlier versions' endpoint identities so their profiles can be recognized.
    identity = config.provider + "\n" + config.base_url.strip().rstrip("/")
    return hashlib.sha256(identity.encode()).hexdigest()


def _read_config(raw) -> ProviderConfig | None:
    if isinstance(raw, dict) and all(
        isinstance(raw.get(k), str) and raw[k] for k in ("provider", "base_url", "model")
    ):
        return ProviderConfig(raw["provider"], raw["base_url"], raw["model"])
    return None


def _load_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError):
        raise StorageError(f"Folio could not read {path.name}. Check its format and file permissions.") from None


def _write_object(path: Path, data: dict) -> None:
    """Replace a complete file, publishing the new version only after a successful write."""
    tmp = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # NamedTemporaryFile uses owner-only permissions on POSIX. Windows
        # inherits the current user's profile directory ACL.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            tmp = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        tmp.replace(path)
    except (OSError, ValueError, TypeError):
        raise StorageError(f"Folio could not save {path.name}. Check disk space and file permissions.") from None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


class Settings:
    def __init__(self, path: Path | None = None):
        self._path = path if path is not None else _path()
        self._connections_path = self._path.with_name("connections.json")
        if path is None and sys.platform == "win32":
            local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            self._connections_path = local / "Folio" / "connections.json"
        self._lock = RLock()
        self._data = _load_object(self._path)
        self.connection_error = ""
        try:
            self._connections = self._load_connections()
        except StorageError as exc:
            # Keep opening the editor and offline spelling available on a disk error.
            self._connections = {}
            self.connection_error = str(exc)

    def _load_connections(self) -> dict:
        data = _load_object(self._connections_path)
        keys = data.get("keys", {})
        if not isinstance(keys, dict) or not all(isinstance(value, str) for value in keys.values()):
            raise StorageError("Folio could not read connections.json. Check its format and file permissions.")
        return data

    @property
    def config(self) -> ProviderConfig:
        with self._lock:
            return (_read_config(self._connections.get("provider"))
                    or _read_config(self._data.get("provider")) or PRESETS["DeepSeek"])

    def config_for(self, provider: str) -> ProviderConfig:
        with self._lock:
            if self.config.provider == provider:
                return self.config
            for source in (self._connections, self._data):
                profiles = source.get("profiles")
                saved = _read_config(profiles.get(provider)) if isinstance(profiles, dict) else None
                if saved and saved.provider == provider:
                    return saved
            return PRESETS[provider]

    def get(self, name: str, default=None):
        with self._lock:
            return self._data.get(name, default)

    def set(self, name: str, value) -> None:
        with self._lock:
            data = {**self._data, name: value}
            _write_object(self._path, data)
            self._data = data

    def has_key(self, config: ProviderConfig | None = None) -> bool:
        with self._lock:
            return bool(self._connections.get("keys", {}).get(_account(config or self.config)))

    def needs_key_reentry(self, config: ProviderConfig | None = None) -> bool:
        with self._lock:
            old = self._data.get("accounts")
            target = config or self.config
            return isinstance(old, list) and _account(target) in old and not self.has_key(target)

    def get_key(self, config: ProviderConfig | None = None) -> str:
        with self._lock:
            return self._connections.get("keys", {}).get(_account(config or self.config), "")

    def save_provider(self, config: ProviderConfig, key: str | None = None) -> None:
        """Commit the validated credential and provider selection in one replacement."""
        with self._lock:
            data = self._load_connections() if self.connection_error else self._connections
            account = _account(config)
            keys = dict(data.get("keys", {}))
            if key is not None:
                if not key.strip():
                    raise StorageError("Enter an API key.")
                keys[account] = key.strip()
            if not keys.get(account):
                raise StorageError("Enter an API key for this endpoint.")

            profiles = data.get("profiles", {})
            profiles = dict(profiles) if isinstance(profiles, dict) else {}
            previous = self.config
            profiles.setdefault(previous.provider, asdict(previous))
            profiles[config.provider] = asdict(config)
            updated = {**data, "provider": asdict(config), "profiles": profiles, "keys": keys}
            _write_object(self._connections_path, updated)
            self._connections = updated
            self.connection_error = ""
