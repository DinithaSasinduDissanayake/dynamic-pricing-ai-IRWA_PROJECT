"""
Local OpenAI-Compatible Bridge for OpenCode MuseSpark.
Bridges OpenAI /v1/chat/completions to `opencode run --pure --model opencode/muse-spark-1.2-contributor-free`.
Supports concurrent requests via ThreadingHTTPServer.
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
from pathlib import Path

OPENCODE_BIN = "/home/sasindu/.opencode/bin/opencode"
DEFAULT_MODEL = "opencode/muse-spark-1.2-contributor-free"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("opencode_bridge")


def run_opencode_inference(prompt: str, model: str = DEFAULT_MODEL) -> str:
    start_t = time.time()
    logger.info(f"Dispatching inference to OpenCode ({model}): prompt_len={len(prompt)}")
    try:
        res = subprocess.run(
            [OPENCODE_BIN, "run", "--pure", "--model", model, prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        duration = time.time() - start_t
        logger.info(f"OpenCode inference returned in {duration:.2f}s (exit {res.returncode})")
        if res.returncode != 0:
            logger.error(f"OpenCode error: {res.stderr}")
            return f"[Error from OpenCode: {res.stderr.strip()}]"
        return res.stdout.strip()
    except Exception as e:
        logger.error(f"Failed to execute opencode: {e}")
        return f"[Error executing OpenCode: {e}]"


class BridgeHandler(BaseHTTPRequestHandler):
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
            tools = req.get("tools")
            stream = req.get("stream", False)
            model = req.get("model") or DEFAULT_MODEL
            if not model.startswith("opencode/"):
                model = f"opencode/{model}"

            formatted_parts = []
            if tools:
                tools_desc = json.dumps(tools, indent=2)
                formatted_parts.append(
                    f"[Available Tools]\nYou have access to the following tools:\n{tools_desc}\n"
                    f"To call a tool, you MUST reply with a JSON object:\n"
                    f'{{"tool_calls": [{{"name": "<tool_name>", "arguments": {{...}}}}]}}\n'
                    f"If no tool call is needed, reply with normal text."
                )

            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    formatted_parts.append(f"[System Instructions]\n{content}")
                elif role == "user":
                    formatted_parts.append(f"[User]\n{content}")
                elif role == "assistant":
                    tool_calls = m.get("tool_calls")
                    if tool_calls:
                        formatted_parts.append(f"[Assistant Tool Calls]\n{json.dumps(tool_calls)}")
                    else:
                        formatted_parts.append(f"[Assistant]\n{content}")
                elif role == "tool":
                    name = m.get("name", "tool")
                    formatted_parts.append(f"[Tool Response for {name}]\n{content}")

            prompt = "\n\n".join(formatted_parts)
            response_text = run_opencode_inference(prompt, model=model)

            completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created_ts = int(time.time())

            # Check if model output contains tool_calls
            tool_calls_payload = None
            if tools and "tool_calls" in response_text:
                try:
                    # extract json snippet
                    match = re.search(r'\{.*"tool_calls".*\}', response_text, re.DOTALL)
                    if match:
                        parsed = json.loads(match.group(0))
                        if "tool_calls" in parsed:
                            tc_list = []
                            for idx, tc in enumerate(parsed["tool_calls"]):
                                tc_list.append({
                                    "id": f"call_{uuid.uuid4().hex[:8]}",
                                    "type": "function",
                                    "function": {
                                        "name": tc.get("name"),
                                        "arguments": json.dumps(tc.get("arguments", {})) if isinstance(tc.get("arguments"), dict) else str(tc.get("arguments", "{}"))
                                    }
                                })
                            tool_calls_payload = tc_list
                except Exception as e:
                    logger.warning(f"Failed to parse tool calls from model output: {e}")

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                if tool_calls_payload:
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": "muse-spark-1.2-contributor-free",
                        "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": tool_calls_payload}, "finish_reason": "tool_calls"}]
                    }
                else:
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
                
                msg_payload = {"role": "assistant"}
                if tool_calls_payload:
                    msg_payload["tool_calls"] = tool_calls_payload
                    msg_payload["content"] = None
                    finish_reason = "tool_calls"
                else:
                    msg_payload["content"] = response_text
                    finish_reason = "stop"

                res = {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": created_ts,
                    "model": "muse-spark-1.2-contributor-free",
                    "choices": [{
                        "index": 0,
                        "message": msg_payload,
                        "finish_reason": finish_reason
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
    httpd = ThreadingHTTPServer(server_address, BridgeHandler)
    logger.info(f"OpenCode MuseSpark Threaded Bridge running on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8088
    run_server(port)
