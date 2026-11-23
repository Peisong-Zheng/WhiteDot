"""Build release assets for the current host, run the packaged offline smoke test."""

import os
import platform
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "artwork"
DIST = ROOT / "dist"


def build_icon(macos):
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient

    BUILD.mkdir(parents=True, exist_ok=True)
    images = {}
    for size in (16, 32, 64, 128, 256, 512):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 128, size / 128)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#41454d"))
        painter.drawRoundedRect(QRectF(3, 3, 122, 122), 29, 29)
        shadow = QRadialGradient(64, 64, 49)
        shadow.setColorAt(0.64, QColor(0, 0, 0, 100))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(shadow)
        painter.drawEllipse(QRectF(15, 15, 98, 98))
        painter.setBrush(QColor("#81858a"))
        painter.drawEllipse(QRectF(21, 21, 86, 86))
        painter.setBrush(QColor("#c4c6c9"))
        painter.drawEllipse(QRectF(27, 27, 74, 74))
        painter.setBrush(Qt.GlobalColor.white)
        painter.drawEllipse(QRectF(34, 34, 60, 60))
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Could not encode application icon.")
        images[size] = bytes(data)
    if macos:
        chunks = []
        for size, tag in [(16, b"icp4"), (32, b"icp5"), (64, b"icp6"), (128, b"ic07"),
                          (256, b"ic08"), (512, b"ic09")]:
            png = images[size]
            chunks.append(tag + struct.pack(">I", len(png) + 8) + png)
        payload = b"".join(chunks)
        (BUILD / "Folio.icns").write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)
    else:
        entries, payload = [], bytearray()
        sizes = (16, 32, 64, 128, 256)
        for size in sizes:
            png = images[size]
            offset = 6 + 16 * len(sizes) + len(payload)
            entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset))
            payload.extend(png)
        (BUILD / "Folio.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + payload)


def main():
    if sys.platform not in ("darwin", "win32"):
        raise SystemExit("Build on macOS for a .app, or Windows for a portable .exe.")
    macos = sys.platform == "darwin"
    build_icon(macos)
    build_env = dict(os.environ)
    build_env.setdefault("PYINSTALLER_CONFIG_DIR", str(ROOT / "build" / "cache"))
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "Folio.spec"],
                   cwd=ROOT, env=build_env, check=True)
    if macos:
        bundle = DIST / "Folio.app"
        # Finder metadata can be inherited in synced directories and invalidates
        # the bundle signature. Sanitize only the generated app, then seal it.
        subprocess.run(["xattr", "-cr", str(bundle)], check=True)
        subprocess.run(["codesign", "-s", "-", "--force", "--all-architectures",
                        "--timestamp=none", "--deep", str(bundle)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
    binary = DIST / ("Folio.app/Contents/MacOS/Folio" if macos else "Folio.exe")
    env = {**os.environ, "QT_QPA_PLATFORM": "minimal"}
    subprocess.run([str(binary), "--self-test"], cwd=DIST, env=env, check=True, timeout=120)
    cpu = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(cpu, cpu)
    if macos:
        asset = DIST / f"Folio-macos-{arch}.zip"
        subprocess.run(["ditto", "-c", "-k", "--norsrc", "--noextattr", "--noacl", "--keepParent",
                        str(DIST / "Folio.app"), str(asset)], check=True)
    else:
        asset = DIST / f"Folio-windows-{arch}.exe"
        binary.replace(asset)
    print(f"Built and smoke-tested {asset}")


if __name__ == "__main__":
    main()
