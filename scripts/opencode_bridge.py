"""
Local OpenAI-Compatible Bridge for OpenCode MuseSpark in Clean Raw Agent Mode.
Bridges OpenAI /v1/chat/completions to `opencode run --agent raw "<prompt>"`.
Guarantees zero file-system or shell tool access.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPENCODE_BIN = "/home/sasindu/.opencode/bin/opencode"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("opencode_bridge")


def run_opencode_raw(prompt: str) -> str:
    start_t = time.time()
    logger.info(f"Dispatching clean raw inference: prompt_len={len(prompt)}")
    try:
        res = subprocess.run(
            [OPENCODE_BIN, "run", "--agent", "raw", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        duration = time.time() - start_t
        logger.info(f"Clean raw inference returned in {duration:.2f}s (exit {res.returncode})")
        if res.returncode != 0:
            logger.error(f"OpenCode error: {res.stderr}")
            return f"[Error from OpenCode: {res.stderr.strip()}]"
        return res.stdout.strip()
    except Exception as e:
        logger.error(f"Failed to execute opencode: {e}")
        return f"[Error executing OpenCode: {e}]"


class CleanBridgeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/health", "/v1/models"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = {
                "object": "list",
                "data": [{"id": "muse-spark-1.2-contributor-free", "object": "model", "owned_by": "opencode"}]
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            req = json.loads(body.decode("utf-8"))

            messages = req.get("messages", [])
            stream = req.get("stream", False)

            formatted_parts = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    formatted_parts.append(f"[System Instructions]\n{content}")
                elif role == "user":
                    formatted_parts.append(f"[User]\n{content}")
                elif role == "assistant":
                    formatted_parts.append(f"[Assistant]\n{content}")
                elif role == "tool":
                    name = m.get("name", "tool")
                    formatted_parts.append(f"[Tool Response for {name}]\n{content}")

            prompt = "\n\n".join(formatted_parts)
            response_text = run_opencode_raw(prompt)

            completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created_ts = int(time.time())

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": "muse-spark-1.2-contributor-free",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}]
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                res = {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": created_ts,
                    "model": "muse-spark-1.2-contributor-free",
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop"
                    }],
                    "usage": {
                        "prompt_tokens": len(prompt.split()),
                        "completion_tokens": len(response_text.split()),
                        "total_tokens": len(prompt.split()) + len(response_text.split())
                    }
                }
                self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def run_server(port: int = 8088):
    server_address = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(server_address, CleanBridgeHandler)
    logger.info(f"OpenCode MuseSpark Clean Raw Bridge running on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8088
    run_server(port)
