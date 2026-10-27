"""Safe desktop tools for Belizarius (Windows-oriented)."""
import os
import re
import webbrowser
from pathlib import Path
from urllib.parse import quote, urlsplit

WORKSPACE = Path(__file__).resolve().parent.parent / "Belizarius_Workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)


def safe_path(name: str) -> Path:
    """Resolve a relative path and confine it to Belizarius_Workspace."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A non-empty relative file path is required.")

    candidate = Path(name)
    if candidate.is_absolute():
        raise ValueError("Use a relative path inside Belizarius_Workspace.")

    target = (WORKSPACE / candidate).resolve()
    root = WORKSPACE.resolve()
    if target != root and root not in target.parents:
        raise PermissionError("Access denied: path is outside Belizarius_Workspace.")
    return target


def create_file(name: str, content: str = "") -> str:
    target = safe_path(name)
    if target.exists():
        raise FileExistsError(f"{name} already exists; ask before overwriting it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Created text file: {target}"


def read_file(name: str) -> str:
    target = safe_path(name)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {name}")
    if target.stat().st_size > 1_000_000:
        raise ValueError("File is too large to read (limit: 1 MB).")
    return target.read_text(encoding="utf-8")[:20000]


def write_file(name: str, content: str) -> str:
    target = safe_path(name)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {name}. Use create_file first.")
    target.write_text(content, encoding="utf-8")
    return f"Updated text file: {target}"


def open_file(name: str) -> str:
    target = safe_path(name)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {name}")
    if not hasattr(os, "startfile"):
        raise OSError("Opening files with the default application is supported on Windows.")
    os.startfile(str(target))
    return f"Opened file: {target}"


def open_website(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only complete HTTP or HTTPS website URLs are allowed.")
    webbrowser.open(url)
    return f"Opened website in the default browser: {url}"


def play_youtube(query: str) -> str:
    from urllib.parse import quote_plus

    if not query or not query.strip():
        raise ValueError("Please provide a song, artist, or music search.")
    search_query = query.strip()
    url = "https://www.youtube.com/results?search_query=" + quote_plus(search_query)
    webbrowser.open(url)
    return f"Opened YouTube search results for: {search_query}. Select a result to start playback."


def compose_email(recipient_email: str, subject: str, body: str) -> str:
    """Open a draft only; never sends mail."""
    recipient = recipient_email.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient):
        raise ValueError("That does not look like a valid email address.")
    if not subject.strip():
        raise ValueError("Email subject cannot be empty.")

    # mailto opens the user's configured mail handler; it does not send the message.
    mailto = (
        f"mailto:{quote(recipient, safe='@')}"
        f"?subject={quote(subject, safe='')}"
        f"&body={quote(body, safe='')}"
    )
    opened = webbrowser.open(mailto)
    if not opened:
        return (
            f"Prepared email details for {recipient}, but the system did not confirm "
            "opening the default mail handler. No email was sent."
        )
    return (
        f"Opened an email draft addressed to {recipient} with the supplied subject and body. "
        "No email was sent; review and send it yourself."
    )
