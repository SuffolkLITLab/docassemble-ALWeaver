#!/usr/bin/env python3
"""Loopback-only OpenAI-compatible fixture for the classroom stress harness.

Provides deterministic JSON drafts after eight seconds and GET /metrics. Run
inside the Docassemble container and temporarily configure its model base URL
as http://127.0.0.1:18089/v1 with a dummy key; restore configuration afterwards.
It makes no upstream requests and is unsuitable for production model output.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

active = 0
maximum = 0
calls = 0
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            self.respond(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": name,
                            "object": "model",
                            "created": 1,
                            "owned_by": "local-stress",
                        }
                        for name in ("gpt-5-nano", "gpt-4o-mini", "gpt-4o")
                    ],
                }
            )
        elif self.path == "/metrics":
            with lock:
                self.respond(
                    {
                        "active": active,
                        "maximum_active": maximum,
                        "calls": calls,
                        "delay_seconds": 8,
                    }
                )
        else:
            self.respond({"error": "not found"}, 404)

    def do_POST(self):
        global active, maximum, calls
        request = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
        )
        with lock:
            active += 1
            calls += 1
            maximum = max(maximum, active)
        try:
            time.sleep(8)
            content = {
                "question": "Stress fixture question",
                "subquestion": "Local deterministic model fixture.",
                "continue_button_field": "",
                "fields": [
                    {
                        "label": "Stress answer",
                        "field": "stress_answer",
                        "datatype": "text",
                    }
                ],
            }
            self.respond(
                {
                    "id": "stress-completion",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request.get("model", "gpt-4o-mini"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(content),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            )
        finally:
            with lock:
                active -= 1


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 18089), Handler).serve_forever()
