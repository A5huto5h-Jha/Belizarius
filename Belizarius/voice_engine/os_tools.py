
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

import ctypes
from ctypes import POINTER, cast
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume


# Restrict file operations to these locations.
HOME = Path.home()
ALLOWED_ROOTS = [
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Downloads",
    HOME / "Music",
    HOME / "Videos",
]

# Add your project folder explicitly if you want it accessible.
PROJECT_ROOT = Path(r"A:\Belizarius\Belizarius")
ALLOWED_ROOTS.append(PROJECT_ROOT)


def resolve_allowed_path(path: str) -> Path:
    """Resolve a path and ensure it stays within an allowed directory."""
    target = Path(path).expanduser().resolve()

    for root in ALLOWED_ROOTS:
        root = root.resolve()
        try:
            target.relative_to(root)
            return target
        except ValueError:
            continue

    raise PermissionError(f"Path is outside allowed locations: {target}")


def create_directory(path: str) -> str:
    target = resolve_allowed_path(path)
    target.mkdir(parents=True, exist_ok=False)
    return f"Created directory: {target}"


def create_text_file(path: str, content: str = "") -> str:
    target = resolve_allowed_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Created text file: {target}"


def list_directory(path: str) -> str:
    target = resolve_allowed_path(path)
    if not target.is_dir():
        raise NotADirectoryError(str(target))

    entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not entries:
        return "The directory is empty."

    return "\n".join(
        f"{'[DIR]' if p.is_dir() else '[FILE]'} {p.name}"
        for p in entries[:100]
    )


def read_text_file(path: str) -> str:
    target = resolve_allowed_path(path)
    if not target.is_file():
        raise FileNotFoundError(str(target))

    if target.stat().st_size > 1_000_000:
        raise ValueError("File is too large to read (limit: 1 MB).")

    return target.read_text(encoding="utf-8")[:12000]


def rename_path(path: str, new_name: str) -> str:
    target = resolve_allowed_path(path)

    if not target.exists():
        raise FileNotFoundError(str(target))

    if Path(new_name).name != new_name or new_name in {".", ".."}:
        raise ValueError("Provide only a new filename, not a path.")

    destination = resolve_allowed_path(str(target.parent / new_name))
    if destination.exists():
        raise FileExistsError(str(destination))

    target.rename(destination)
    return f"Renamed to: {destination}"


def move_path(source: str, destination_folder: str) -> str:
    src = resolve_allowed_path(source)
    dst_folder = resolve_allowed_path(destination_folder)

    if not src.exists():
        raise FileNotFoundError(str(src))
    if not dst_folder.is_dir():
        raise NotADirectoryError(str(dst_folder))

    dst = resolve_allowed_path(str(dst_folder / src.name))
    if dst.exists():
        raise FileExistsError(str(dst))

    shutil.move(str(src), str(dst))
    return f"Moved to: {dst}"


def delete_path(path: str, confirmed: bool = False) -> str:
    if not confirmed:
        return (
            "CONFIRMATION_REQUIRED: Ask the user to confirm deletion "
            f"of {path!r} before calling this function again with confirmed=True."
        )

    target = resolve_allowed_path(path)

    if not target.exists():
        raise FileNotFoundError(str(target))

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    return f"Deleted: {target}"


def open_path(path: str) -> str:
    target = resolve_allowed_path(path)

    if not target.exists():
        raise FileNotFoundError(str(target))

    os.startfile(str(target))
    return f"Opened: {target}"


def open_website(url: str) -> str:
    if not url.startswith(("https://", "http://")):
        raise ValueError("Only HTTP and HTTPS URLs are allowed.")

    webbrowser.open(url)
    return f"Opened website: {url}"


def play_youtube(query: str) -> str:
    from urllib.parse import quote_plus

    url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    webbrowser.open(url)
    return f"Opened YouTube search for: {query}"


def set_system_volume(level: int) -> str:
    if not 0 <= level <= 100:
        raise ValueError("Volume must be between 0 and 100.")

    devices = AudioUtilities.GetSpeakers()
    volume = devices.EndpointVolume
    volume.SetMasterVolumeLevelScalar(level / 100.0, None)

    return f"System volume set to {level}%."
