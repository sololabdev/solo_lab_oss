"""
Unified LLM client for benchmark — backs onto either Anthropic SDK directly
or OpenRouter as a fallback when the Anthropic balance is empty.

Why two paths:
- Anthropic direct = first-class prompt caching (the cache_control: ephemeral
  hook that makes 90 reuses of the same 700K context cost ~10% of full price).
- OpenRouter = same model, no first-class cache_control, but works when
  Anthropic balance is zero. ~Same per-token cost.

Pick via env:
    LLM_BACKEND=anthropic    # default, requires ANTHROPIC_API_KEY + balance
    LLM_BACKEND=openrouter   # uses OPENROUTER_API_KEY, no cache discount

Env vars:
    ANTHROPIC_API_KEY        — required if backend=anthropic
    OPENROUTER_API_KEY       — required if backend=openrouter
    OPENROUTER_KEY_FILE      — optional override path to a key-on-disk
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float | None  # None if backend doesn't expose; estimate from tokens
    elapsed_s: float
    backend: str


def _resolve_openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key.strip()
    # Optional file fallback — opt-in via env var, no hardcoded host paths.
    file_override = os.environ.get("OPENROUTER_KEY_FILE")
    if file_override:
        p = Path(file_override).expanduser()
        if p.exists():
            return p.read_text().strip()
    raise RuntimeError(
        "OPENROUTER_API_KEY not set. Either export the env var, "
        "or set OPENROUTER_KEY_FILE=/path/to/keyfile."
    )


class AnthropicBackend:
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self.client = anthropic.Anthropic(api_key=key)

    def call(
        self,
        model: str,
        system_blocks: list[dict],
        user_prompt: str,
        max_tokens: int,
    ) -> LLMResponse:
        t0 = time.time()
        resp = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user_prompt}],
        )
        elapsed = time.time() - t0
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        u = resp.usage
        # Pricing constants for claude-opus-4-7 (per 1M tokens, USD).
        # Anthropic prompt caching has 4 buckets:
        #   - non-cached input  : $15.00
        #   - cache write       : $18.75 (input + 25% premium for first write)
        #   - cache read        : $1.50  (input × 0.10 — 90% discount)
        #   - output            : $75.00
        # Verify against https://www.anthropic.com/pricing for current rates.
        IN, CACHE_WRITE, CACHE_READ, OUT = 15.0, 18.75, 1.50, 75.0
        cache_create = getattr(u, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        # input_tokens excludes cached portions per Anthropic API contract
        non_cached_in = (u.input_tokens or 0)
        cost = (
            non_cached_in / 1e6 * IN
            + cache_create / 1e6 * CACHE_WRITE
            + cache_read / 1e6 * CACHE_READ
            + (u.output_tokens or 0) / 1e6 * OUT
        )
        return LLMResponse(
            text=text,
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cost_usd=round(cost, 4),
            elapsed_s=elapsed,
            backend=self.name,
        )


class OpenRouterBackend:
    """Maps anthropic-style messages.create to OpenRouter chat-completions.

    OpenRouter does NOT honour Anthropic-flavoured cache_control blocks, so the
    full input is billed every call. For the benchmark this means the realistic
    spend at 90 calls is closer to $25-30 than the $5-10 with Anthropic-direct
    caching. Document this in the run summary.

    Model name mapping: drop hyphen → dot for the OpenRouter slug.
        claude-opus-4-7 -> anthropic/claude-opus-4.7
    """
    name = "openrouter"
    URL = "https://openrouter.ai/api/v1/chat/completions"

    MODEL_MAP = {
        "claude-opus-4-7": "anthropic/claude-opus-4.7",
        "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
        "claude-haiku-4-5": "anthropic/claude-haiku-4.5",
    }

    def __init__(self) -> None:
        self.key = _resolve_openrouter_key()

    def _to_or_messages(self, system_blocks: list[dict], user_prompt: str) -> list[dict]:
        """Anthropic system list -> single combined system message in OR format."""
        sys_text = "\n\n".join(
            b["text"] for b in system_blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )
        return [
            {"role": "system", "content": sys_text},
            {"role": "user", "content": user_prompt},
        ]

    def call(
        self,
        model: str,
        system_blocks: list[dict],
        user_prompt: str,
        max_tokens: int,
    ) -> LLMResponse:
        or_model = self.MODEL_MAP.get(model, model)
        body = json.dumps({
            "model": or_model,
            "messages": self._to_or_messages(system_blocks, user_prompt),
            "max_tokens": max_tokens,
            "usage": {"include": True},  # ask OR to include cost
        }).encode()
        req = urllib.request.Request(
            self.URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://solo-lab.dev",
                "X-Title": "Solo Lab benchmark",
            },
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                rj = json.load(r)
        except urllib.error.HTTPError as e:
            # Surface the OR error body — otherwise rate-limit / model-not-found
            # debugging is opaque ("HTTP Error 429" with no detail).
            try:
                detail = e.read().decode("utf-8", errors="replace")[:500]
            except OSError:
                detail = "<could not read error body>"
            raise RuntimeError(
                f"OpenRouter HTTP {e.code}: {detail}"
            ) from e
        elapsed = time.time() - t0
        text = rj["choices"][0]["message"]["content"]
        usage = rj.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cache_creation_input_tokens=0,  # OR doesn't expose cache shape
            cache_read_input_tokens=0,
            cost_usd=float(usage.get("cost") or 0.0),
            elapsed_s=elapsed,
            backend=self.name,
        )


def get_backend(name: str | None = None):
    name = (name or os.environ.get("LLM_BACKEND") or "anthropic").lower()
    if name == "openrouter":
        return OpenRouterBackend()
    if name == "anthropic":
        return AnthropicBackend()
    raise ValueError(f"unknown backend: {name}")


if __name__ == "__main__":
    # Smoke-test both backends if env supports it
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "openrouter"
    be = get_backend(target)
    sys_b = [{"type": "text", "text": "You are a terse assistant."}]
    r = be.call("claude-opus-4-7", sys_b, "Reply with: pong", 20)
    print(f"backend={r.backend} text={r.text!r} in={r.input_tokens} out={r.output_tokens}"
          f" cost=${r.cost_usd:.6f} t={r.elapsed_s:.2f}s")
