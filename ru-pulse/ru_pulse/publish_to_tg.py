"""Thin Telegram publish helper for ru_pulse.

Replaces the print-only `publish_to_stdout` path in weekly_pulse with a real
Bot API send. Stdlib-only HTTP via urllib.request, credentials read from
`$CREDENTIALS_DIR` (env var) or `~/.openclaw/credentials/` (default).

CLI:
    python -m ru_pulse.publish_to_tg --channel ru --file path/to/post.html
    python -m ru_pulse.publish_to_tg --channel ru --text "<b>hi</b>"
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CREDENTIALS_DIR = Path(
    os.environ.get("CREDENTIALS_DIR", "") or Path.home() / ".openclaw" / "credentials"
)
TOKEN_FILE = CREDENTIALS_DIR / "telegram-token.txt"
CHANNELS_FILE = CREDENTIALS_DIR / "tg-channels.json"

TG_LIMIT = 4096
API_URL = "https://api.telegram.org/bot{token}/sendMessage"
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_comments(text: str) -> str:
    """Remove HTML comment markers (e.g. ``<!-- refined:v1 -->``)."""
    return COMMENT_RE.sub("", text).strip()


def _split_html(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Split text into <=limit chunks, preferring tag/newline boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind("> ")
            cut = cut + 1 if cut != -1 else cut
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def load_token(path: Path = TOKEN_FILE) -> str:
    """Read the bot token from disk; raise RuntimeError if missing/empty."""
    if not path.exists():
        raise RuntimeError(
            f"Telegram bot token not found at {path}. "
            f"Create it with `echo <token> > {path}` and chmod 600."
        )
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"Telegram bot token at {path} is empty.")
    return token


def load_chat_id(channel: str, path: Path = CHANNELS_FILE) -> str:
    """Resolve a channel key (e.g. 'ru') to its chat_id from tg-channels.json."""
    if not path.exists():
        raise RuntimeError(
            f"TG channels map not found at {path}. "
            f"Expected JSON with key '{channel}' -> {{'chat_id': '-100...'}}."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"TG channels map at {path} is not valid JSON: {exc}") from exc
    entry = data.get(channel)
    if not entry or not entry.get("chat_id"):
        raise RuntimeError(
            f"Channel '{channel}' not found in {path}. "
            f"Available keys: {sorted(data.keys()) or '[]'}."
        )
    return str(entry["chat_id"])


def _post(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST a sendMessage payload; raise RuntimeError on HTTP/API failure."""
    url = API_URL.format(token=token)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"Telegram HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram network error: {exc.reason}") from exc

    if status != 200:
        raise RuntimeError(f"Telegram HTTP {status}: {raw}")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Telegram returned non-JSON body: {raw!r}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result


def send_message(
    text: str,
    chat_id: str,
    token: str,
    parse_mode: str = "HTML",
    disable_preview: bool = True,
) -> dict[str, Any]:
    """Send `text` to `chat_id`, splitting >4096 chars. Returns the LAST response."""
    cleaned = _strip_comments(text)
    if not cleaned:
        raise RuntimeError("Refusing to send empty message after comment strip.")
    chunks = _split_html(cleaned)
    logger.info("sending %d chunk(s) to %s", len(chunks), chat_id)
    last: dict[str, Any] = {}
    for idx, chunk in enumerate(chunks, 1):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }
        last = _post(token, payload)
        logger.info("chunk %d/%d ok (message_id=%s)", idx, len(chunks),
                    last.get("result", {}).get("message_id"))
    return last


def _main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: read text from --file or --text and send to --channel."""
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(prog="ru_pulse.publish_to_tg")
    p.add_argument("--channel", required=True, help="key in tg-channels.json (e.g. 'ru')")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", type=Path, help="path to a file with the post body")
    src.add_argument("--text", help="inline text to send")
    p.add_argument("--parse-mode", default="HTML")
    p.add_argument("--enable-preview", action="store_true")
    args = p.parse_args(argv)

    try:
        token = load_token()
        chat_id = load_chat_id(args.channel)
        text = args.file.read_text(encoding="utf-8") if args.file else args.text
        send_message(
            text=text, chat_id=chat_id, token=token,
            parse_mode=args.parse_mode, disable_preview=not args.enable_preview,
        )
    except RuntimeError as exc:
        logger.error("publish failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
