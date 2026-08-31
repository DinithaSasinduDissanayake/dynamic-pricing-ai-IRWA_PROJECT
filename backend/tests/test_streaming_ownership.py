import json
import uuid
from typing import Dict, Any, List
from fastapi.testclient import TestClient


def make_test_client():
    import importlib
    import sys

    if "backend.main" in sys.modules:
        del sys.modules["backend.main"]
    mod = importlib.import_module("backend.main")
    return TestClient(mod.app)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def iter_sse_frames(resp):
    buf = b""
    for chunk in resp.iter_bytes():
        buf += chunk
        while b"\n\n" in buf:
            frame, buf = buf.split(b"\n\n", 1)
            yield frame.decode("utf-8", errors="ignore")


def test_streaming_endpoints_enforce_thread_ownership(monkeypatch):
    monkeypatch.setenv("UI_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    client = make_test_client()

    # Register User A
    email_a = unique_email("user_a")
    r_a = client.post("/api/register", json={"email": email_a, "password": "correcthorse1"})
    assert r_a.status_code == 200, r_a.text
    token_a = r_a.json()["token"]

    # Register User B
    email_b = unique_email("user_b")
    r_b = client.post("/api/register", json={"email": email_b, "password": "correcthorse2"})
    assert r_b.status_code == 200, r_b.text
    token_b = r_b.json()["token"]

    # User A creates a thread
    r_thread = client.post("/api/threads", params={"token": token_a}, json={"title": "User A Private Thread"})
    assert r_thread.status_code == 200, r_thread.text
    tid = r_thread.json()["id"]

    # 1. User B attempts non-streaming POST to User A's thread -> 404 rejected
    r_idor_post = client.post(
        f"/api/threads/{tid}/messages",
        params={"token": token_b},
        json={"user_name": "user_b", "content": "Attempting IDOR message"},
    )
    assert r_idor_post.status_code == 404
    assert r_idor_post.json().get("detail") == "Thread not found"

    # 2. User B attempts streaming POST to User A's thread -> 404 rejected
    with client.stream(
        "POST",
        f"/api/threads/{tid}/messages/stream",
        params={"token": token_b},
        json={"user_name": "user_b", "content": "Attempting IDOR stream"},
    ) as resp_idor_stream:
        assert resp_idor_stream.status_code == 404

    # 3. Owner (User A) posts non-streaming message -> 200 OK
    r_owner_post = client.post(
        f"/api/threads/{tid}/messages",
        params={"token": token_a},
        json={"user_name": "user_a", "content": "Owner message"},
    )
    assert r_owner_post.status_code == 200
    assert r_owner_post.json()["role"] == "assistant"

    # 4. Owner (User A) streams message -> 200 OK
    with client.stream(
        "POST",
        f"/api/threads/{tid}/messages/stream",
        params={"token": token_a},
        json={"user_name": "user_a", "content": "Owner stream message"},
    ) as resp_owner_stream:
        assert resp_owner_stream.status_code == 200
        got_done = False
        for frame in iter_sse_frames(resp_owner_stream):
            if "event: done" in frame:
                got_done = True
                break
        assert got_done


def test_streaming_endpoints_nonexistent_thread(monkeypatch):
    monkeypatch.setenv("UI_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    client = make_test_client()

    email = unique_email("user_nonexistent")
    r = client.post("/api/register", json={"email": email, "password": "correcthorse1"})
    assert r.status_code == 200
    token = r.json()["token"]

    non_existent_tid = 999999

    # Non-streaming on non-existent thread -> 404
    r_post = client.post(
        f"/api/threads/{non_existent_tid}/messages",
        params={"token": token},
        json={"user_name": "tester", "content": "hello"},
    )
    assert r_post.status_code == 404
    assert r_post.json().get("detail") == "Thread not found"

    # Streaming on non-existent thread -> 404
    with client.stream(
        "POST",
        f"/api/threads/{non_existent_tid}/messages/stream",
        params={"token": token},
        json={"user_name": "tester", "content": "hello"},
    ) as resp_stream:
        assert resp_stream.status_code == 404


def test_streaming_endpoints_anonymous_thread(monkeypatch):
    monkeypatch.setenv("UI_REQUIRE_LOGIN", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    client = make_test_client()

    # Create anonymous thread (no owner)
    r = client.post("/api/threads", json={"title": "Anonymous Thread"})
    assert r.status_code == 200
    tid = r.json()["id"]

    # Any caller can post to anonymous thread
    r_post = client.post(
        f"/api/threads/{tid}/messages",
        json={"user_name": "anon", "content": "hello anonymous"},
    )
    assert r_post.status_code == 200
    assert r_post.json()["role"] == "assistant"

    # Any caller can stream to anonymous thread
    with client.stream(
        "POST",
        f"/api/threads/{tid}/messages/stream",
        json={"user_name": "anon", "content": "stream anonymous"},
    ) as resp_stream:
        assert resp_stream.status_code == 200
        got_done = False
        for frame in iter_sse_frames(resp_stream):
            if "event: done" in frame:
                got_done = True
                break
        assert got_done
