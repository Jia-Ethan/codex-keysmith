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
import hashlib
import json
import os
import sys
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

_FUNCTIONS_WRAPPER_NAMES = {"functions", "function", "tools"}
_EXEC_NESTED_METHODS = {"exec_command", "apply_patch", "write_stdin"}
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
    if isinstance(parsed, dict) and set(parsed.keys()) == {"input"}:
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
                # other block types (reasoning traces, tool calls) carry no
                # prose for the delivery arm; skip rather than reject.
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    raise EnvelopeError("input item content is not text")


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
    {id, name, arguments} where arguments is a JSON string (matching
    _upstream_tool_calls' output contract). The anthropic reply shape is
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
            arguments = _unwrap_tool_input(block.get("input"))
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


def _usage_fields(usage: Dict[str, Any]) -> Dict[str, int]:
    """Normalize usage across shapes (prompt_tokens | input_tokens ...)."""
    return {
        "input_tokens": usage.get(
            "input_tokens", usage.get("prompt_tokens", 0)
        ) or 0,
        "output_tokens": usage.get(
            "output_tokens", usage.get("completion_tokens", 0)
        ) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
    }


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

    return {
        "id": resp_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed" if finish in (
            "stop", "tool_calls", "end_turn", "tool_use"
        ) else "incomplete",
        "model": model,
        "output": output,
        "usage": _usage_fields(usage),
        "incomplete_details": (
            {"reason": finish} if finish and finish not in ("stop", "end_turn") else None
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
        "response": {k: response[k] for k in ("id", "object", "created_at", "model", "status") if k in response},
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
        "model": "",
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
    thinking_passthrough: bool = False
    overlay_text: str = ""

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
            translated = translate_request(
                request_body,
                thinking_passthrough=self.thinking_passthrough,
                overlay_text=self.overlay_text,
            )
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
