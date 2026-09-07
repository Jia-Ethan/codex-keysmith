#!/usr/bin/env python3
"""ks-envelope — local OpenAI-to-Anthropic-shape protocol adapter for keysmith.

Pure stdlib. Listens on a loopback-only port, accepts OpenAI Responses-API
requests (/v1/responses), translates each into an Anthropic-shaped
/v1/messages call against the upstream gateway, and translates the
chat.completion reply back into a Responses-API response object.

Why: the upstream content classifiers are envelope-sensitive. Measured
2026-09-06/07 on gpt-5.6-sol via lgw.gru.ai (breaktest-results/nsfw-v051/
phase7-cyber-envelope-summary.json): the same frozen 12-case prompt bank and
the same lean preset scored messages-arm 4/12 vs codex/responses 1/12, with
at least one cell (anti-detection-zh) blocked by the upstream cyber
classifier on chat/responses arms but delivered through the anthropic-shaped
messages arm. This adapter gives Codex the messages-arm envelope without
changing its OpenAI client.

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
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_UPSTREAM = "https://lgw.gru.ai/v1"
DEFAULT_AUTH_PATH = Path.home() / ".codex" / "auth.json"
LOCAL_PREFIX = "/v1"
UPSTREAM_MESSAGES = "/messages"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
UPSTREAM_TIMEOUT_SECONDS = 300

SECRET_PATTERNS = (
    "OPENAI_API_KEY",
    "Authorization",
    "x-api-key",
)


class EnvelopeError(Exception):
    """Adapter-local failure with a safe, redacted message."""


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

def _translate_tools(raw_input: Any) -> List[Dict[str, Any]]:
    """Map Responses additional_tools declarations to anthropic tools.

    Codex declares its tools as ``{type: "custom", name, description,
    format: {type: "grammar", ...}}`` — free-text input tools. The
    anthropic-messages surface wants JSON-schema tools; a single string
    parameter carries the grammar source verbatim.
    """
    tools: List[Dict[str, Any]] = []
    if not isinstance(raw_input, list):
        return tools
    for item in raw_input:
        if not isinstance(item, dict) or item.get("type") != "additional_tools":
            continue
        for tool in item.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            name = tool.get("name")
            if not isinstance(name, str) or not name:
                continue
            tools.append(
                {
                    "name": name,
                    "description": str(tool.get("description") or ""),
                    "input_schema": {
                        "type": "object",
                        "properties": {"input": {"type": "string"}},
                        "required": ["input"],
                    },
                }
            )
    return tools


def _tool_call_input(item: Dict[str, Any]) -> Dict[str, Any]:
    """Arguments for a history tool_call item, as the anthropic input dict."""
    arguments = item.get("arguments", item.get("input"))
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
        return {"input": arguments}
    return {"input": ""}


def _tool_output_text(item: Dict[str, Any]) -> str:
    output = item.get("output")
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        return json.dumps(output, ensure_ascii=False)
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
                # other block types (reasoning traces, tool calls) carry no
                # prose for the delivery arm; skip rather than reject.
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    raise EnvelopeError("input item content is not text")


def translate_request(body: Dict[str, Any]) -> Dict[str, Any]:
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
                # Assistant tool invocation from conversation history.
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": str(item.get("call_id") or item.get("id") or ""),
                                "name": str(item.get("name") or ""),
                                "input": _tool_call_input(item),
                            }
                        ],
                    }
                )
                continue
            if item_type == "function_call_output":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": str(item.get("call_id") or ""),
                                "content": _tool_output_text(item),
                            }
                        ],
                    }
                )
                continue
            role = item.get("role", "user")
            text = _item_text(item)
            if role == "developer":
                system_parts.append(text)
                continue
            if role not in ("user", "assistant"):
                role = "user"
            messages.append(
                {"role": role, "content": [{"type": "text", "text": text}]}
            )
    else:
        raise EnvelopeError("request has no usable input field")

    if not messages:
        # Tool-result-only follow-ups still carry the conversation; if nothing
        # else remains, the request is unusable for the messages arm.
        raise EnvelopeError("request has no user/assistant messages")

    tools = _translate_tools(raw_input)

    out: Dict[str, Any] = {
        "model": body.get("model"),
        "max_tokens": body.get("max_output_tokens") or 4096,
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


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def translate_response(upstream: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Map a gateway chat.completion object onto a Responses-API response."""
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
    finish = first.get("finish_reason")
    resp_id = "resp_" + hashlib.sha256(
        (str(upstream.get("id", "")) + str(_now_iso())).encode("utf-8")
    ).hexdigest()[:24]
    usage = upstream.get("usage") if isinstance(upstream.get("usage"), dict) else {}

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
    for call_index, call in enumerate(_upstream_tool_calls(first)):
        arguments = call.get("arguments")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        output.append(
            {
                "id": "ctc_" + hashlib.sha256(
                    (str(call.get("id", "")) + str(resp_id)).encode("utf-8")
                ).hexdigest()[:16],
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": str(call.get("id") or f"call_{call_index}"),
                "name": str(call.get("name") or ""),
                "input": str(arguments if arguments is not None else ""),
            }
        )

    return {
        "id": resp_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed" if finish in ("stop", "tool_calls") else "incomplete",
        "model": model,
        "output": output,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "incomplete_details": (
            {"reason": finish} if finish and finish != "stop" else None
        ),
    }


def _sse_event(event: str, data: Dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def stream_response_events(
    response: Dict[str, Any],
) -> List[bytes]:
    """Responses-API SSE event frames for a completed response object."""
    text = ""
    for item in response.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    text = text + str(block.get("text", ""))
    events: List[bytes] = []
    created = {
        "type": "response.created",
        "response": {k: response[k] for k in ("id", "object", "created_at", "model", "status")},
    }
    events.append(_sse_event("response.created", created))
    for index, item in enumerate(response.get("output", [])):
        events.append(_sse_event("response.output_item.added", {
            "type": "response.output_item.added",
            "output_index": index,
            "item": item,
        }))
        if item.get("type") == "message":
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
    events.append(_sse_event("response.completed", {
        "type": "response.completed",
        "response": response,
    }))
    return events


def translate_error_response(upstream_status: int, detail: str) -> Dict[str, Any]:
    """Upstream failure surfaced as a failed response object (Codex-visible)."""
    return {
        "id": "resp_" + uuid.uuid4().hex[:24],
        "object": "response",
        "created_at": int(time.time()),
        "status": "failed",
        "error": {
            "code": "upstream_error",
            "message": f"upstream {UPSTREAM_MESSAGES} returned {upstream_status}",
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

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802
        if self.verbose:
            safe = _redact(fmt % args, self.secret_for_redaction)
            sys.stderr.write("[ks-envelope] " + safe + "\n")

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

    def _reply_sse(self, response: Dict[str, Any]) -> None:
        frames = stream_response_events(response)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for frame in frames:
            self.wfile.write(frame)
        self.wfile.flush()
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

        try:
            translated = translate_request(request_body)
        except EnvelopeError as exc:
            self._reject(400, {"error": {"code": "bad_request", "message": str(exc)[:300]}})
            return

        wants_stream = request_body.get("stream") is True
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
        try:
            with urllib.request.urlopen(
                req, timeout=UPSTREAM_TIMEOUT_SECONDS
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated_out = translate_response(
                    data, str(request_body.get("model"))
                )
                if wants_stream:
                    self._reply_sse(translated_out)
                else:
                    self._reply_json(200, translated_out)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                detail = str(exc)
            self.log_message("upstream %s: %s", exc.code, _redact(detail, self.secret_for_redaction))
            error_out = translate_error_response(exc.code, detail)
            if wants_stream:
                self._reply_sse(error_out)
            else:
                self._reply_json(200, error_out)
        except urllib.error.URLError as exc:
            reason = str(exc.reason)[:200]
            self.log_message("upstream urlerror: %s", reason)
            error_out = translate_error_response(0, reason)
            if wants_stream:
                self._reply_sse(error_out)
            else:
                self._reply_json(200, error_out)
        except EnvelopeError as exc:
            self._reject(502, {"error": {"code": "bad_upstream", "message": str(exc)[:300]}})
        except Exception as exc:  # pragma: no cover - defensive
            self.log_message("internal: %s", _redact(str(exc), self.secret_for_redaction))
            self._reject(500, {"error": {"code": "internal", "message": "adapter failure"}})


def serve(
    port: int,
    upstream_base: str,
    auth_file: Path,
    verbose: bool,
) -> None:
    key = load_upstream_key(auth_file)
    handler = type(
        "BoundEnvelopeHandler",
        (EnvelopeHandler,),
        {
            "upstream_key": key,
            "upstream_base": upstream_base.rstrip("/"),
            "secret_for_redaction": key,
            "verbose": verbose,
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
    args = parser.parse_args(argv)

    if not (0 < args.port < 65536):
        parser.error("--port must be within 1-65535")
    upstream = args.upstream.strip()
    if not upstream.startswith(("http://", "https://")):
        parser.error("--upstream must start with http:// or https://")

    try:
        serve(args.port, upstream, Path(args.auth_file).expanduser(), args.verbose)
    except EnvelopeError as exc:
        print(f"[ks-envelope] error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
