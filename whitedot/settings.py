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
from uuid import uuid4

from .provider import PRESETS, ProviderConfig

# Keep the existing credential namespace and preference path across the rename.
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
        self._credential_lock = RLock()
        self._session_keys: dict[str, str] = {}
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(self._data, dict):
                raise ValueError
        except FileNotFoundError:
            self._data = {}
        except (OSError, ValueError, RecursionError):
            raise StorageError("Folio could not read its settings. Check the file format and permissions.") from None

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

    def has_key(self, config: ProviderConfig | None = None) -> bool:
        """Report what the user has configured without opening the credential store."""
        return _account(config or self.config) in self._accounts()

    def _credential_name(self, account: str) -> str:
        generations = self.get("credential_generations")
        generation = generations.get(account) if isinstance(generations, dict) else None
        # Even a damaged preference must never point one endpoint at another's key.
        if isinstance(generation, str) and len(generation) == 32 and all(
                c in "0123456789abcdef" for c in generation):
            return f"{account}.{generation}"
        return account  # Existing releases stored this endpoint under its unversioned name.

    def get_key(self, config: ProviderConfig | None = None) -> str:
        target = config or self.config
        account = _account(target)
        with self._credential_lock:
            if not self.has_key(target):
                return ""
            if account not in self._session_keys:
                try:
                    key = _vault().get_password(_SERVICE, self._credential_name(account))
                except Exception:
                    raise StorageError("Access to the saved key was denied. Unlock your credential store and retry.") from None
                if not key:
                    return ""
                self._session_keys[account] = key
            return self._session_keys[account]

    def save_provider(self, config: ProviderConfig, key: str | None = None) -> None:
        """Commit a validated profile. Supply a key only when creating or replacing it."""
        if key is not None and not key.strip():
            raise StorageError("Enter an API key.")
        with self._credential_lock, self._lock:
            account = _account(config)
            known = self.has_key(config)
            saved = self.get("profiles")
            profiles = dict(saved) if isinstance(saved, dict) else {}
            previous_config = _read_config(self.get("provider"))
            if previous_config:
                profiles[previous_config.provider] = asdict(previous_config)
            profiles[config.provider] = asdict(config)
            data = {**self._data, "provider": asdict(config), "profiles": profiles,
                    "accounts": sorted(self._accounts() | {account})}
            if key is None:
                if not known:
                    raise StorageError("Enter an API key for this endpoint.")
                self._write(data)
                return

            # Keyring's macOS backend deletes an item before it writes the new
            # value. Stage the replacement separately so no failure loses the
            # active key or requires reading the original secret for rollback.
            previous = self._credential_name(account)
            generation = uuid4().hex
            credential = f"{account}.{generation}"
            raw = self.get("credential_generations")
            generations = dict(raw) if isinstance(raw, dict) else {}
            generations[account] = generation
            data["credential_generations"] = generations
            try:
                vault = _vault()
                vault.set_password(_SERVICE, credential, key.strip())
            except Exception:
                raise StorageError("Allow access to your credential store to save the API key.") from None
            try:
                self._write(data)
            except Exception:
                try:
                    vault.delete_password(_SERVICE, credential)
                except Exception:
                    pass  # The unreferenced item is still protected by the OS.
                raise
            self._session_keys[account] = key.strip()
            if known:
                try:
                    vault.delete_password(_SERVICE, previous)
                except Exception:
                    pass  # The validated replacement is already active.
