"""Real provider adapter protocol tests against a local mock HTTP server.

No real endpoints, keys or egress: the mock server records requests and
replies with OpenAI-compatible payloads.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from knowledge.providers import (
    EgressNotAllowed,
    OpenAICompatibleChat,
    OpenAICompatibleEmbedding,
    OpenAICompatibleVision,
    ProviderCallError,
    load_providers,
)


class _Recorder:
    def __init__(self):
        self.requests = []
        self.responses = {}  # path -> list of (status, payload)
        self.serving = True

    def next(self, path):
        queue = self.responses.get(path)
        return queue.pop(0) if queue else (200, {})


def build_mock_server():
    recorder = _Recorder()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            recorder.requests.append({
                "path": self.path,
                "auth": self.headers.get("Authorization", ""),
                "body": body,
            })
            status, payload = recorder.next(self.path)
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, recorder


CHAT_OK = {
    "choices": [{"message": {"role": "assistant", "content": "正常"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 2},
}
EMBED_OK = {
    "data": [{"index": 0, "embedding": [0.1, 0.2]},
             {"index": 1, "embedding": [0.3, 0.4]}],
    "usage": {"prompt_tokens": 8, "total_tokens": 8},
}


class ProviderHttpTest(unittest.TestCase):
    def setUp(self):
        self.server, self.recorder = build_mock_server()
        self.base = "http://127.0.0.1:%d/v4" % self.server.server_address[1]
        self.chat = OpenAICompatibleChat("chat", "GLM-5.3", self.base,
                                         "test-key", egress_allowed=True)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_chat_completion_and_usage(self):
        self.recorder.responses["/v4/chat/completions"] = [(200, CHAT_OK)]
        text, usage = self.chat.complete("只回复：正常")
        self.assertEqual(text, "正常")
        self.assertEqual(usage.input_tokens, 12)
        self.assertEqual(usage.output_tokens, 2)
        self.assertIn("GLM-5.3", usage.cost_basis)
        request = self.recorder.requests[0]
        self.assertEqual(request["auth"], "Bearer test-key")
        self.assertEqual(request["body"]["model"], "GLM-5.3")
        self.assertEqual(request["body"]["messages"][0]["role"], "user")

    def test_egress_gate_refuses_before_any_request(self):
        locked = OpenAICompatibleChat("chat", "GLM-5.3", self.base,
                                      "test-key", egress_allowed=False)
        with self.assertRaises(EgressNotAllowed):
            locked.complete("x")
        self.assertEqual(self.recorder.requests, [])  # nothing left the box

    def test_non_retryable_http_error(self):
        self.recorder.responses["/v4/chat/completions"] = [(401, {
            "error": {"message": "invalid api key"}})]
        with self.assertRaises(ProviderCallError) as ctx:
            self.chat.complete("x")
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_retry_then_success_on_429(self):
        self.recorder.responses["/v4/chat/completions"] = [
            (429, {"error": {"message": "rate limit"}}), (200, CHAT_OK)]
        text, usage = self.chat.complete("x")
        self.assertEqual(text, "正常")
        self.assertEqual(len(self.recorder.requests), 2)

    def test_embedding_shapes_and_dimensions(self):
        embedder = OpenAICompatibleEmbedding(
            "embedding", "embedding-3", self.base, "k",
            dimensions=512, egress_allowed=True)
        self.recorder.responses["/v4/embeddings"] = [(200, EMBED_OK)]
        vectors, usage = embedder.embed(["你好", "world"])
        self.assertEqual(len(vectors), 2)
        self.assertEqual(vectors[1], [0.3, 0.4])
        self.assertEqual(usage.input_tokens, 8)
        self.assertEqual(self.recorder.requests[0]["body"]["dimensions"], 512)

    def test_vision_message_structure(self):
        vision = OpenAICompatibleVision("vision_ocr", "GLM-5.3-Flash",
                                        self.base, "k", egress_allowed=True)
        self.recorder.responses["/v4/chat/completions"] = [(200, CHAT_OK)]
        vision.complete_with_image("描述图片", b"\x89PNG-fake", "image/png")
        content = self.recorder.requests[0]["body"]["messages"][0]["content"]
        parts = {part["type"]: part for part in content}
        self.assertIn("text", parts)
        self.assertTrue(parts["image_url"]["image_url"]["url"]
                        .startswith("data:image/png;base64,"))

    def test_load_providers_builds_real_adapters(self):
        providers = load_providers({"providers": {
            "chat": {"kind": "openai-compatible", "base_url": self.base,
                     "api_key": "real-key", "model": "GLM-5.3",
                     "egress_allowed": True},
            "embedding": {"kind": "openai-compatible", "base_url": self.base,
                          "api_key": "real-key", "model": "embedding-3",
                          "egress_allowed": True},
            "vision_ocr": {"kind": "openai-compatible-vision",
                           "base_url": self.base, "api_key": "real-key",
                           "model": "GLM-5.3-Flash", "egress_allowed": True},
        }})
        self.assertIsInstance(providers["chat"], OpenAICompatibleChat)
        self.assertIsInstance(providers["embedding"],
                              OpenAICompatibleEmbedding)
        self.assertIsInstance(providers["vision_ocr"], OpenAICompatibleVision)
        self.assertTrue(providers["chat"].egress_allowed)
        # egress flag from config is honored
        locked = load_providers({"providers": {
            "chat": {"kind": "openai-compatible", "base_url": self.base,
                     "api_key": "real-key", "model": "m",
                     "egress_allowed": False}}})["chat"]
        self.assertFalse(locked.egress_allowed)


if __name__ == "__main__":
    unittest.main()
