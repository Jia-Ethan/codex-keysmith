#!/usr/bin/env python3
"""ks-envelope — local Responses-to-messages protocol adapter for keysmith.

Pure stdlib. Listens on a loopback-only port, accepts Codex Responses-API
requests (/v1/responses), translates each into an Anthropic-shaped
/v1/messages call against the upstream gateway, and translates the
reply back into a Responses-API response object so Codex keeps its
OpenAI client.

Security posture:
- loopback bind only (127.0.0.1); non-loopback bind is refused
- upstream credential read from --auth-file or CODEX_KEYSMITH_AUTH (default
  ~/.codex/auth.json, OPENAI_API_KEY field); never written to disk by this
  tool, never echoed in logs
- request bodies and error strings are redacted before logging

Engine: Python 3.9+ | Language: Python
Run:  python3 scripts/ks-envelope.py --port 8091
      # then point Codex at it, e.g. in an isolated CODEX_HOME:
      #   model_providers.keysmith.base_url = "http://127.0.0.1:8091/v1"
Deps: none (stdlib only)
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import http.client
import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

DEFAULT_UPSTREAM = "https://lgw.gru.ai/v1"
DEFAULT_AUTH_PATH = Path.home() / ".codex" / "auth.json"
LOCAL_PREFIX = "/v1"
UPSTREAM_MESSAGES = "/messages"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
UPSTREAM_TIMEOUT_SECONDS = 300
KEEPALIVE_INTERVAL_SECONDS = 1.0
SSE_IDLE_TIMEOUT_SECONDS = 1.0
KEEPALIVE_COMMENT = b": keepalive\n\n"
COALESCE_TTL_SECONDS = 60.0
_TOOL_ITEM_TYPES = (
    "function_call",
    "custom_tool_call",
    "function_call_output",
    "custom_tool_call_output",
)

SECRET_PATTERNS = (
    "OPENAI_API_KEY",
    "Authorization",
    "x-api-key",
)


class EnvelopeError(Exception):
    """Adapter-local failure with a safe, redacted message."""


class _FrameBuffer:
    """Thread-safe SSE capture that reconnect POSTs can tail while the leader is live.

    Codex retries an in-flight turn by opening a new /responses POST. If that
    POST waits until the leader finishes before sending headers, the desktop
    client sees a silent socket, counts a reconnect (1/5 … 5/5), and surfaces
    ``stream_interrupted``. Waiters must emit SSE (keepalives + captured
    frames) immediately.
    """

    def __init__(self) -> None:
        self._data = bytearray()
        self._cv = threading.Condition()
        self._done = False

    def extend(self, frame: bytes) -> None:
        if not frame:
            return
        with self._cv:
            self._data.extend(frame)
            self._cv.notify_all()

    def mark_done(self) -> None:
        with self._cv:
            self._done = True
            self._cv.notify_all()

    def wait_more(self, offset: int, timeout: float) -> Tuple[bytes, int, bool]:
        deadline = time.time() + max(0.0, timeout)
        with self._cv:
            while True:
                if offset < len(self._data) or self._done:
                    chunk = bytes(self._data[offset:])
                    return chunk, len(self._data), self._done
                remaining = deadline - time.time()
                if remaining <= 0:
                    return b"", offset, self._done
                self._cv.wait(remaining)

    def __len__(self) -> int:
        with self._cv:
            return len(self._data)

    def __bool__(self) -> bool:
        return len(self) > 0

    def __bytes__(self) -> bytes:
        with self._cv:
            return bytes(self._data)


class _CoalescedTurn:
    """One in-flight or recently finished stream, shared across reconnect POSTs."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.frames = _FrameBuffer()
        self.error: Optional[BaseException] = None
        self.finished_at = 0.0


_coalesce_lock = threading.Lock()
_coalesce: Dict[str, _CoalescedTurn] = {}


def reset_coalesce_state() -> None:
    """Test helper: drop in-flight and cached stream slots."""
    with _coalesce_lock:
        _coalesce.clear()


def _content_text(item: Dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for block in content:
        if isinstance(block, str) and block:
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in (
            "input_text",
            "output_text",
            "text",
            "summary_text",
        ):
            text = str(block.get("text") or "")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _request_fingerprint(body: Dict[str, Any]) -> str:
    """Stable across Codex retries: ignore item ids and developer/memory-router churn."""
    parts: List[str] = [
        str(body.get("model") or ""),
        "stream=" + ("1" if body.get("stream") is True else "0"),
    ]
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        parts.append("effort=" + str(reasoning.get("effort")))
    raw = body.get("input")
    last_user = ""
    if isinstance(raw, str):
        last_user = raw.strip()
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            itype = str(item.get("type") or "")
            role = item.get("role")
            if itype in _TOOL_ITEM_TYPES:
                parts.append(
                    itype
                    + ":"
                    + str(item.get("name") or "")
                    + ":"
                    + str(item.get("call_id") or item.get("id") or "")
                )
                continue
            if role == "user":
                text = _content_text(item)
                if text:
                    last_user = text
    if last_user:
        parts.append("user:" + last_user)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _coalesce_begin(fingerprint: str) -> Tuple[_CoalescedTurn, bool]:
    now = time.time()
    with _coalesce_lock:
        stale = [
            key
            for key, slot in _coalesce.items()
            if slot.done.is_set() and now - slot.finished_at > COALESCE_TTL_SECONDS
        ]
        for key in stale:
            _coalesce.pop(key, None)
        existing = _coalesce.get(fingerprint)
        if existing is not None and (
            not existing.done.is_set()
            or now - existing.finished_at <= COALESCE_TTL_SECONDS
        ):
            sys.stderr.write(
                "[ks-envelope] coalesce replay fp=%s\n" % fingerprint[:16]
            )
            sys.stderr.flush()
            return existing, False
        slot = _CoalescedTurn()
        _coalesce[fingerprint] = slot
        sys.stderr.write("[ks-envelope] coalesce leader fp=%s\n" % fingerprint[:16])
        sys.stderr.flush()
        return slot, True


def _coalesce_finish(
    slot: _CoalescedTurn, error: Optional[BaseException] = None
) -> None:
    if error is not None and slot.error is None:
        slot.error = error
    slot.finished_at = time.time()
    slot.done.set()
    slot.frames.mark_done()


class _SseKeepalive:
    """Write SSE comments while the upstream is silent so Codex does not idle-retry."""

    def __init__(
        self,
        wfile: Any,
        capture: Any = None,
        interval: Optional[float] = None,
        should_write: Optional[Any] = None,
        live: Any = None,
    ) -> None:
        self.wfile = wfile
        self.capture = capture
        self.should_write = should_write
        self.live = live
        self.interval = (
            KEEPALIVE_INTERVAL_SECONDS if interval is None else interval
        )
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.resp_id = ""

    def start(self) -> None:
        if self.interval <= 0:
            return
        self._thread = threading.Thread(
            target=self._run, name="ks-sse-keepalive", daemon=True
        )
        self._thread.start()

    def _progress_frame(self) -> bytes:
        if not self.resp_id:
            return KEEPALIVE_COMMENT
        return KEEPALIVE_COMMENT + _sse_event(
            "response.in_progress",
            {
                "type": "response.in_progress",
                "response": {"id": self.resp_id, "status": "in_progress"},
            },
        )

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            if self.should_write is not None and not self.should_write():
                return
            if self.live is not None:
                frame = KEEPALIVE_COMMENT + b"".join(self.live.heartbeat())
                if not self.emit(frame, capture=True):
                    return
                continue
            if not self.emit(self._progress_frame(), capture=False):
                return

    def emit(self, frame: bytes, capture: bool = True) -> bool:
        if b"event: response.created" in frame and not self.resp_id:
            marker = b'"id": "'
            start = frame.find(marker)
            if start >= 0:
                start += len(marker)
                end = frame.find(b'"', start)
                if end > start:
                    self.resp_id = frame[start:end].decode("ascii", errors="replace")
        # Capture before write so reconnect waiters keep the generation even
        # after this socket is superseded or the original client hangs up.
        if capture and self.capture is not None and not frame.startswith(b":"):
            self.capture.extend(frame)
        if self.should_write is not None and not self.should_write():
            return True
        try:
            with self._lock:
                self.wfile.write(frame)
                self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._stop.set()
            return False

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)


def load_upstream_key(auth_file: Path) -> str:
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EnvelopeError(
            f"auth file not found: {auth_file} (set --auth-file or "
            "CODEX_KEYSMITH_AUTH)"
        ) from None
    except (OSError, ValueError) as exc:
        raise EnvelopeError(f"auth file unreadable: {auth_file}: {exc}") from exc
    key = data.get("OPENAI_API_KEY") if isinstance(data, dict) else None
    if not isinstance(key, str) or not key:
        raise EnvelopeError(f"auth file has no OPENAI_API_KEY: {auth_file}")
    return key


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        text = text.replace(secret, "<redacted>")
    return text


# --- request translation: Responses API -> Anthropic messages ----------------

_FUNCTIONS_WRAPPER_NAMES = {"functions", "function", "tools"}
_EXEC_NESTED_METHODS = {"exec_command", "apply_patch", "write_stdin"}
_COLLAB_METHODS = {
    "followup_task",
    "interrupt_agent",
    "list_agents",
    "send_message",
    "spawn_agent",
    "wait_agent",
}
_CUSTOM_TOOL_NAMES = {"exec"}


def _function_input_schema(tool: Dict[str, Any]) -> Dict[str, Any]:
    params = tool.get("parameters")
    if isinstance(params, dict) and params.get("type") == "object":
        return params
    return {
        "type": "object",
        "properties": {"input": {"type": "string"}},
        "required": ["input"],
    }


def _translate_one_tool(tool: Dict[str, Any]) -> List[Dict[str, Any]]:
    ttype = tool.get("type")
    if ttype == "namespace":
        nested: List[Dict[str, Any]] = []
        for child in tool.get("tools") or []:
            if isinstance(child, dict):
                nested.extend(_translate_one_tool(child))
        return nested
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        return []
    if ttype == "function":
        return [
            {
                "name": name,
                "description": str(tool.get("description") or ""),
                "input_schema": _function_input_schema(tool),
            }
        ]
    return [
        {
            "name": name,
            "description": str(tool.get("description") or ""),
            "input_schema": {
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
            },
        }
    ]


def _translate_tools(raw_input: Any) -> List[Dict[str, Any]]:
    """Map Responses additional_tools declarations to anthropic tools.

    Custom grammar tools stay as a single string ``input``. JSON-schema
    ``function`` tools keep their ``parameters``. ``namespace`` tools are
    expanded to the nested function tools Codex actually dispatches
    (``send_message``, ``spawn_agent``, …). Flattening a namespace into
    one string-input tool is what made gpt-6-astra emit a wrapper call
    named ``functions``, which Codex rejects as an unknown custom tool.
    """
    tools: List[Dict[str, Any]] = []
    if not isinstance(raw_input, list):
        return tools
    seen = set()
    for item in raw_input:
        if not isinstance(item, dict) or item.get("type") != "additional_tools":
            continue
        for tool in item.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            for translated in _translate_one_tool(tool):
                name = translated["name"]
                if name in seen:
                    continue
                seen.add(name)
                tools.append(translated)
    return tools


def _parse_tool_arguments(arguments: Any) -> Any:
    if isinstance(arguments, str):
        text = arguments.strip()
        if text[:1] in "{[":
            try:
                return json.loads(text)
            except ValueError:
                return arguments
        return arguments
    return arguments


def _exec_js_call(method: str, arguments: Any) -> str:
    if not method.isidentifier():
        method = "exec_command"
    if isinstance(arguments, dict):
        arg = json.dumps(arguments, ensure_ascii=False)
    elif isinstance(arguments, str):
        arg = json.dumps(arguments, ensure_ascii=False)
    elif arguments is None:
        arg = "{}"
    else:
        arg = json.dumps(arguments, ensure_ascii=False)
    return f"text(await tools.{method}({arg}));"


def _normalize_tool_call(name: str, arguments: Any) -> Tuple[str, str, str]:
    """Map an upstream tool_use onto a Codex custom or function call.

    Returns ``(name, payload, kind)``. ``kind`` is ``custom`` (payload is
    grammar source for ``custom_tool_call.input``) or ``function``
    (payload is a JSON string for ``function_call.arguments``).

    Live desktop session 2026-09-11: the model emitted
    ``name=functions`` / ``{"tool":"exec_command","arguments":{"cmd":"pwd"}}``.
    Codex replied ``unsupported custom tool call: functions`` and never
    ran the command. Nested exec methods belong on the ``exec`` grammar
    tool, not as a wrapper name.
    """
    parsed = _parse_tool_arguments(arguments)
    if name in _CUSTOM_TOOL_NAMES and isinstance(parsed, dict) and set(parsed.keys()) == {"input"}:
        parsed = parsed["input"]
        parsed = _parse_tool_arguments(parsed)
    label = (name or "").strip()
    if label in _FUNCTIONS_WRAPPER_NAMES and isinstance(parsed, dict):
        inner = parsed.get("tool") or parsed.get("name") or parsed.get("function")
        inner_args = (
            parsed.get("arguments")
            or parsed.get("parameters")
            or parsed.get("args")
            or {}
        )
        if isinstance(inner, str) and inner.strip():
            return _normalize_tool_call(inner.strip(), inner_args)
    if label in _EXEC_NESTED_METHODS:
        return "exec", _exec_js_call(label, parsed), "custom"
    if label in _COLLAB_METHODS:
        if isinstance(parsed, dict):
            payload = json.dumps(parsed, ensure_ascii=False)
        elif isinstance(parsed, str):
            payload = parsed
        elif parsed is None:
            payload = "{}"
        else:
            payload = json.dumps(parsed, ensure_ascii=False)
        return label, payload, "function"
    if label in _CUSTOM_TOOL_NAMES or label == "exec":
        if isinstance(parsed, dict) and "cmd" in parsed:
            return "exec", _exec_js_call("exec_command", parsed), "custom"
        if isinstance(parsed, str):
            return "exec", parsed, "custom"
        if parsed is None:
            return "exec", "", "custom"
        return "exec", json.dumps(parsed, ensure_ascii=False), "custom"
    if isinstance(parsed, dict):
        payload = json.dumps(parsed, ensure_ascii=False)
    elif isinstance(parsed, str):
        payload = parsed
    elif parsed is None:
        payload = "{}"
    else:
        payload = json.dumps(parsed, ensure_ascii=False)
    return label or "exec", payload, "function" if label else "custom"


def _tool_call_input(item: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """History tool_call → (name, anthropic tool_use.input)."""
    raw_name = str(item.get("name") or "")
    raw_args = item.get("arguments", item.get("input"))
    name, payload, kind = _normalize_tool_call(raw_name, raw_args)
    if kind == "custom":
        return name, {"input": payload}
    parsed = _parse_tool_arguments(payload)
    if isinstance(parsed, dict):
        return name, parsed
    return name, {"input": payload}


def _tool_output_text(item: Dict[str, Any]) -> str:
    output = item.get("output")
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        return json.dumps(output, ensure_ascii=False)
    if isinstance(output, list):
        # Codex custom_tool_call_output carries a list of input_text blocks
        # (phase 0 wire capture, breaktest-results/toolregression-v070).
        parts = []
        for block in output:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p)
    return ""


def _item_text(item: Dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") in (
                    "input_text",
                    "output_text",
                    "text",
                    "summary_text",
                ):
                    parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    raise EnvelopeError("input item content is not text")


def _anthropic_image_block(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = block.get("image_url") or block.get("url")
    if not isinstance(url, str) or not url:
        source = block.get("source")
        if isinstance(source, dict) and isinstance(source.get("data"), str):
            media = str(source.get("media_type") or "image/png")
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media,
                    "data": source["data"],
                },
            }
        return None
    if url.startswith("data:") and "," in url:
        header, data = url.split(",", 1)
        media = "image/png"
        rest = header[5:] if header.startswith("data:") else header
        if ";" in rest:
            media = rest.split(";", 1)[0] or media
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media, "data": data},
        }
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _message_content_blocks(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    content = item.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        text = _item_text(item)
        return [{"type": "text", "text": text}] if text else []
    blocks: List[Dict[str, Any]] = []
    text_parts: List[str] = []

    def flush_text() -> None:
        if text_parts:
            blocks.append({"type": "text", "text": "\n".join(text_parts)})
            text_parts.clear()

    for block in content:
        if isinstance(block, str):
            if block:
                text_parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in ("input_text", "output_text", "text", "summary_text"):
            text = str(block.get("text", ""))
            if text:
                text_parts.append(text)
        elif btype in ("input_image", "image"):
            image = _anthropic_image_block(block)
            if image is not None:
                flush_text()
                blocks.append(image)
    flush_text()
    return blocks


def translate_request(
    body: Dict[str, Any],
    thinking_passthrough: bool = False,
    overlay_text: str = "",
) -> Dict[str, Any]:
    """Map a Responses-API request onto the Anthropic messages shape.

    Two request shapes are accepted:

    - Simple: top-level ``instructions`` + string/block ``input`` items
      (the raw-HTTP shape used by the bank runners).
    - Codex: ``input`` is a list of typed items; ``type: message`` items
      carry ``role`` (developer/user/assistant) and ``input_text`` blocks;
      ``type: additional_tools`` developer items are dropped (the upstream
      messages arm has no matching tool surface — bank runs never need it);
      every developer-message text is prepended to the ``system`` string in
      arrival order (that is where Codex puts model_instructions_file
      content), user/assistant items become the messages array.

    ``max_output_tokens`` maps to ``max_tokens``; ``stream`` requests are
    handled by the caller (see do_POST). temperature/top_p pass through
    when numeric.
    """
    if not isinstance(body, dict):
        raise EnvelopeError("request body is not a JSON object")
    messages: List[Dict[str, Any]] = []
    system_parts: List[str] = []
    raw_input = body.get("input")
    if isinstance(raw_input, str):
        messages.append(
            {"role": "user", "content": [{"type": "text", "text": raw_input}]}
        )
    elif isinstance(raw_input, list):
        for item in raw_input:
            if not isinstance(item, dict):
                raise EnvelopeError("input item is not an object")
            item_type = item.get("type")
            if item_type == "additional_tools":
                # Translated by _translate_tools into anthropic tool schemas.
                continue
            if item_type in ("function_call", "custom_tool_call"):
                hist_name, hist_input = _tool_call_input(item)
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": str(item.get("call_id") or item.get("id") or ""),
                                "name": hist_name,
                                "input": hist_input,
                            }
                        ],
                    }
                )
                continue
            if item_type in ("function_call_output", "custom_tool_call_output"):
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": str(item.get("call_id") or ""),
                                "content": (
                                    _message_content_blocks({"content": item["output"]})
                                    if isinstance(item.get("output"), list) and any(
                                        isinstance(block, dict)
                                        and block.get("type") in ("input_image", "image")
                                        for block in item["output"]
                                    ) else _tool_output_text(item)
                                ),
                            }
                        ],
                    }
                )
                continue
            role = item.get("role", "user")
            if role == "developer":
                text = _item_text(item)
                if text:
                    system_parts.append(text)
                continue
            if role not in ("user", "assistant"):
                role = "user"
            content_blocks = _message_content_blocks(item)
            if not content_blocks:
                continue
            messages.append({"role": role, "content": content_blocks})
    else:
        raise EnvelopeError("request has no usable input field")

    if not messages:
        # Tool-result-only follow-ups still carry the conversation; if nothing
        # else remains, the request is unusable for the messages arm.
        raise EnvelopeError("request has no user/assistant messages")

    tool_items = list(raw_input) if isinstance(raw_input, list) else []
    if isinstance(body.get("tools"), list):
        tool_items.append({"type": "additional_tools", "tools": body["tools"]})
    tools = _translate_tools(tool_items)

    out: Dict[str, Any] = {
        "model": body.get("model"),
        # Tool-call turns carry the model's full working output; the previous
        # 4096 floor truncated agentic sessions mid-tool-call on this gateway
        # (Phase 0 finding). Map the client's max_output_tokens when present,
        # else default high.
        "max_tokens": body.get("max_output_tokens") or 16384,
        "messages": messages,
    }
    if tools:
        out["tools"] = tools
        out["tool_choice"] = {"type": "auto"}
    if not out["model"] or not isinstance(out["model"], str):
        raise EnvelopeError("request has no model")
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions:
        system_parts.insert(0, instructions)
    # Overlay contract: appended AFTER the stock instructions and developer
    # items, never replacing them (recency position). This is the injection
    # point for the keysmith overlay preset (--overlay-file).
    if overlay_text:
        system_parts.append(overlay_text)

    # The messages arm hangs if we emit an anthropic thinking block
    # (--thinking-passthrough). Still honor Codex's effort so high/xhigh
    # turns do not collapse to a short first-token reply.
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        effort = reasoning.get("effort")
        depth_label = {
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "extra-high",
            "max": "maximum",
        }.get(effort) if isinstance(effort, str) else None
        budgets = {"low": 1024, "medium": 4096, "high": 8192, "xhigh": 16384}
        if thinking_passthrough and effort in budgets:
            out["thinking"] = {"type": "enabled", "budget_tokens": budgets[effort]}
        elif effort in ("high", "xhigh", "max"):
            # Keep LGW SSE alive during gpt-5.6-sol high-effort turns.
            # Without a thinking block the gateway sits silent ~15s then
            # drops the stream (envelope e2e: response.incomplete /
            # stream_interrupted at 16.5s). Cap 4096 so the messages arm
            # does not hang on the old unbounded budget.
            out["thinking"] = {"type": "enabled", "budget_tokens": 4096}
        elif depth_label:
            system_parts.append(
                f"Work this turn at {depth_label} depth. Inspect the named "
                "files, then act. A plan without an executed step is unfinished."
            )

    if system_parts:
        out["system"] = "\n\n".join(p for p in system_parts if p)
    for passthrough in ("temperature", "top_p"):
        value = body.get(passthrough)
        if isinstance(value, (int, float)):
            out[passthrough] = value
    return out


# --- response translation: chat.completion -> Responses API -------------------

def _upstream_tool_calls(choice: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract OpenAI-style tool_calls from a gateway chat.completion choice."""
    message = choice.get("message")
    if not isinstance(message, dict):
        return []
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return []
    result = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if isinstance(function, dict):
            result.append(
                {
                    "id": call.get("id"),
                    "name": function.get("name"),
                    "arguments": function.get("arguments"),
                }
            )
        elif call.get("name"):
            result.append(
                {"id": call.get("id"), "name": call.get("name"), "arguments": call.get("input")}
            )
    return result


def _anthropic_output(upstream: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], str]:
    """Decode an anthropic-messages reply body.

    Returns (text, tool_calls, stop_reason). Tool calls are normalized to
    {id, name, arguments}; arguments retain the original input object until
    tool-specific normalization. The anthropic reply shape is
    ``content: [{type:"text"|"tool_use", ...}]`` at the top level with
    ``stop_reason``; anything lacking both anthropic and chat.completion
    markers returns a sentinel stop_reason so the caller can fall through.
    """
    blocks = upstream.get("content")
    if not isinstance(blocks, list):
        return "", [], ""
    text_parts: List[str] = []
    calls: List[Dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(str(block.get("text", "")))
        elif block_type == "tool_use":
            arguments = block.get("input")
            calls.append(
                {
                    "id": block.get("id"),
                    "name": str(block.get("name") or ""),
                    "arguments": arguments,
                }
            )
    return "\n".join(p for p in text_parts if p), calls, str(
        upstream.get("stop_reason") or ""
    )


def _unwrap_tool_input(arguments: Any) -> str:
    """Normalize a tool_use input to the string the tool's grammar expects.

    The request side declares every tool as ``input_schema: {input: string}``
    (see _translate_tools), so a well-behaved upstream emits
    ``{"input": "<raw grammar source>"}``. Codex's custom tools expect the
    RAW grammar source (JS for the exec tool), not the JSON envelope — a
    JSON-wrapped string is a JS syntax error at the ``:`` and the model
    loops on it (e2e evidence: 20 requests, every custom_tool_call output
    'SyntaxError: Unexpected token :'). Unwrap {"input": str} here;
    anything else is passed through as-is.
    """
    if isinstance(arguments, dict):
        if set(arguments.keys()) == {"input"} and isinstance(arguments["input"], str):
            return arguments["input"]
        return json.dumps(arguments, ensure_ascii=False)
    if isinstance(arguments, str):
        return arguments
    if arguments is None:
        return ""
    return json.dumps(arguments, ensure_ascii=False)


def _chat_completion_output(
    upstream: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]], str, Dict[str, Any]]:
    """Decode a chat.completion reply body into (text, tool_calls, finish, usage)."""
    choices = upstream.get("choices")
    if not isinstance(choices, list) or not choices:
        raise EnvelopeError("upstream reply has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise EnvelopeError("upstream choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise EnvelopeError("upstream choice has no message")
    content = message.get("content")
    text = content if isinstance(content, str) else json.dumps(
        content, ensure_ascii=False
    ) if content is not None else ""
    usage = upstream.get("usage") if isinstance(upstream.get("usage"), dict) else {}
    return text, _upstream_tool_calls(first), str(first.get("finish_reason") or ""), usage


def _extract_output(upstream: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], str, Dict[str, Any]]:
    """Shape-sniff the upstream reply: anthropic first, chat.completion second.

    Phase 0 evidence (breaktest-results/toolregression-v070): a gateway
    reply in anthropic content-block shape (tool_use block, stop_reason
    "tool_use") crashed translate_response with "upstream reply has no
    choices" — the tool call was silently dropped and Codex surfaced the
    failure as a reconnect loop. Anthropic shape is now decoded first.
    """
    if isinstance(upstream.get("content"), list) or upstream.get("stop_reason") is not None:
        text, calls, stop = _anthropic_output(upstream)
        usage = upstream.get("usage") if isinstance(upstream.get("usage"), dict) else {}
        return text, calls, stop, usage
    return _chat_completion_output(upstream)


def _usage_fields(usage: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize usage across shapes (prompt_tokens | input_tokens ...)."""
    result: Dict[str, Any] = {
        "input_tokens": usage.get(
            "input_tokens", usage.get("prompt_tokens", 0)
        ) or 0,
        "output_tokens": usage.get(
            "output_tokens", usage.get("completion_tokens", 0)
        ) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
    }
    # Anthropic excludes cache reads/writes from input_tokens; Responses
    # counts the full input and reports cache hits as a subset.
    cached = usage.get("cache_read_input_tokens", 0) or 0
    result["input_tokens"] += cached + (usage.get("cache_creation_input_tokens", 0) or 0)
    if "cache_read_input_tokens" in usage:
        result["input_tokens_details"] = {"cached_tokens": cached}
    if not result["total_tokens"]:
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def translate_response(upstream: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Map a gateway reply (anthropic or chat.completion shape) onto a
    Responses-API response."""
    text, calls, finish, usage = _extract_output(upstream)
    resp_id = "resp_" + hashlib.sha256(
        (str(upstream.get("id", "")) + str(_now_iso())).encode("utf-8")
    ).hexdigest()[:24]

    output: List[Dict[str, Any]] = []
    if text:
        output.append(
            {
                "id": "msg_" + resp_id[-20:],
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "annotations": [], "text": text}
                ],
            }
        )
    for call_index, call in enumerate(calls):
        name, payload, kind = _normalize_tool_call(
            str(call.get("name") or ""), call.get("arguments")
        )
        call_id = str(call.get("id") or f"call_{call_index}")
        item_id = hashlib.sha256(
            (str(call.get("id", "")) + str(resp_id)).encode("utf-8")
        ).hexdigest()[:16]
        if kind == "custom":
            output.append(
                {
                    "id": "ctc_" + item_id,
                    "type": "custom_tool_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": name,
                    "input": payload,
                }
            )
        else:
            output.append(
                {
                    "id": "fc_" + item_id,
                    "type": "function_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": name,
                    "arguments": payload,
                }
            )

    status = "completed" if finish in (
        "stop", "tool_calls", "end_turn", "tool_use", "stop_sequence"
    ) else "incomplete"
    return {
        "id": resp_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model,
        "output": output,
        "usage": _usage_fields(usage),
        "incomplete_details": (
            {"reason": finish} if status != "completed" and finish else None
        ),
    }


def _sse_event(event: str, data: Dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _terminal_event_name(status: str) -> str:
    if status == "failed":
        return "response.failed"
    if status == "incomplete":
        return "response.incomplete"
    return "response.completed"


def stream_response_events(
    response: Dict[str, Any],
    include_created: bool = True,
) -> List[bytes]:
    """Responses-API SSE frames. Terminal event follows response.status."""
    text = ""
    for item in response.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    text = text + str(block.get("text", ""))
    events: List[bytes] = []
    if include_created:
        created = {
            "type": "response.created",
            "response": {
                k: response[k]
                for k in ("id", "object", "created_at", "model", "status")
                if k in response
            },
        }
        events.append(_sse_event("response.created", created))
    for index, item in enumerate(response.get("output", [])):
        events.append(_sse_event("response.output_item.added", {
            "type": "response.output_item.added",
            "output_index": index,
            "item": item,
        }))
        if item.get("type") == "message" and text:
            events.append(_sse_event("response.output_text.delta", {
                "type": "response.output_text.delta",
                "output_index": index,
                "content_index": 0,
                "delta": text,
            }))
        events.append(_sse_event("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": index,
            "item": item,
        }))
    terminal = _terminal_event_name(str(response.get("status") or "completed"))
    events.append(_sse_event(terminal, {
        "type": terminal,
        "response": response,
    }))
    return events


def _sse_data_payload(parts: List[str]) -> Any:
    blob = "\n".join(parts).strip()
    if not blob or blob == "[DONE]":
        return None
    try:
        return json.loads(blob)
    except ValueError:
        sys.stderr.write(
            "[ks-envelope] skip invalid SSE JSON (%s bytes) %r\n"
            % (len(blob), blob[:80])
        )
        sys.stderr.flush()
        return None


def _is_timeout_exc(exc: BaseException) -> bool:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    msg = str(exc).lower()
    if "timed out" in msg or "timeout" in msg:
        return True
    if isinstance(exc, OSError) and exc.errno in (
        errno.ETIMEDOUT,
        errno.EAGAIN,
        errno.EWOULDBLOCK,
    ):
        return True
    return False


def _readline_sse(fp: Any) -> Tuple[Optional[bytes], bool]:
    """Read one SSE line. Returns (bytes|None, eof).

    None + not-eof means an idle timeout. Do not lower the SSL socket
    timeout to implement heartbeats: that raises ssl.SSLError/OSError on
    this host and was logged as stream fail OSError (thread 01a096a2).
    Heartbeats come from _SseKeepalive + _LiveResponse.heartbeat instead.
    """
    try:
        raw = fp.readline()
    except (socket.timeout, TimeoutError) as exc:
        if _is_timeout_exc(exc):
            return None, False
        raise
    except ssl.SSLError as exc:
        if _is_timeout_exc(exc):
            return None, False
        raise
    except OSError as exc:
        if _is_timeout_exc(exc):
            return None, False
        raise
    except http.client.IncompleteRead as exc:
        raw = exc.partial or b""
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return raw or b"", True
    except (BrokenPipeError, ConnectionResetError):
        raise
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not raw:
        return b"", True
    return raw, False


def iter_sse_events(fp: Any) -> Iterator[Tuple[Optional[str], Any]]:
    """Yield (event_name, data) from an Anthropic-style SSE byte/text stream."""
    event_name: Optional[str] = None
    data_parts: List[str] = []
    while True:
        raw, eof = _readline_sse(fp)
        if raw is None and not eof:
            yield "ping", {"type": "ping"}
            continue
        if raw:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if data_parts:
                    payload = _sse_data_payload(data_parts)
                    if payload is not None:
                        yield event_name, payload
                event_name = None
                data_parts = []
            elif line.startswith(":"):
                pass
            elif line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_parts.append(line[5:].lstrip())
        if eof:
            if data_parts:
                payload = _sse_data_payload(data_parts)
                if payload is not None:
                    yield event_name, payload
            return


def iter_anthropic_stream_as_responses(
    fp: Any,
    model: str,
    live: Optional[_LiveResponse] = None,
    emit_created: bool = True,
) -> Iterator[bytes]:
    """Translate an Anthropic /messages SSE stream into Responses SSE frames."""
    if live is None:
        live = _LiveResponse(model)
    if emit_created:
        yield live.created_frame()
    try:
        yield from _forward_anthropic_stream(fp, live)
    except (OSError, http.client.HTTPException, EnvelopeError) as exc:
        # Headers are already sent. Never append another HTTP response or
        # expose upstream exception text (which may contain credentials).
        sys.stderr.write(
            "[ks-envelope] stream fail %s errno=%s %s\n"
            % (
                type(exc).__name__,
                getattr(exc, "errno", ""),
                str(exc)[:80].replace("\n", " "),
            )
        )
        sys.stderr.flush()
        yield from live.fail("upstream stream interrupted or invalid")


def _forward_anthropic_stream(fp: Any, live: _LiveResponse) -> Iterator[bytes]:
    for _name, payload in iter_sse_events(fp):
        if not isinstance(payload, dict):
            continue
        etype = str(payload.get("type") or _name or "")
        if etype == "error":
            yield from live.fail("upstream stream error")
            return
        if etype == "content_block_start":
            yield from live.block_start(payload)
        elif etype == "content_block_delta":
            yield from live.block_delta(payload)
        elif etype == "content_block_stop":
            yield from live.block_stop(payload)
        elif etype == "message_delta":
            live.message_delta(payload)
        elif etype == "message_start":
            message = payload.get("message")
            if isinstance(message, dict) and isinstance(message.get("usage"), dict):
                live.usage.update(message["usage"])
        elif etype == "ping":
            yield from live.heartbeat()
        elif etype == "message_stop":
            yield from live.finish()
            return
    if live.text and not live.tools:
        live.stop_reason = live.stop_reason or "end_turn"
        yield from live.finish()
        return
    yield from live.fail("upstream stream ended before message_stop")


class _LiveResponse:
    """Assemble Responses SSE while an Anthropic stream is in flight."""

    def __init__(self, model: str) -> None:
        self.model = model or ""
        self.resp_id = "resp_" + uuid.uuid4().hex[:24]
        self.created_at = int(time.time())
        self.output: List[Dict[str, Any]] = []
        self.stop_reason = ""
        self.usage: Dict[str, Any] = {}
        self.next_index = 0
        self.text_index: Optional[int] = None
        self.text_block_index: Optional[int] = None
        self.text_closed = False
        self.text = ""
        self.text_id = "msg_" + self.resp_id[-20:]
        self.tools: Dict[int, Dict[str, Any]] = {}
        self.reasoning_index: Optional[int] = None
        self.reasoning_closed = False
        self.reasoning_text = ""
        self.reasoning_id = "rs_" + self.resp_id[-20:]
        self._lock = threading.RLock()

    def created_frame(self) -> bytes:
        body = {
            "id": self.resp_id,
            "object": "response",
            "created_at": self.created_at,
            "model": self.model,
            "status": "in_progress",
        }
        return _sse_event(
            "response.created", {"type": "response.created", "response": body}
        )

    def keepalive_frame(self) -> bytes:
        body = {
            "id": self.resp_id,
            "object": "response",
            "created_at": self.created_at,
            "model": self.model,
            "status": "in_progress",
        }
        return _sse_event(
            "response.in_progress",
            {"type": "response.in_progress", "response": body},
        )

    def heartbeat(self) -> Iterator[bytes]:
        """Keep Codex from idle-reconnecting while LGW is silently thinking.

        Desktop first-token timeout is ~15s. LGW often emits no SSE bytes
        during gpt-5.6-sol high-effort thinking, then dumps thinking_delta.
        ``response.in_progress`` comments are not first tokens; a reasoning
        summary delta is. Emitted from the keepalive thread so we never
        lower the HTTPS socket timeout.
        """
        with self._lock:
            yield self.keepalive_frame()
            yield from self._ensure_reasoning_item()
            assert self.reasoning_index is not None
            yield _sse_event("response.reasoning_summary_text.delta", {
                "type": "response.reasoning_summary_text.delta",
                "item_id": self.reasoning_id,
                "output_index": self.reasoning_index,
                "summary_index": 0,
                "delta": "\u200b",
            })

    def snapshot(self, status: str) -> Dict[str, Any]:
        incomplete = None
        if status != "completed" and self.stop_reason:
            incomplete = {"reason": self.stop_reason}
        out: Dict[str, Any] = {
            "id": self.resp_id,
            "object": "response",
            "created_at": self.created_at,
            "status": status,
            "model": self.model,
            "output": list(self.output),
            "usage": _usage_fields(self.usage),
            "incomplete_details": incomplete,
        }
        return out

    def _ensure_reasoning_item(self) -> Iterator[bytes]:
        with self._lock:
            if self.reasoning_index is not None:
                return
            self.reasoning_index = self.next_index
            self.next_index += 1
            item = {
                "id": self.reasoning_id,
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": ""}],
            }
            self.output.append(item)
            yield _sse_event("response.output_item.added", {
                "type": "response.output_item.added",
                "output_index": self.reasoning_index,
                "item": item,
            })

    def _close_reasoning_item(self) -> Iterator[bytes]:
        if self.reasoning_index is None or self.reasoning_closed:
            return
        item = self.output[self.reasoning_index]
        if item.get("summary"):
            item["summary"][0]["text"] = self.reasoning_text
        self.reasoning_closed = True
        yield _sse_event("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": self.reasoning_index,
            "item": item,
        })

    def _ensure_text_item(self) -> Iterator[bytes]:
        if self.text_index is not None:
            return
        self.text_index = self.next_index
        self.next_index += 1
        item = {
            "id": self.text_id,
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [{"type": "output_text", "annotations": [], "text": ""}],
        }
        self.output.append(item)
        yield _sse_event("response.output_item.added", {
            "type": "response.output_item.added",
            "output_index": self.text_index,
            "item": item,
        })

    def _close_text_item(self) -> Iterator[bytes]:
        if self.text_index is None or self.text_closed:
            return
        item = self.output[self.text_index]
        item["status"] = "completed"
        item["content"][0]["text"] = self.text
        self.text_closed = True
        yield _sse_event("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": self.text_index,
            "item": item,
        })

    def block_start(self, payload: Dict[str, Any]) -> List[bytes]:
        block = payload.get("content_block")
        if not isinstance(block, dict):
            return []
        index = payload.get("index")
        btype = block.get("type")
        if btype == "thinking":
            return list(self._ensure_reasoning_item())
        if btype == "text" and isinstance(index, int):
            frames: List[bytes] = []
            frames.extend(self._close_reasoning_item())
            if (
                self.text_index is not None
                and not self.text_closed
                and self.text_block_index is not None
                and index != self.text_block_index
            ):
                frames.extend(self._close_text_item())
                self.text_index = None
                self.text_closed = False
                self.text = ""
                self.text_id = "msg_" + uuid.uuid4().hex[:20]
            elif self.text_closed:
                self.text_index = None
                self.text_closed = False
                self.text = ""
                self.text_id = "msg_" + uuid.uuid4().hex[:20]
            self.text_block_index = index
            if block.get("text"):
                frames.extend(self.block_delta({"index": index, "delta": {
                    "type": "text_delta", "text": block["text"],
                }}))
            return frames
        elif btype == "tool_use" and isinstance(index, int):
            frames = list(self._close_reasoning_item())
            self.tools[index] = {
                "id": block.get("id"),
                "name": block.get("name") or "",
                "json": "",
                "input": block.get("input", {}),
            }
            return frames
        return []

    def block_delta(self, payload: Dict[str, Any]) -> Iterator[bytes]:
        delta = payload.get("delta")
        if not isinstance(delta, dict):
            return
        dtype = delta.get("type")
        index = payload.get("index")
        if dtype in ("thinking_delta", "reasoning_delta"):
            chunk = str(delta.get("thinking") or delta.get("text") or "")
            if not chunk:
                return
            yield from self._ensure_reasoning_item()
            self.reasoning_text += chunk
            assert self.reasoning_index is not None
            summary = self.output[self.reasoning_index].get("summary")
            if summary:
                summary[0]["text"] = self.reasoning_text
            yield _sse_event("response.reasoning_summary_text.delta", {
                "type": "response.reasoning_summary_text.delta",
                "item_id": self.reasoning_id,
                "output_index": self.reasoning_index,
                "summary_index": 0,
                "delta": chunk,
            })
            return
        if dtype == "signature_delta":
            return
        if dtype == "text_delta":
            chunk = str(delta.get("text") or "")
            if not chunk:
                return
            yield from self._close_reasoning_item()
            yield from self._ensure_text_item()
            self.text += chunk
            assert self.text_index is not None
            self.output[self.text_index]["content"][0]["text"] = self.text
            yield _sse_event("response.output_text.delta", {
                "type": "response.output_text.delta",
                "output_index": self.text_index,
                "content_index": 0,
                "delta": chunk,
            })
            return
        if dtype == "input_json_delta" and isinstance(index, int):
            acc = self.tools.get(index)
            if acc is not None:
                acc["json"] += str(delta.get("partial_json") or "")

    def block_stop(self, payload: Dict[str, Any]) -> Iterator[bytes]:
        index = payload.get("index")
        if index == self.text_block_index:
            # Keep the message in_progress until finish()/fail(). Codex
            # commits AgentMessage on output_item.done; emitting it before
            # the terminal event is what produced a second reply on reconnect.
            return
        if not isinstance(index, int) or index not in self.tools:
            return
        acc = self.tools.pop(index)
        raw_args: Any = acc.get("json") or ""
        if isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed: Any = json.loads(raw_args)
            except ValueError:
                raise EnvelopeError("invalid upstream tool JSON") from None
        else:
            parsed = acc["input"]
        name, payload_text, kind = _normalize_tool_call(
            str(acc.get("name") or ""), parsed
        )
        call_id = str(acc.get("id") or f"call_{self.next_index}")
        item_id = hashlib.sha256(
            (call_id + self.resp_id).encode("utf-8")
        ).hexdigest()[:16]
        out_index = self.next_index
        self.next_index += 1
        if kind == "custom":
            item = {
                "id": "ctc_" + item_id,
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": call_id,
                "name": name,
                "input": payload_text,
            }
        else:
            item = {
                "id": "fc_" + item_id,
                "type": "function_call",
                "status": "completed",
                "call_id": call_id,
                "name": name,
                "arguments": payload_text,
            }
        self.output.append(item)
        yield _sse_event("response.output_item.added", {
            "type": "response.output_item.added",
            "output_index": out_index,
            "item": item,
        })
        yield _sse_event("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": out_index,
            "item": item,
        })

    def message_delta(self, payload: Dict[str, Any]) -> None:
        delta = payload.get("delta")
        if isinstance(delta, dict) and delta.get("stop_reason"):
            self.stop_reason = str(delta["stop_reason"])
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self.usage.update(usage)

    def fail(self, message: str) -> Iterator[bytes]:
        visible = bool(self.text) or bool(self.reasoning_text) or any(
            item.get("type") in ("message", "reasoning") for item in self.output
        )
        yield from self._close_reasoning_item()
        yield from self._close_text_item()
        if visible:
            # Codex already committed the assistant item. A failed terminal
            # makes it retry and generate a second, different reply.
            if not self.stop_reason:
                self.stop_reason = "stream_interrupted"
            yield _sse_event("response.incomplete", {
                "type": "response.incomplete",
                "response": self.snapshot("incomplete"),
            })
            return
        snap = self.snapshot("failed")
        snap["error"] = {"code": "upstream_error", "message": message[:300]}
        yield _sse_event("response.failed", {
            "type": "response.failed",
            "response": snap,
        })

    def finish(self) -> Iterator[bytes]:
        if not self.stop_reason or self.tools:
            yield from self.fail("upstream stream ended without complete message metadata")
            return
        yield from self._close_reasoning_item()
        yield from self._close_text_item()
        status = "completed" if self.stop_reason in (
            "stop", "tool_calls", "end_turn", "tool_use", "stop_sequence"
        ) else "incomplete"
        terminal = _terminal_event_name(status)
        yield _sse_event(terminal, {
            "type": terminal,
            "response": self.snapshot(status),
        })


def translate_error_response(upstream_status: int, detail: str) -> Dict[str, Any]:
    """Upstream failure surfaced as a failed response object (Codex-visible)."""
    message = f"upstream {UPSTREAM_MESSAGES} returned {upstream_status}"
    extra = " ".join(str(detail or "").split())
    if extra:
        message = f"{message}: {extra[:180]}"
    return {
        "id": "resp_" + uuid.uuid4().hex[:24],
        "object": "response",
        "created_at": int(time.time()),
        "status": "failed",
        "model": "",
        "error": {
            "code": "upstream_error",
            "message": message,
        },
    }


# --- HTTP server ---------------------------------------------------------------

class EnvelopeHandler(BaseHTTPRequestHandler):
    server_version = "ks-envelope/1.0"
    protocol_version = "HTTP/1.1"

    # injected by serve()
    upstream_key: str = ""
    upstream_base: str = ""
    secret_for_redaction: str = ""
    verbose: bool = False
    thinking_passthrough: bool = False
    overlay_text: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802
        if self.verbose:
            self._log_error(fmt, *args)

    def _log_error(self, fmt: str, *args: Any) -> None:
        safe = _redact(fmt % args, self.secret_for_redaction)
        sys.stderr.write("[ks-envelope] " + safe + "\n")
        sys.stderr.flush()

    def _reject(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reply_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reply_sse(
        self, response: Dict[str, Any], capture: Any = None
    ) -> None:
        frames = stream_response_events(response)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for frame in frames:
            if capture is not None:
                capture.extend(frame)
            self.wfile.write(frame)
        self.wfile.flush()
        self.close_connection = True

    def _write_sse_frame(self, frame: bytes) -> None:
        self.wfile.write(frame)
        self.wfile.flush()

    def _start_sse_headers(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _replay_coalesced(self, slot: _CoalescedTurn) -> None:
        if slot.done.is_set() and not slot.frames:
            self._reject(
                502,
                {
                    "error": {
                        "code": "upstream_error",
                        "message": "coalesced leader produced no frames",
                    }
                },
            )
            return
        # Send headers immediately so Codex sees a live SSE socket instead of
        # waiting out the leader. Do not mute the leader socket: that is what
        # turned a 15s LGW think-gap into desktop 正在重新連線 5/5.
        self._start_sse_headers()
        gate = _SseKeepalive(self.wfile, capture=None)
        gate.start()
        offset = 0
        deadline = time.time() + UPSTREAM_TIMEOUT_SECONDS
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                chunk, offset, done = slot.frames.wait_more(
                    offset, min(1.0, remaining)
                )
                if chunk and not gate.emit(chunk, capture=False):
                    return
                if done and offset >= len(slot.frames):
                    return
        finally:
            gate.stop()
            self.close_connection = True

    def _pipe_upstream_stream(
        self,
        resp: Any,
        model: str,
        gate: _SseKeepalive,
        live: Optional[_LiveResponse] = None,
    ) -> None:
        try:
            for frame in iter_anthropic_stream_as_responses(
                resp, model, live=live, emit_created=live is None
            ):
                # Client disconnect still captures frames so a reconnect
                # POST can replay this generation instead of calling LGW again.
                gate.emit(frame)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _emit_ready_frames(
        self, response: Dict[str, Any], gate: _SseKeepalive
    ) -> None:
        for frame in stream_response_events(response):
            if not gate.emit(frame):
                break

    def _reply_upstream_stream(
        self,
        resp: Any,
        model: str,
        capture: Any = None,
    ) -> None:
        self._start_sse_headers()
        gate = _SseKeepalive(self.wfile, capture=capture)
        gate.start()
        try:
            self._pipe_upstream_stream(resp, model, gate)
        finally:
            gate.stop()
            self.close_connection = True

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("", "/health", LOCAL_PREFIX + "/health"):
            self._reply_json(
                200, {"ok": True, "envelope": "openai-responses-to-anthropic-messages"}
            )
            return
        self._reject(404, {"error": {"code": "not_found", "message": self.path}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != LOCAL_PREFIX + "/responses":
            self._reject(404, {"error": {"code": "not_found", "message": self.path}})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._reject(400, {"error": {"code": "bad_length"}})
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._reject(400, {"error": {"code": "bad_length", "length": length}})
            return
        raw = self.rfile.read(length)
        try:
            request_body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._reject(400, {"error": {"code": "bad_json", "message": str(exc)[:200]}})
            return
        if not isinstance(request_body, dict):
            self._reject(400, {"error": {"code": "bad_json", "message": "request is not an object"}})
            return

        wants_stream = request_body.get("stream") is True
        slot: Optional[_CoalescedTurn] = None
        leader = False
        if wants_stream:
            slot, leader = _coalesce_begin(_request_fingerprint(request_body))
            if not leader:
                self._replay_coalesced(slot)
                return
        capture = slot.frames if slot is not None else None

        try:
            translated = translate_request(
                request_body,
                thinking_passthrough=self.thinking_passthrough,
                overlay_text=self.overlay_text,
            )
        except EnvelopeError as exc:
            if leader and slot is not None:
                _coalesce_finish(slot, error=exc)
            self._reject(400, {"error": {"code": "bad_request", "message": str(exc)[:300]}})
            return

        if wants_stream:
            translated["stream"] = True
        payload = json.dumps(translated, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.upstream_base + UPSTREAM_MESSAGES,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.upstream_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        model = str(request_body.get("model") or "")
        gate: Optional[_SseKeepalive] = None
        live_stream: Optional[_LiveResponse] = None
        if wants_stream:
            live_stream = _LiveResponse(model)
            self._start_sse_headers()
            gate = _SseKeepalive(self.wfile, capture=capture, live=live_stream)
            gate.start()
            gate.emit(live_stream.created_frame())
        try:
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(
                        req, timeout=UPSTREAM_TIMEOUT_SECONDS
                    ) as resp:
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if wants_stream:
                            assert gate is not None
                            if "text/event-stream" in ctype:
                                self._pipe_upstream_stream(
                                    resp, model, gate, live=live_stream
                                )
                            else:
                                data = json.loads(resp.read().decode("utf-8"))
                                self._emit_ready_frames(
                                    translate_response(data, model), gate
                                )
                        else:
                            data = json.loads(resp.read().decode("utf-8"))
                            self._reply_json(200, translate_response(data, model))
                    break
                except urllib.error.HTTPError as exc:
                    try:
                        detail = exc.read().decode("utf-8", errors="replace")[:500]
                    except Exception:
                        detail = str(exc)
                    self._log_error(
                        "upstream %s: %s",
                        exc.code,
                        _redact(detail, self.secret_for_redaction),
                    )
                    error_out = translate_error_response(exc.code, detail)
                    if wants_stream:
                        assert gate is not None
                        self._emit_ready_frames(error_out, gate)
                    else:
                        self._reply_json(200, error_out)
                    break
                except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                    reason = str(getattr(exc, "reason", exc))[:200]
                    self._log_error(
                        "upstream urlerror attempt %s: %s",
                        attempt + 1,
                        _redact(reason, self.secret_for_redaction),
                    )
                    if attempt == 0:
                        continue
                    error_out = translate_error_response(0, reason)
                    if wants_stream:
                        assert gate is not None
                        self._emit_ready_frames(error_out, gate)
                    else:
                        self._reply_json(200, error_out)
        except EnvelopeError as exc:
            if wants_stream:
                assert gate is not None
                self._emit_ready_frames(
                    translate_error_response(0, str(exc)[:300]), gate
                )
            else:
                self._reject(502, {"error": {"code": "bad_upstream", "message": str(exc)[:300]}})
        except Exception as exc:  # pragma: no cover - defensive
            self._log_error("internal: %s", _redact(str(exc), self.secret_for_redaction))
            if wants_stream:
                assert gate is not None
                self._emit_ready_frames(
                    translate_error_response(0, "adapter failure"), gate
                )
            else:
                self._reject(500, {"error": {"code": "internal", "message": "adapter failure"}})
        finally:
            if gate is not None:
                gate.stop()
                self.close_connection = True
            if leader and slot is not None and not slot.done.is_set():
                _coalesce_finish(slot)


def serve(
    port: int,
    upstream_base: str,
    auth_file: Path,
    verbose: bool,
    thinking_passthrough: bool = False,
    overlay_file: Optional[Path] = None,
) -> None:
    key = load_upstream_key(auth_file)
    overlay_text = ""
    if overlay_file is not None:
        try:
            overlay_text = overlay_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise EnvelopeError(f"overlay file unreadable: {overlay_file}: {exc}") from exc
        if not overlay_text.strip():
            raise EnvelopeError(f"overlay file is empty: {overlay_file}")
    handler = type(
        "BoundEnvelopeHandler",
        (EnvelopeHandler,),
        {
            "upstream_key": key,
            "upstream_base": upstream_base.rstrip("/"),
            "secret_for_redaction": key,
            "verbose": verbose,
            "thinking_passthrough": thinking_passthrough,
            "overlay_text": overlay_text,
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    print(
        f"[ks-envelope] listening on http://127.0.0.1:{port}{LOCAL_PREFIX}/responses"
        f" -> {upstream_base.rstrip('/')}{UPSTREAM_MESSAGES}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="OpenAI-Responses-to-Anthropic-shape local adapter for keysmith"
    )
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument(
        "--upstream",
        default=os.environ.get("KS_UPSTREAM", DEFAULT_UPSTREAM),
        help="gateway base URL ending in /v1 (default: lgw.gru.ai)",
    )
    parser.add_argument(
        "--auth-file",
        default=os.environ.get(
            "CODEX_KEYSMITH_AUTH", str(DEFAULT_AUTH_PATH)
        ),
        help="JSON file holding OPENAI_API_KEY (default ~/.codex/auth.json)",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--thinking-passthrough",
        action="store_true",
        help=(
            "map codex reasoning.effort onto the anthropic thinking block "
            "(experimental; measured to hang the lgw.gru.ai messages arm "
            "intermittently, so it is off by default)"
        ),
    )
    parser.add_argument(
        "--overlay-file",
        default=os.environ.get("KS_OVERLAY_FILE"),
        help=(
            "Markdown contract appended AFTER the stock instructions in the "
            "upstream system parameter (never replaces the base prompt); "
            "e.g. examples/gpt-overlay.md"
        ),
    )
    args = parser.parse_args(argv)

    if not (0 < args.port < 65536):
        parser.error("--port must be within 1-65535")
    upstream = args.upstream.strip()
    if not upstream.startswith(("http://", "https://")):
        parser.error("--upstream must start with http:// or https://")

    overlay_path: Optional[Path] = None
    if args.overlay_file:
        overlay_path = Path(args.overlay_file).expanduser()

    try:
        serve(
            args.port,
            upstream,
            Path(args.auth_file).expanduser(),
            args.verbose,
            thinking_passthrough=args.thinking_passthrough,
            overlay_file=overlay_path,
        )
    except EnvelopeError as exc:
        print(f"[ks-envelope] error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
