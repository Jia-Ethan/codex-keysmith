import importlib.util
import io
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENVELOPE_PATH = REPO_ROOT / "scripts" / "ks-envelope.py"

spec = importlib.util.spec_from_file_location("ks_envelope", ENVELOPE_PATH)
ks_envelope = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = ks_envelope
spec.loader.exec_module(ks_envelope)


# --- request translation -------------------------------------------------------


def test_translate_request_maps_instructions_to_system():
    body = {
        "model": "gpt-5.6-sol",
        "instructions": "be terse",
        "input": [{"role": "user", "content": "hello"}],
        "max_output_tokens": 128,
    }
    out = ks_envelope.translate_request(body)
    assert out["model"] == "gpt-5.6-sol"
    assert out["system"] == "be terse"
    assert out["max_tokens"] == 128
    assert out["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]}
    ]


def test_translate_request_content_block_list():
    body = {
        "model": "m",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "a"}, {"type": "input_text", "text": "b"}],
            }
        ],
    }
    out = ks_envelope.translate_request(body)
    assert out["messages"][0]["content"][0]["text"] == "a\nb"


def test_translate_request_assistant_role_preserved():
    body = {
        "model": "m",
        "input": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ],
    }
    out = ks_envelope.translate_request(body)
    assert [m["role"] for m in out["messages"]] == ["user", "assistant"]


def test_translate_request_codex_shape_developer_to_system():
    body = {
        "model": "gpt-5.6-sol",
        "stream": True,
        "input": [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [{"type": "custom", "name": "exec"}],
            },
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "CONTRACT"}],
            },
            {
                "type": "message",
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": "<permissions>"},
                    {"type": "input_text", "text": "<skills>"},
                ],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
        ],
    }
    out = ks_envelope.translate_request(body)
    assert out["system"] == "CONTRACT\n\n<permissions>\n<skills>"
    assert len(out["messages"]) == 1
    assert out["messages"][0]["role"] == "user"
    assert out["messages"][0]["content"][0]["text"] == "hello"


def test_translate_request_rejects_developer_only_input():
    body = {
        "model": "m",
        "input": [
            {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "x"}]}
        ],
    }
    with pytest.raises(ks_envelope.EnvelopeError):
        ks_envelope.translate_request(body)


def test_stream_response_events_order_and_delta():
    response = {
        "id": "resp_x",
        "object": "response",
        "created_at": 1,
        "model": "m",
        "status": "completed",
        "output": [
            {
                "id": "msg_x",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "annotations": [], "text": "pong"}],
            }
        ],
        "usage": {},
    }
    frames = ks_envelope.stream_response_events(response)
    joined = b"".join(frames).decode("utf-8")
    assert "event: response.created" in joined
    assert "event: response.output_text.delta" in joined
    assert '"delta": "pong"' in joined
    assert "event: response.completed" in joined
    assert (
        joined.index("response.created")
        < joined.index("response.output_text.delta")
        < joined.index("response.completed")
    )


def test_stream_response_events_failed_uses_failed_terminal():
    response = {
        "id": "resp_f",
        "object": "response",
        "created_at": 1,
        "model": "m",
        "status": "failed",
        "output": [],
        "error": {"code": "upstream_error", "message": "upstream 401"},
    }
    joined = b"".join(ks_envelope.stream_response_events(response)).decode("utf-8")
    assert "event: response.failed" in joined
    assert "event: response.completed" not in joined


def test_stream_response_events_incomplete_terminal():
    response = {
        "id": "resp_i",
        "object": "response",
        "created_at": 1,
        "model": "m",
        "status": "incomplete",
        "output": [],
        "incomplete_details": {"reason": "failed"},
    }
    joined = b"".join(ks_envelope.stream_response_events(response)).decode("utf-8")
    assert "event: response.incomplete" in joined
    assert "event: response.completed" not in joined


def test_anthropic_stream_emits_text_deltas_before_completed():
    raw = (
        "event: message_start\n"
        "data: {\"type\":\"message_start\",\"message\":{\"id\":\"msg_s\"}}\n"
        "\n"
        "event: content_block_start\n"
        "data: {\"type\":\"content_block_start\",\"index\":0,"
        "\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n"
        "\n"
        "event: content_block_delta\n"
        "data: {\"type\":\"content_block_delta\",\"index\":0,"
        "\"delta\":{\"type\":\"text_delta\",\"text\":\"Hel\"}}\n"
        "\n"
        "event: content_block_delta\n"
        "data: {\"type\":\"content_block_delta\",\"index\":0,"
        "\"delta\":{\"type\":\"text_delta\",\"text\":\"lo\"}}\n"
        "\n"
        "event: content_block_stop\n"
        "data: {\"type\":\"content_block_stop\",\"index\":0}\n"
        "\n"
        "event: message_delta\n"
        "data: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"end_turn\"},"
        "\"usage\":{\"output_tokens\":2}}\n"
        "\n"
        "event: message_stop\n"
        "data: {\"type\":\"message_stop\"}\n"
        "\n"
    )
    frames = list(
        ks_envelope.iter_anthropic_stream_as_responses(
            io.BytesIO(raw.encode("utf-8")), "m"
        )
    )
    joined = b"".join(frames).decode("utf-8")
    assert joined.index("response.created") < joined.index('"delta": "Hel"')
    assert joined.index('"delta": "Hel"') < joined.index('"delta": "lo"')
    assert joined.index('"delta": "lo"') < joined.index("response.completed")
    assert '"delta": "Hello"' not in joined


def test_anthropic_stream_tool_use_emits_custom_tool_call():
    raw = (
        "event: content_block_start\n"
        "data: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":"
        "{\"type\":\"tool_use\",\"id\":\"toolu_1\",\"name\":\"exec\",\"input\":{}}}\n"
        "\n"
        "event: content_block_delta\n"
        "data: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":"
        "{\"type\":\"input_json_delta\",\"partial_json\":\"{\\\"input\\\": \\\"ls\\\"}\"}}\n"
        "\n"
        "event: content_block_stop\n"
        "data: {\"type\":\"content_block_stop\",\"index\":0}\n"
        "\n"
        "event: message_delta\n"
        "data: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"tool_use\"}}\n"
        "\n"
        "event: message_stop\n"
        "data: {\"type\":\"message_stop\"}\n"
        "\n"
    )
    joined = b"".join(
        ks_envelope.iter_anthropic_stream_as_responses(
            io.BytesIO(raw.encode("utf-8")), "m"
        )
    ).decode("utf-8")
    assert '"type": "custom_tool_call"' in joined
    assert '"name": "exec"' in joined
    assert "event: response.completed" in joined


def test_translate_request_string_input():
    out = ks_envelope.translate_request({"model": "m", "input": "ping"})
    assert out["messages"][0]["content"][0]["text"] == "ping"


def test_translate_request_passes_temperature():
    out = ks_envelope.translate_request(
        {"model": "m", "input": "x", "temperature": 0.2}
    )
    assert out["temperature"] == 0.2


def test_translate_request_rejects_missing_model():
    with pytest.raises(ks_envelope.EnvelopeError):
        ks_envelope.translate_request({"input": "x"})


def test_translate_request_rejects_bad_input():
    with pytest.raises(ks_envelope.EnvelopeError):
        ks_envelope.translate_request({"model": "m", "input": 42})


# --- response translation ------------------------------------------------------


def test_translate_response_maps_choice_to_output_message():
    upstream = {
        "id": "chatcmpl-1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "pong"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    out = ks_envelope.translate_response(upstream, "gpt-5.6-sol")
    assert out["object"] == "response"
    assert out["status"] == "completed"
    assert out["model"] == "gpt-5.6-sol"
    assert out["output"][0]["content"][0]["text"] == "pong"
    assert out["usage"]["input_tokens"] == 10
    assert out["usage"]["output_tokens"] == 2


def test_translate_response_non_stop_finish_marks_incomplete():
    upstream = {
        "choices": [{"message": {"content": ""}, "finish_reason": "failed"}]
    }
    out = ks_envelope.translate_response(upstream, "m")
    assert out["status"] == "incomplete"
    assert out["incomplete_details"]["reason"] == "failed"


def test_translate_response_rejects_missing_choices():
    with pytest.raises(ks_envelope.EnvelopeError):
        ks_envelope.translate_response({}, "m")


def test_translate_error_response_shape():
    out = ks_envelope.translate_error_response(401, "nope")
    assert out["status"] == "failed"
    assert out["error"]["code"] == "upstream_error"
    assert "401" in out["error"]["message"]


# --- auth loading --------------------------------------------------------------


def test_load_upstream_key(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": "gg:test-key"}), encoding="utf-8")
    assert ks_envelope.load_upstream_key(auth) == "gg:test-key"


def test_load_upstream_key_missing_file(tmp_path):
    with pytest.raises(ks_envelope.EnvelopeError):
        ks_envelope.load_upstream_key(tmp_path / "nope.json")


def test_load_upstream_key_missing_field(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    with pytest.raises(ks_envelope.EnvelopeError):
        ks_envelope.load_upstream_key(auth)


def test_redact_hides_secret():
    assert ks_envelope._redact("key gg:abc tail", "gg:abc") == "key <redacted> tail"


# --- end-to-end with mock upstream --------------------------------------------


class _MockUpstream(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        assert self.path == "/messages"
        assert self.headers.get("x-api-key") == "gg:mock"
        assert self.headers.get("anthropic-version") == "2023-06-01"
        if body["messages"][0]["content"][0]["text"] == "blocked":
            reply = {
                "choices": [{"message": {"content": ""}, "finish_reason": "failed"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        else:
            # capture the system field so the test can assert translation
            reply = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "echo:" + body.get("system", "")[:12],
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            }
        payload = json.dumps(reply).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


@pytest.fixture(scope="module")
def _servers(tmp_path_factory):
    upstream_dir = tmp_path_factory.mktemp("upstream")
    auth = upstream_dir / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": "gg:mock"}), encoding="utf-8")

    upstream = HTTPServer(("127.0.0.1", 0), _MockUpstream)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    handler = type(
        "Bound",
        (ks_envelope.EnvelopeHandler,),
        {
            "upstream_key": "gg:mock",
            "upstream_base": f"http://127.0.0.1:{upstream.server_port}",
            "secret_for_redaction": "gg:mock",
            "verbose": False,
        },
    )
    adapter = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    adapter.daemon_threads = True
    adapter_thread = threading.Thread(target=adapter.serve_forever, daemon=True)
    adapter_thread.start()

    yield {
        "adapter_port": adapter.server_port,
        "upstream_port": upstream.server_port,
        "auth": auth,
    }

    adapter.shutdown()
    upstream.shutdown()
    adapter.server_close()
    upstream.server_close()


def _post_responses(port: int, body: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_end_to_end_translates_both_directions(_servers):
    out = _post_responses(
        _servers["adapter_port"],
        {
            "model": "gpt-5.6-sol",
            "instructions": "contract text here",
            "input": [{"role": "user", "content": "hello"}],
            "max_output_tokens": 256,
        },
    )
    assert out["object"] == "response"
    assert out["status"] == "completed"
    text = out["output"][0]["content"][0]["text"]
    assert text == "echo:contract tex"


def test_end_to_end_blocked_cell_maps_to_incomplete(_servers):
    out = _post_responses(
        _servers["adapter_port"],
        {
            "model": "gpt-5.6-sol",
            "instructions": "contract",
            "input": [{"role": "user", "content": "blocked"}],
        },
    )
    assert out["status"] == "incomplete"
    assert out["incomplete_details"]["reason"] == "failed"


def test_end_to_end_stream_request_gets_sse(_servers):
    req = urllib.request.Request(
        f"http://127.0.0.1:{_servers['adapter_port']}/v1/responses",
        data=json.dumps(
            {
                "model": "gpt-5.6-sol",
                "instructions": "contract",
                "stream": True,
                "input": [{"role": "user", "content": "hello"}],
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        assert resp.headers.get("Content-Type", "").startswith("text/event-stream")
        body = resp.read().decode("utf-8")
    assert "event: response.completed" in body
    assert "event: response.output_text.delta" in body


class _AnthropicSseUpstream(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        assert body.get("stream") is True
        chunks = [
            'event: content_block_start\ndata: {"type":"content_block_start",'
            '"index":0,"content_block":{"type":"text","text":""}}\n\n',
            'event: content_block_delta\ndata: {"type":"content_block_delta",'
            '"index":0,"delta":{"type":"text_delta","text":"ab"}}\n\n',
            'event: content_block_stop\ndata: {"type":"content_block_stop",'
            '"index":0}\n\n',
            'event: message_delta\ndata: {"type":"message_delta",'
            '"delta":{"stop_reason":"end_turn"}}\n\n',
            'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()

    def log_message(self, fmt, *args):
        pass


def test_end_to_end_forwards_anthropic_sse_deltas():
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _AnthropicSseUpstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    handler = type(
        "BoundSse",
        (ks_envelope.EnvelopeHandler,),
        {
            "upstream_key": "k",
            "upstream_base": f"http://127.0.0.1:{upstream.server_address[1]}",
            "secret_for_redaction": "k",
            "verbose": False,
        },
    )
    adapter = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    adapter.daemon_threads = True
    threading.Thread(target=adapter.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{adapter.server_address[1]}/v1/responses",
            data=json.dumps(
                {
                    "model": "m",
                    "stream": True,
                    "input": [{"role": "user", "content": "hi"}],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
        assert '"delta": "ab"' in body
        assert "event: response.completed" in body
        assert body.index("response.created") < body.index('"delta": "ab"')
    finally:
        adapter.shutdown()
        upstream.shutdown()
        adapter.server_close()
        upstream.server_close()


def test_health_endpoint(_servers):
    with urllib.request.urlopen(
        f"http://127.0.0.1:{_servers['adapter_port']}/v1/health", timeout=10
    ) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assert data["ok"] is True


def test_unknown_post_path_404(_servers):
    req = urllib.request.Request(
        f"http://127.0.0.1:{_servers['adapter_port']}/v1/nope",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


# --- CLI guards ----------------------------------------------------------------


def test_main_rejects_bad_port(capsys):
    with pytest.raises(SystemExit) as exc_info:
        ks_envelope.main(["--port", "0"])
    assert exc_info.value.code == 2


def test_main_rejects_bad_upstream_scheme(capsys):
    with pytest.raises(SystemExit) as exc_info:
        ks_envelope.main(["--upstream", "ftp://x"])
    assert exc_info.value.code == 2


def test_translate_tools_from_additional_tools():
    raw = [
        {
            "type": "additional_tools",
            "role": "developer",
            "tools": [
                {
                    "type": "custom",
                    "name": "exec",
                    "description": "Run code",
                    "format": {"type": "grammar", "syntax": "lark", "definition": "start: ..."},
                }
            ],
        }
    ]
    tools = ks_envelope._translate_tools(raw)
    assert len(tools) == 1
    assert tools[0]["name"] == "exec"
    assert tools[0]["description"] == "Run code"
    assert tools[0]["input_schema"]["properties"]["input"]["type"] == "string"
    assert tools[0]["input_schema"]["required"] == ["input"]


def test_translate_tools_expands_namespace_and_keeps_function_schema():
    raw = [
        {
            "type": "additional_tools",
            "tools": [
                {"type": "custom", "name": "exec", "description": "run"},
                {
                    "type": "function",
                    "name": "wait",
                    "description": "wait on a cell",
                    "parameters": {
                        "type": "object",
                        "properties": {"cell_id": {"type": "string"}},
                        "required": ["cell_id"],
                    },
                },
                {
                    "type": "namespace",
                    "name": "collaboration",
                    "tools": [
                        {
                            "type": "function",
                            "name": "send_message",
                            "description": "message an agent",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "target": {"type": "string"},
                                    "message": {"type": "string"},
                                },
                                "required": ["target", "message"],
                            },
                        }
                    ],
                },
            ],
        }
    ]
    tools = ks_envelope._translate_tools(raw)
    by_name = {t["name"]: t for t in tools}
    assert set(by_name) == {"exec", "wait", "send_message"}
    assert "collaboration" not in by_name
    assert by_name["exec"]["input_schema"]["properties"]["input"]["type"] == "string"
    assert by_name["wait"]["input_schema"]["required"] == ["cell_id"]
    assert "target" in by_name["send_message"]["input_schema"]["properties"]


def test_translate_tools_ignores_bad_entries():
    raw = [
        {"type": "additional_tools", "role": "developer", "tools": [{"type": "custom"}, "junk"]},
        {"type": "message", "role": "user", "content": "x"},
    ]
    assert ks_envelope._translate_tools(raw) == []
    assert ks_envelope._translate_tools("not-a-list") == []


def test_translate_request_carries_tools():
    body = {
        "model": "m",
        "tool_choice": "auto",
        "input": [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [
                    {"type": "custom", "name": "exec", "description": "run", "format": {}}
                ],
            },
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "run it"}]},
        ],
    }
    out = ks_envelope.translate_request(body)
    assert out["tools"][0]["name"] == "exec"
    assert out["tool_choice"] == {"type": "auto"}


def test_translate_request_function_call_history():
    body = {
        "model": "m",
        "input": [
            {"type": "function_call", "call_id": "call_1", "name": "exec", "arguments": "{\"input\": \"echo hi\"}"},
            {"type": "function_call_output", "call_id": "call_1", "output": "hi"},
            {"type": "message", "role": "user", "content": "next"},
        ],
    }
    out = ks_envelope.translate_request(body)
    roles = [m["role"] for m in out["messages"]]
    assert roles == ["assistant", "user", "user"]
    tool_use = out["messages"][0]["content"][0]
    assert tool_use["type"] == "tool_use"
    assert tool_use["id"] == "call_1"
    assert tool_use["name"] == "exec"
    assert tool_use["input"] == {"input": "echo hi"}
    tool_result = out["messages"][1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "call_1"
    assert tool_result["content"] == "hi"


def test_translate_request_custom_tool_call_history():
    body = {
        "model": "m",
        "input": [
            {"type": "custom_tool_call", "call_id": "call_2", "name": "exec", "input": "await tools.exec_command({...})"},
            {"type": "function_call_output", "call_id": "call_2", "output": "done"},
            {"type": "message", "role": "user", "content": "next"},
        ],
    }
    out = ks_envelope.translate_request(body)
    tool_use = out["messages"][0]["content"][0]
    assert tool_use["input"] == {"input": "await tools.exec_command({...})"}


def test_upstream_tool_calls_extraction():
    choice = {
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "exec", "arguments": "{\"input\": \"echo x\"}"},
                }
            ],
        },
        "finish_reason": "tool_calls",
    }
    calls = ks_envelope._upstream_tool_calls(choice)
    assert calls == [{"id": "call_abc", "name": "exec", "arguments": "{\"input\": \"echo x\"}"}]
    assert ks_envelope._upstream_tool_calls({}) == []
    assert ks_envelope._upstream_tool_calls({"message": {}}) == []


def test_translate_response_tool_call_output_item():
    upstream = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {"name": "exec", "arguments": "{\"input\": \"echo x\"}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    out = ks_envelope.translate_response(upstream, "m")
    assert out["status"] == "completed"
    assert len(out["output"]) == 1
    item = out["output"][0]
    assert item["type"] == "custom_tool_call"
    assert item["call_id"] == "call_abc"
    assert item["name"] == "exec"
    assert item["input"] == "echo x"  # {"input":...} envelope unwrapped to raw grammar source


def test_translate_response_text_plus_tool_call():
    upstream = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "I'll run that.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "exec", "arguments": "await tools.exec_command({command: 'ls'})"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    out = ks_envelope.translate_response(upstream, "m")
    kinds = [item["type"] for item in out["output"]]
    assert kinds == ["message", "custom_tool_call"]


def test_stream_events_include_tool_call_items():
    response = {
        "id": "resp_t",
        "object": "response",
        "created_at": 1,
        "model": "m",
        "status": "completed",
        "output": [
            {
                "id": "ctc_1",
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": "call_1",
                "name": "exec",
                "input": "code",
            }
        ],
        "usage": {},
    }
    frames = ks_envelope.stream_response_events(response)
    joined = b"".join(frames).decode("utf-8")
    assert "response.output_item.added" in joined
    assert "response.completed" in joined
    assert '"type": "custom_tool_call"' in joined


def test_tool_call_input_string_becomes_input_dict():
    item = {"name": "exec", "arguments": "await tools.exec_command({command: 'ls'})"}
    assert ks_envelope._tool_call_input(item) == (
        "exec",
        {"input": "await tools.exec_command({command: 'ls'})"},
    )
    item = {"name": "wait", "arguments": "{\"a\": 1}"}
    assert ks_envelope._tool_call_input(item) == ("wait", {"a": 1})
    item = {"name": "wait", "arguments": {"a": 1}}
    assert ks_envelope._tool_call_input(item) == ("wait", {"a": 1})


def test_translate_request_forwards_input_image():
    body = {
        "model": "m",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "what is this"},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,AAAA",
                    },
                ],
            }
        ],
    }
    out = ks_envelope.translate_request(body)
    content = out["messages"][0]["content"]
    types = [block["type"] for block in content]
    assert types == ["text", "image"]
    assert content[1]["source"]["type"] == "base64"
    assert content[1]["source"]["media_type"] == "image/png"
    assert content[1]["source"]["data"] == "AAAA"


def test_translate_request_reasoning_off_by_default():
    body = {
        "model": "m",
        "reasoning": {"effort": "xhigh", "context": "all_turns"},
        "input": [{"role": "user", "content": "x"}],
    }
    out = ks_envelope.translate_request(body)
    assert "thinking" not in out
    assert "extra-high depth" in out.get("system", "")


def test_translate_request_reasoning_effort_maps_to_thinking():
    body = {
        "model": "m",
        "reasoning": {"effort": "xhigh", "context": "all_turns"},
        "input": [{"role": "user", "content": "x"}],
    }
    out = ks_envelope.translate_request(body, thinking_passthrough=True)
    assert out["thinking"] == {"type": "enabled", "budget_tokens": 16384}


def test_translate_request_unknown_effort_omits_thinking():
    body = {
        "model": "m",
        "reasoning": {"effort": "absurd"},
        "input": [{"role": "user", "content": "x"}],
    }
    out = ks_envelope.translate_request(body, thinking_passthrough=True)
    assert "thinking" not in out


def test_translate_request_no_reasoning_field():
    out = ks_envelope.translate_request({"model": "m", "input": "x"}, thinking_passthrough=True)
    assert "thinking" not in out
