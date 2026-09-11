#!/usr/bin/env python3
"""Tests for ks-envelope tool-call round-trip fidelity.

Phase 0 evidence (2026-09-08, breaktest-results/toolregression-v070):
two return-path gaps made Codex unable to use tools through the adapter:

1. Upstream replies in anthropic content-block shape (``content`` list with
   ``tool_use`` blocks, ``stop_reason: "tool_use"``) crashed translate_response
   with "upstream reply has no choices" — the tool call was dropped and Codex
   reconnected in a loop.
2. Codex 0.144.6 sends tool results as ``custom_tool_call_output`` items (not
   ``function_call_output``) whose ``output`` is a list of ``input_text``
   blocks; the adapter dropped them into an empty user message, so the model
   never saw tool results and the turn never converged.

These tests pin both wire shapes plus the full round-trip through a mock
upstream, using the same in-process harness pattern as test_ks_envelope.py.
"""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

KS_ENVELOPE_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "ks-envelope.py"
)

spec = importlib.util.spec_from_file_location("ks_envelope", KS_ENVELOPE_PATH)
ks_envelope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ks_envelope)


# ---------------------------------------------------------------------------
# Unit: anthropic content-block reply decoding
# ---------------------------------------------------------------------------

def test_anthropic_tool_use_reply_decodes_to_custom_tool_call():
    reply = {
        "id": "msg_m1",
        "content": [
            {"type": "text", "text": "Running the probe now."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "exec",
                "input": {"input": "ls -la"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }
    out = ks_envelope.translate_response(reply, "gpt-5.6-sol")
    assert out["status"] == "completed"
    kinds = [item["type"] for item in out["output"]]
    assert kinds == ["message", "custom_tool_call"]
    call = out["output"][1]
    assert call["call_id"] == "toolu_1"
    assert call["name"] == "exec"
    # {"input": ...} envelope is unwrapped to the raw grammar source string.
    assert call["input"] == "ls -la"


def test_anthropic_tool_use_plain_string_input_passthrough():
    reply = {
        "id": "msg_m1",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_2",
                "name": "exec",
                "input": "await tools.exec_command({cmd: 'ls'})",
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    out = ks_envelope.translate_response(reply, "m")
    call = out["output"][0]
    assert call["type"] == "custom_tool_call"
    assert call["input"] == "await tools.exec_command({cmd: 'ls'})"


def test_anthropic_end_turn_text_reply():
    reply = {
        "id": "msg_m2",
        "content": [{"type": "text", "text": "done"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }
    out = ks_envelope.translate_response(reply, "m")
    assert out["status"] == "completed"
    assert out["output"][0]["content"][0]["text"] == "done"
    assert out["incomplete_details"] is None


def test_anthropic_usage_fields_normalized():
    reply = {
        "content": [{"type": "text", "text": "x"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 7, "output_tokens": 4},
    }
    out = ks_envelope.translate_response(reply, "m")
    assert out["usage"]["input_tokens"] == 7
    assert out["usage"]["output_tokens"] == 4


def test_chat_completion_shape_still_decodes():
    reply = {
        "id": "cmpl_1",
        "choices": [
            {
                "message": {
                    "content": "hi",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "exec", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    out = ks_envelope.translate_response(reply, "m")
    assert out["status"] == "completed"
    kinds = [item["type"] for item in out["output"]]
    assert kinds == ["message", "custom_tool_call"]
    assert out["usage"]["input_tokens"] == 1


def test_functions_wrapper_rewrites_to_exec_custom_tool():
    # Live desktop 2026-09-11: Codex rejected name=functions with
    # "unsupported custom tool call: functions".
    reply = {
        "content": [
            {
                "type": "tool_use",
                "id": "call_vngiTW4aWR7sY4Hm8ZEBZLxd",
                "name": "functions",
                "input": {
                    "tool": "exec_command",
                    "arguments": {"cmd": "pwd"},
                },
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    out = ks_envelope.translate_response(reply, "gpt-6-astra")
    call = out["output"][0]
    assert call["type"] == "custom_tool_call"
    assert call["name"] == "exec"
    assert call["call_id"] == "call_vngiTW4aWR7sY4Hm8ZEBZLxd"
    assert "exec_command" in call["input"]
    assert "pwd" in call["input"]
    assert call["input"].startswith("text(await tools.exec_command(")


def test_exec_command_nested_name_rewrites_to_exec():
    reply = {
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_x",
                "name": "exec_command",
                "input": {"cmd": "ls /tmp", "max_output_tokens": 1000},
            }
        ],
        "stop_reason": "tool_use",
    }
    call = ks_envelope.translate_response(reply, "m")["output"][0]
    assert call["type"] == "custom_tool_call"
    assert call["name"] == "exec"
    assert "ls /tmp" in call["input"]


def test_wait_function_tool_emits_function_call_not_custom():
    reply = {
        "content": [
            {
                "type": "tool_use",
                "id": "call_wait",
                "name": "wait",
                "input": {"cell_id": "exec-1", "yield_time_ms": 10000},
            }
        ],
        "stop_reason": "tool_use",
    }
    call = ks_envelope.translate_response(reply, "m")["output"][0]
    assert call["type"] == "function_call"
    assert call["name"] == "wait"
    args = json.loads(call["arguments"])
    assert args["cell_id"] == "exec-1"


def test_max_tokens_default_raised_for_tool_turns():
    body = {"model": "m", "input": [{"role": "user", "content": "hi"}]}
    out = ks_envelope.translate_request(body)
    assert out["max_tokens"] >= 16384


# ---------------------------------------------------------------------------
# Unit: custom_tool_call_output history translation
# ---------------------------------------------------------------------------

def _codex_round2_request():
    return {
        "model": "gpt-5.6-sol",
        "instructions": "base",
        "input": [
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "list files"}]},
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "Checking files."}]},
            {"type": "custom_tool_call", "status": "completed",
             "call_id": "toolu_1", "name": "exec",
             "input": "{\"input\": \"sed -n 1p items.txt\"}"},
            {"type": "custom_tool_call_output", "call_id": "toolu_1",
             "output": [
                 {"type": "input_text", "text": "alpha 1"},
                 {"type": "input_text", "text": "beta 2"},
             ]},
        ],
    }


def test_custom_tool_call_output_becomes_tool_result():
    out = ks_envelope.translate_request(_codex_round2_request())
    msgs = out["messages"]
    # Last message must be a user tool_result carrying both text blocks.
    last = msgs[-1]
    assert last["role"] == "user"
    blocks = last["content"]
    assert blocks[0]["type"] == "tool_result"
    assert blocks[0]["tool_use_id"] == "toolu_1"
    assert "alpha 1" in blocks[0]["content"]
    assert "beta 2" in blocks[0]["content"]
    # No empty-text user message may leak in (the old drop-through bug).
    for m in msgs:
        for b in m["content"]:
            assert not (b.get("type") == "text" and b.get("text") == "")


def test_custom_tool_call_output_string_output():
    body = {
        "model": "m",
        "input": [
            {"type": "custom_tool_call_output", "call_id": "c1", "output": "raw text"},
        ],
    }
    out = ks_envelope.translate_request(body)
    block = out["messages"][0]["content"][0]
    assert block["type"] == "tool_result"
    assert block["content"] == "raw text"


def test_custom_tool_call_history_maps_to_tool_use():
    out = ks_envelope.translate_request(_codex_round2_request())
    tool_use_msgs = [
        m for m in out["messages"]
        if isinstance(m.get("content"), list)
        and m["content"][0].get("type") == "tool_use"
    ]
    assert tool_use_msgs, "custom_tool_call history must map to tool_use"
    assert tool_use_msgs[0]["content"][0]["name"] == "exec"


# ---------------------------------------------------------------------------
# E2E: full round-trip through the adapter against a mock anthropic upstream
# ---------------------------------------------------------------------------

class _ToolMockUpstream(BaseHTTPRequestHandler):
    """First call: anthropic tool_use. After tool_result: plain text."""

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        msgs = body.get("messages", [])
        has_result = any(
            isinstance(m.get("content"), list)
            and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in m["content"]
            )
            for m in msgs
        )
        if has_result:
            reply = {
                "id": "msg_m2",
                "content": [{"type": "text", "text": "The first line is: alpha 1"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 9, "output_tokens": 7},
            }
        else:
            tool_name = "exec"
            if isinstance(body.get("tools"), list) and body["tools"]:
                tool_name = body["tools"][0].get("name") or tool_name
            reply = {
                "id": "msg_m1",
                "content": [
                    {"type": "text", "text": "Checking files."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": tool_name,
                        "input": {"input": "sed -n 1p items.txt"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 9, "output_tokens": 11},
            }
        payload = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def _servers():
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _ToolMockUpstream)
    handler = type(
        "Bound",
        (ks_envelope.EnvelopeHandler,),
        {
            "upstream_base": f"http://127.0.0.1:{upstream.server_address[1]}",
            "upstream_key": "mock-key",
            "thinking_passthrough": False,
        },
    )
    envelope = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    threading.Thread(target=envelope.serve_forever, daemon=True).start()
    yield envelope
    envelope.shutdown()
    upstream.shutdown()


def _post(url, payload):
    import urllib.request

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode()
    if payload.get("stream") is True:
        # SSE replay: the completed event's data holds the full response.
        for chunk in raw.split("\n\n"):
            if chunk.startswith("event: response.completed"):
                data = json.loads(chunk.split("data: ", 1)[1])
                return data["response"]
        raise AssertionError(f"no response.completed frame in: {raw[:200]}")
    return json.loads(raw)


def test_e2e_codex_shaped_round_trip(_servers):
    port = _servers.server_address[1]
    # Turn 1: Codex-shaped request with additional_tools.
    turn1 = {
        "model": "gpt-5.6-sol",
        "instructions": "stock base prompt",
        "stream": True,
        "input": [
            {
                "type": "additional_tools",
                "tools": [
                    {
                        "type": "custom",
                        "name": "exec",
                        "description": "Run JavaScript",
                        "format": {"type": "grammar", "syntax": "lark",
                                   "definition": "start: SOURCE"},
                    }
                ],
            },
            {"type": "message", "role": "developer",
             "content": [{"type": "input_text", "text": "dev note"}]},
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "read items.txt"}]},
        ],
    }
    out1 = _post(f"http://127.0.0.1:{port}/v1/responses", turn1)
    kinds = [i["type"] for i in out1["output"]]
    assert kinds == ["message", "custom_tool_call"], kinds
    call = out1["output"][1]
    assert call["name"] == "exec"
    assert call["call_id"] == "toolu_1"

    # Turn 2: history with the tool call and Codex's custom_tool_call_output.
    turn2 = {
        "model": "gpt-5.6-sol",
        "instructions": "stock base prompt",
        "input": [
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "read items.txt"}]},
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "Checking files."}]},
            {"type": "custom_tool_call", "status": "completed",
             "call_id": "toolu_1", "name": "exec",
             "input": "{\"input\": \"sed -n 1p items.txt\"}"},
            {"type": "custom_tool_call_output", "call_id": "toolu_1",
             "output": [{"type": "input_text", "text": "alpha 1"}]},
        ],
    }
    out2 = _post(f"http://127.0.0.1:{port}/v1/responses", turn2)
    text = out2["output"][0]["content"][0]["text"]
    assert "alpha 1" in text
    assert out2["status"] == "completed"
