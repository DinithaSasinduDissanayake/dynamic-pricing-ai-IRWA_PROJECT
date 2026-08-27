#!/usr/bin/env python3
"""
FluxPricer Diagnostic CLI (flux).
Composable terminal diagnostic commands for inspecting, driving, and testing the product pipeline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.parse
import urllib.request
import urllib.error

# ANSI Styling
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
RED = "\033[31m"

DEFAULT_BASE_URL = os.getenv("FLUX_API_URL", "http://127.0.0.1:8123")
SESSION_FILE = Path.home() / ".fluxpricer" / "session.json"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_cached_session() -> Dict[str, Any]:
    if not SESSION_FILE.exists():
        return {}
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_session(data: Dict[str, Any]) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(SESSION_FILE, 0o600)
    except Exception:
        pass


def clear_session() -> None:
    if SESSION_FILE.exists():
        try:
            SESSION_FILE.unlink()
        except Exception:
            pass


def get_token(args: Optional[argparse.Namespace] = None) -> Optional[str]:
    if args and getattr(args, "token", None):
        return args.token
    env_token = os.getenv("FLUX_API_TOKEN")
    if env_token:
        return env_token
    session = get_cached_session()
    return session.get("token")


def get_base_url(args: Optional[argparse.Namespace] = None) -> str:
    if args and getattr(args, "url", None):
        return args.url.rstrip("/")
    session = get_cached_session()
    return session.get("base_url", DEFAULT_BASE_URL).rstrip("/")


def http_request(
    method: str,
    path: str,
    data: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    base_url: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    multipart_files: Optional[Dict[str, Path]] = None,
) -> Dict[str, Any]:
    url = (base_url or DEFAULT_BASE_URL).rstrip("/") + path
    query_params = dict(params or {})
    if token:
        query_params["token"] = token
    if query_params:
        url += "?" + urllib.parse.urlencode(query_params)

    headers = {
        "User-Agent": "FluxPricer-CLI/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body_bytes = None
    if multipart_files:
        boundary = "----FluxBoundary" + str(int(time.time()))
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        body_parts = []
        for field_name, file_path in multipart_files.items():
            filename = file_path.name
            file_data = file_path.read_bytes()
            body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
            body_parts.append(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8"))
            body_parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
            body_parts.append(file_data)
            body_parts.append(b"\r\n")
        body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body_bytes = b"".join(body_parts)
    elif data is not None:
        headers["Content-Type"] = "application/json"
        body_bytes = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            resp_body = resp.read().decode("utf-8")
            if not resp_body.strip():
                return {"status_code": resp.status, "ok": True}
            try:
                parsed = json.loads(resp_body)
                if isinstance(parsed, dict):
                    parsed["status_code"] = resp.status
                return parsed
            except json.JSONDecodeError:
                return {"status_code": resp.status, "raw": resp_body}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body)
            parsed["status_code"] = e.code
            return parsed
        except Exception:
            return {"status_code": e.code, "error": f"HTTP {e.code}: {e.reason}", "raw": err_body}
    except Exception as e:
        return {"status_code": 0, "error": f"Connection failed: {e}"}


# ==================== CLI HANDLERS ====================

def cmd_auth_register(args):
    base_url = get_base_url(args)
    res = http_request("POST", "/api/register", data={"email": args.email, "password": args.password}, base_url=base_url)
    if res.get("ok"):
        token = res.get("token")
        user = res.get("user", {})
        save_session({"base_url": base_url, "token": token, "user": user})
        print(f"{GREEN}[OK]{RESET} Registered and logged in as {BOLD}{args.email}{RESET} (id={user.get('user_id')})")
        print(f"Token saved to {SESSION_FILE}")
        return 0
    print(f"{RED}[ERROR]{RESET} Registration failed: {res.get('error') or res.get('detail')}")
    return 1


def cmd_auth_login(args):
    base_url = get_base_url(args)
    res = http_request("POST", "/api/login", data={"email": args.email, "password": args.password}, base_url=base_url)
    if res.get("ok"):
        token = res.get("token")
        user = res.get("user", {})
        save_session({"base_url": base_url, "token": token, "user": user})
        print(f"{GREEN}[OK]{RESET} Logged in as {BOLD}{args.email}{RESET} (id={user.get('user_id')})")
        print(f"Token saved to {SESSION_FILE}")
        return 0
    print(f"{RED}[ERROR]{RESET} Login failed: {res.get('error') or res.get('detail')}")
    return 1


def cmd_auth_whoami(args):
    token = get_token(args)
    base_url = get_base_url(args)
    if not token:
        print(f"{YELLOW}[WARN]{RESET} Not logged in. Run: flux auth login --email <email> --password <pw>")
        return 1
    res = http_request("GET", "/api/me", token=token, base_url=base_url)
    if res.get("ok"):
        u = res.get("user", {})
        print(f"User ID:    {u.get('user_id')}")
        print(f"Email:      {u.get('email')}")
        print(f"Full Name:  {u.get('full_name') or '-'}")
        print(f"Server:     {base_url}")
        return 0
    print(f"{RED}[ERROR]{RESET} Session invalid: {res.get('error') or res.get('detail')}")
    return 1


def cmd_catalog_upload(args):
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"{RED}[ERROR]{RESET} File not found: {file_path}")
        return 1
    token = get_token(args)
    base_url = get_base_url(args)
    res = http_request("POST", "/api/catalog/upload", token=token, base_url=base_url, multipart_files={"file": file_path})
    if res.get("success"):
        print(f"{GREEN}[OK]{RESET} Uploaded {BOLD}{file_path.name}{RESET}: {res.get('rows_inserted')} products inserted (processed {res.get('rows_processed')})")
        return 0
    print(f"{RED}[ERROR]{RESET} Catalog upload failed: {res.get('detail') or res.get('error')}")
    return 1


def cmd_catalog_list(args):
    token = get_token(args)
    base_url = get_base_url(args)
    res = http_request("GET", "/api/catalog/products", token=token, base_url=base_url)
    if res.get("success"):
        products = res.get("products", [])
        print(f"{BOLD}{'SKU':<15} {'PRICE':<10} {'COST':<10} {'STOCK':<8} {'TITLE'}{RESET}")
        print("-" * 70)
        for p in products:
            sku = p.get("sku", "-")
            price = f"${p.get('current_price', 0.0):.2f}"
            cost = f"${p.get('cost', 0.0):.2f}"
            stock = str(p.get("stock", 0))
            title = p.get("title", "-")[:30]
            print(f"{CYAN}{sku:<15}{RESET} {price:<10} {cost:<10} {stock:<8} {title}")
        print(f"\nTotal products: {len(products)}")
        return 0
    print(f"{RED}[ERROR]{RESET} Failed to list products: {res.get('detail') or res.get('error')}")
    return 1


def cmd_catalog_urgency(args):
    token = get_token(args)
    base_url = get_base_url(args)
    res = http_request("GET", "/api/catalog/urgency", token=token, base_url=base_url)
    if res.get("success") or res.get("ok"):
        items = res.get("ranked_urgency", [])
        print(f"{BOLD}=== Portfolio Pricing Urgency Analysis ({len(items)} products) ==={RESET}\n")
        print(f"{BOLD}{'RANK':<5} {'SKU':<14} {'PRICE':<10} {'COST':<10} {'MARGIN':<9} {'COMP AVG':<10} {'GAP':<8} {'URGENCY':<9} {'REASON'}{RESET}")
        print("-" * 95)
        for idx, it in enumerate(items, 1):
            sku = it.get("sku", "-")
            price = f"${it.get('current_price', 0.0):.2f}"
            cost = f"${it.get('cost', 0.0):.2f}"
            margin = f"{it.get('margin_pct', 0.0):.1f}%"
            c_avg = f"${it.get('avg_competitor_price', 0.0):.2f}" if it.get("avg_competitor_price") is not None else "N/A"
            gap = f"{it.get('competitor_gap_pct'):+g}%" if it.get("competitor_gap_pct") is not None else "N/A"
            lvl = it.get("urgency_level", "LOW")
            badge = f"{RED}{lvl:<9}{RESET}" if lvl == "HIGH" else (f"{YELLOW}{lvl:<9}{RESET}" if lvl == "MEDIUM" else f"{GREEN}{lvl:<9}{RESET}")
            reason = it.get("reason", "-")
            print(f"{idx:<5} {CYAN}{sku:<14}{RESET} {price:<10} {cost:<10} {margin:<9} {c_avg:<10} {gap:<8} {badge} {reason}")
        
        if items:
            top = items[0]
            print(f"\n{BOLD}Top Priority:{RESET} {YELLOW}{top.get('sku')}{RESET} ({top.get('reason')})")
        return 0
    print(f"{RED}[ERROR]{RESET} Failed to evaluate portfolio urgency: {res.get('detail') or res.get('error')}")
    return 1


def cmd_catalog_show(args):
    token = get_token(args)
    base_url = get_base_url(args)
    res = http_request("GET", f"/api/catalog/products/{args.sku}", token=token, base_url=base_url)
    if res.get("success"):
        p = res.get("product", {})
        print(f"SKU:           {BOLD}{p.get('sku')}{RESET}")
        print(f"Title:         {p.get('title')}")
        print(f"Current Price: ${p.get('current_price', 0.0):.2f}")
        print(f"Cost:          ${p.get('cost', 0.0):.2f}")
        print(f"Stock:         {p.get('stock')}")
        print(f"Currency:      {p.get('currency', 'USD')}")
        print(f"Updated At:    {p.get('updated_at')}")
        return 0
    print(f"{RED}[ERROR]{RESET} Product '{args.sku}' not found: {res.get('detail') or res.get('error')}")
    return 1


def cmd_chat_send(args):
    token = get_token(args)
    base_url = get_base_url(args)
    thread_id = args.thread

    # Create thread if not specified
    if not thread_id:
        t_res = http_request("POST", "/api/threads", data={"title": f"CLI: {args.message[:25]}"}, token=token, base_url=base_url)
        if not t_res.get("id"):
            print(f"{RED}[ERROR]{RESET} Failed to create thread: {t_res.get('detail') or t_res.get('error')}")
            return 1
        thread_id = t_res.get("id")

    payload = {"user_name": "CLIUser", "content": args.message}

    if args.stream:
        # Stream SSE
        url = f"{base_url}/api/threads/{thread_id}/messages/stream?token={token}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        print(f"{DIM}[Connecting to chat stream on thread {thread_id}...]{RESET}\n")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            d = json.loads(data_str)
                            if "delta" in d:
                                sys.stdout.write(d["delta"])
                                sys.stdout.flush()
                        except Exception:
                            pass
            print("\n")
            return 0
        except Exception as e:
            print(f"{RED}[ERROR]{RESET} Streaming error: {e}")
            return 1
    else:
        res = http_request("POST", f"/api/threads/{thread_id}/messages", data=payload, token=token, base_url=base_url)
        if res.get("id"):
            content = res.get("content", "")
            meta = res.get("metadata", {}) or {}
            tools = res.get("tools", {}) or {}
            print(f"\n{BOLD}Assistant Response:{RESET}\n{content}\n")
            print(f"{DIM}--- Pipeline Trace ---{RESET}")
            print(f"Thread ID:    {thread_id}")
            print(f"Model:        {res.get('model') or 'mock'}")
            print(f"Tools Used:   {', '.join(tools.get('used', [])) or 'none'}")
            print(f"Tokens:       in={res.get('token_in') or '-'} out={res.get('token_out') or '-'}")
            return 0
        print(f"{RED}[ERROR]{RESET} Chat message failed: {res.get('detail') or res.get('error')}")
        return 1


def cmd_optimizer_run(args):
    token = get_token(args)
    base_url = get_base_url(args)
    res = http_request("POST", "/api/optimizer/run", data={"sku": args.sku, "algorithm": args.algo}, token=token, base_url=base_url)
    if res.get("ok"):
        p = res.get("proposal")
        print(f"{GREEN}[OK]{RESET} Optimizer executed for SKU {BOLD}{args.sku}{RESET}")
        if p:
            print(f"  Proposal ID:    {p.get('id')}")
            print(f"  Proposed Price: {YELLOW}${float(p.get('proposed_price', 0)):.2f}{RESET}")
            print(f"  Current Price:  ${float(p.get('current_price', 0)):.2f}")
            print(f"  Algorithm:      {p.get('algorithm')}")
            print(f"  Margin:         {float(p.get('margin', 0)):.1%}")
            print(f"  Timestamp:      {p.get('ts')}")
            rat = p.get("rationale")
            if rat:
                if isinstance(rat, dict):
                    r_text = rat.get("rationale_text") or "; ".join(rat.get("bounding_notes", []))
                else:
                    r_text = str(rat)
                print(f"  Rationale:      {r_text}")
        else:
            print(f"  Result: {res.get('message')}")
        return 0
    print(f"{RED}[ERROR]{RESET} Optimizer run failed: {res.get('error') or res.get('detail')}")
    return 1


def cmd_collector_run(args):
    token = get_token(args)
    base_url = get_base_url(args)
    res = http_request("POST", "/api/collector/run", data={"sku": args.sku}, token=token, base_url=base_url)
    if res.get("ok"):
        print(f"{GREEN}[OK]{RESET} Collector cycle finished: {res.get('count')} market ticks ingested")
        for t in res.get("ticks", []):
            print(f"  {CYAN}{t.get('sku'):<15}{RESET} our=${t.get('our_price'):.2f} comp=${t.get('competitor_price'):.2f} demand={t.get('demand_index')}")
        return 0
    print(f"{RED}[ERROR]{RESET} Collector run failed: {res.get('error') or res.get('detail')}")
    return 1


def cmd_proposals_list(args):
    token = get_token(args)
    base_url = get_base_url(args)
    params = {"sku": args.sku} if args.sku else {}
    res = http_request("GET", "/api/proposals", params=params, token=token, base_url=base_url)
    if res.get("ok"):
        proposals = res.get("proposals", [])
        if not proposals:
            print(f"No proposals found{' for ' + args.sku if args.sku else ''}.")
            return 0
        print(f"{BOLD}{'ID':<12} {'SKU':<12} {'PROPOSED':<10} {'CURRENT':<10} {'MARGIN':<8} {'ALGORITHM':<18} {'RATIONALE / TIMESTAMP'}{RESET}")
        print("-" * 110)
        for p in proposals:
            pid = str(p.get("id", "-"))[:10]
            sku = p.get("sku", "-")
            prop_p = f"${float(p.get('proposed_price', 0)):.2f}"
            curr_p = f"${float(p.get('current_price', 0)):.2f}"
            margin = f"{float(p.get('margin', 0)):.1%}"
            algo = str(p.get("algorithm", "-"))
            ts = str(p.get("ts", "-"))[:19]
            rat = p.get("rationale")
            r_text = ""
            if isinstance(rat, dict):
                r_text = rat.get("rationale_text") or "; ".join(rat.get("bounding_notes", []))
            elif isinstance(rat, str) and rat:
                r_text = rat
            
            rat_display = r_text if r_text else ts
            print(f"{pid:<12} {CYAN}{sku:<12}{RESET} {YELLOW}{prop_p:<10}{RESET} {curr_p:<10} {margin:<8} {algo:<18} {rat_display}")
        print(f"\nTotal proposals: {len(proposals)}")
        return 0
    print(f"{RED}[ERROR]{RESET} Failed to list proposals: {res.get('error') or res.get('detail')}")
    return 1


def cmd_proposals_show(args):
    token = get_token(args)
    base_url = get_base_url(args)
    res = http_request("GET", "/api/proposals", token=token, base_url=base_url)
    if res.get("ok"):
        proposals = res.get("proposals", [])
        matched = [p for p in proposals if str(p.get("id", "")).startswith(args.id)]
        if not matched:
            print(f"{RED}[ERROR]{RESET} Proposal not found matching ID '{args.id}'")
            return 1
        p = matched[0]
        print(f"{BOLD}Proposal Details:{RESET}")
        print(f"  ID:             {p.get('id')}")
        print(f"  SKU:            {p.get('sku')}")
        print(f"  Proposed Price: {YELLOW}${float(p.get('proposed_price', 0)):.2f}{RESET}")
        print(f"  Current Price:  ${float(p.get('current_price', 0)):.2f}")
        print(f"  Margin:         {float(p.get('margin', 0)):.1%}")
        print(f"  Algorithm:      {p.get('algorithm')}")
        print(f"  Timestamp:      {p.get('ts')}")
        rat = p.get("rationale")
        if isinstance(rat, dict):
            print(f"  Rationale Text: {rat.get('rationale_text') or '-'}")
            print(f"  Sample Count:   {rat.get('sample_count')}")
            print(f"  Avg Comp Price: ${rat.get('avg_competitor_price', 0):.2f}" if rat.get('avg_competitor_price') is not None else "  Avg Comp Price: N/A")
            print(f"  Cost Baseline:  ${rat.get('cost', 0):.2f}" if rat.get('cost') is not None else "  Cost Baseline:  N/A")
            print(f"  Confidence:     {float(rat.get('confidence', 0)):.0%}")
        elif rat:
            print(f"  Rationale:      {rat}")
        return 0
    print(f"{RED}[ERROR]{RESET} Failed to fetch proposals: {res.get('error') or res.get('detail')}")
    return 1


def cmd_alerts_incidents(args):
    token = get_token(args)
    base_url = get_base_url(args)
    if args.action == "ack" and args.id:
        res = http_request("POST", f"/api/alerts/incidents/{args.id}/ack", token=token, base_url=base_url)
        print(f"{GREEN}[OK]{RESET} Incident {args.id} acknowledged" if res.get("status") or res.get("ok") else f"Failed: {res}")
        return 0
    elif args.action == "resolve" and args.id:
        res = http_request("POST", f"/api/alerts/incidents/{args.id}/resolve", token=token, base_url=base_url)
        print(f"{GREEN}[OK]{RESET} Incident {args.id} resolved" if res.get("status") or res.get("ok") else f"Failed: {res}")
        return 0

    res = http_request("GET", "/api/alerts/incidents", token=token, base_url=base_url)
    if isinstance(res, list):
        incidents = res
    else:
        incidents = res.get("incidents", []) if isinstance(res, dict) else []

    if not incidents:
        print("No active alert incidents.")
        return 0
    print(f"{BOLD}{'ID':<10} {'SKU':<12} {'SEVERITY':<10} {'STATUS':<10} {'TITLE'}{RESET}")
    print("-" * 70)
    for inc in incidents:
        iid = str(inc.get("id", "-"))
        sku = inc.get("sku", "-")
        sev = inc.get("severity", "info")
        status = inc.get("status", "open")
        title = inc.get("title", "-")
        print(f"{iid:<10} {CYAN}{sku:<12}{RESET} {sev:<10} {status:<10} {title}")
    return 0


def cmd_agents_status(args):
    token = get_token(args)
    base_url = get_base_url(args)
    res = http_request("GET", "/api/agents/status", token=token, base_url=base_url)
    if res.get("ok"):
        llm = res.get("llm", {})
        agents = res.get("agents", {})
        print(f"{BOLD}=== FluxPricer Daemon Agents Status ==={RESET}")
        print(f"Uptime:       {res.get('uptime_sec')}s")
        print(f"LLM Engine:   {'MOCK (Deterministic)' if llm.get('mock_mode') else llm.get('provider')} (model: {llm.get('model')})")
        print(f"\n{BOLD}Active Daemons:{RESET}")
        for name, info in agents.items():
            subs = ", ".join(info.get("subscriptions", []))
            print(f"  {GREEN}●{RESET} {BOLD}{name:<22}{RESET} status={info.get('status')} subs=[{subs}]")
        return 0
    print(f"{RED}[ERROR]{RESET} Failed to fetch agent status: {res.get('error') or res.get('detail')}")
    return 1


def cmd_events_tail(args):
    events_file = PROJECT_ROOT / "data" / "events.jsonl"
    if not events_file.exists():
        if not args.follow:
            print("No events logged yet (data/events.jsonl does not exist).")
            return 0
        print(f"{DIM}[Waiting for data/events.jsonl to be created...]{RESET}")
        while not events_file.exists():
            time.sleep(0.5)

    def format_event(raw: str) -> Optional[str]:
        raw = raw.strip()
        if not raw:
            return None
        try:
            rec = json.loads(raw)
        except Exception:
            return f"{DIM}[RAW]{RESET} {raw}"
        ts = rec.get("ts", "")[:19].replace("T", " ")
        topic = rec.get("topic", "unknown")
        payload = rec.get("payload", {})
        sku = payload.get("sku") or payload.get("product_id") or "-"
        attrs = []
        if sku != "-":
            attrs.append(f"sku={BOLD}{sku}{RESET}")
        if "proposed_price" in payload:
            attrs.append(f"price={YELLOW}${float(payload['proposed_price']):.2f}{RESET}")
        if "algorithm" in payload:
            attrs.append(f"algo={payload['algorithm']}")
        if "title" in payload:
            attrs.append(f"msg=\"{payload['title'][:40]}\"")
        attr_str = " ".join(attrs) if attrs else json.dumps(payload)[:50]
        return f"{DIM}{ts}{RESET}  {MAGENTA}{topic:<22}{RESET}  {attr_str}"

    with events_file.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
        for l in lines[-args.lines:] if args.lines > 0 else lines:
            fmt = format_event(l)
            if fmt:
                print(fmt)

        if not args.follow:
            return 0

        while True:
            line = f.readline()
            if line:
                fmt = format_event(line)
                if fmt:
                    print(fmt, flush=True)
            else:
                time.sleep(0.25)


def cmd_serve(args):
    os.environ["MOCK_LLM"] = "1" if not args.no_mock_llm else "0"
    os.environ["BUS_BACKEND"] = "inproc"
    os.environ["UI_REQUIRE_LOGIN"] = "1"
    
    print(f"{BOLD}Starting FluxPricer server on {args.host}:{args.port} (MOCK_LLM={os.environ['MOCK_LLM']})...{RESET}")
    import subprocess
    cmd = [
        sys.executable, "-m", "uvicorn", "backend.main:app",
        "--host", args.host,
        "--port", str(args.port),
    ]
    try:
        subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    except KeyboardInterrupt:
        print("\nStopped server.")
        return 0


# ==================== MAIN PARSER ====================

def main():
    parser = argparse.ArgumentParser(prog="flux", description="FluxPricer Diagnostic & Inspection CLI")
    parser.add_argument("--url", help=f"Backend API URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--token", help="Override auth token")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # auth
    p_auth = subparsers.add_parser("auth", help="Authentication and session management")
    sp_auth = p_auth.add_subparsers(dest="auth_action", required=True)
    p_reg = sp_auth.add_parser("register", help="Register a new user account")
    p_reg.add_argument("--email", required=True)
    p_reg.add_argument("--password", required=True)
    p_reg.set_defaults(func=cmd_auth_register)

    p_log = sp_auth.add_parser("login", help="Log in with email and password")
    p_log.add_argument("--email", required=True)
    p_log.add_argument("--password", required=True)
    p_log.set_defaults(func=cmd_auth_login)

    p_who = sp_auth.add_parser("whoami", help="Show current user identity")
    p_who.set_defaults(func=cmd_auth_whoami)

    # catalog
    p_cat = subparsers.add_parser("catalog", help="Catalog upload and management")
    sp_cat = p_cat.add_subparsers(dest="catalog_action", required=True)
    p_cup = sp_cat.add_parser("upload", help="Upload a catalog file (CSV or JSON)")
    p_cup.add_argument("file", help="Path to CSV or JSON file")
    p_cup.set_defaults(func=cmd_catalog_upload)

    p_clist = sp_cat.add_parser("list", help="List catalog products")
    p_clist.set_defaults(func=cmd_catalog_list)

    p_curg = sp_cat.add_parser("urgency", help="Show portfolio pricing urgency summary and ranked priority")
    p_curg.set_defaults(func=cmd_catalog_urgency)

    p_cshow = sp_cat.add_parser("show", help="Show specific product details")
    p_cshow.add_argument("sku", help="Product SKU")
    p_cshow.set_defaults(func=cmd_catalog_show)

    # chat
    p_chat = subparsers.add_parser("chat", help="Chat interaction turns")
    sp_chat = p_chat.add_subparsers(dest="chat_action", required=True)
    p_csend = sp_chat.add_parser("send", help="Send a message to the pricing assistant")
    p_csend.add_argument("message", help="Message text")
    p_csend.add_argument("--thread", type=int, help="Thread ID (creates new if omitted)")
    p_csend.add_argument("--stream", action="store_true", help="Stream response via SSE")
    p_csend.set_defaults(func=cmd_chat_send)

    # optimizer
    p_opt = subparsers.add_parser("optimizer", help="Direct price optimizer execution")
    sp_opt = p_opt.add_subparsers(dest="opt_action", required=True)
    p_orun = sp_opt.add_parser("run", help="Run optimizer on SKU")
    p_orun.add_argument("sku", help="Product SKU")
    p_orun.add_argument("--algo", help="Algorithm (rule_based, profit_maximization, volatility_adjusted)")
    p_orun.set_defaults(func=cmd_optimizer_run)

    # collector
    p_col = subparsers.add_parser("collector", help="Data collector triggers")
    sp_col = p_col.add_subparsers(dest="col_action", required=True)
    p_crun = sp_col.add_parser("run", help="Trigger data collection cycle")
    p_crun.add_argument("sku", nargs="?", help="Optional SKU filter")
    p_crun.set_defaults(func=cmd_collector_run)

    # proposals
    p_prop = subparsers.add_parser("proposals", help="Inspect logged price proposals")
    sp_prop = p_prop.add_subparsers(dest="prop_action", required=True)
    p_plist = sp_prop.add_parser("list", help="List recent price proposals")
    p_plist.add_argument("sku", nargs="?", help="Optional SKU filter")
    p_plist.set_defaults(func=cmd_proposals_list)
    p_pshow = sp_prop.add_parser("show", help="Show details of a specific price proposal")
    p_pshow.add_argument("id", help="Proposal ID or ID prefix")
    p_pshow.set_defaults(func=cmd_proposals_show)

    # alerts
    p_alt = subparsers.add_parser("alerts", help="Alert incidents and notifications")
    sp_alt = p_alt.add_subparsers(dest="alert_action", required=True)
    p_ainc = sp_alt.add_parser("incidents", help="List or acknowledge/resolve alert incidents")
    p_ainc.add_argument("action", nargs="?", choices=["list", "ack", "resolve"], default="list")
    p_ainc.add_argument("id", nargs="?", help="Incident ID for ack/resolve")
    p_ainc.set_defaults(func=cmd_alerts_incidents)

    # agents
    p_ag = subparsers.add_parser("agents", help="Inspect daemon agent statuses")
    sp_ag = p_ag.add_subparsers(dest="agents_action", required=True)
    p_astat = sp_ag.add_parser("status", help="Get status of daemon agents and bus")
    p_astat.set_defaults(func=cmd_agents_status)

    # events
    p_ev = subparsers.add_parser("events", help="Audit events journal")
    sp_ev = p_ev.add_subparsers(dest="events_action", required=True)
    p_etail = sp_ev.add_parser("tail", help="Tail data/events.jsonl")
    p_etail.add_argument("-n", "--lines", type=int, default=20, help="Number of lines")
    p_etail.add_argument("-f", "--follow", action="store_true", help="Follow event stream")
    p_etail.set_defaults(func=cmd_events_tail)

    # serve
    p_srv = subparsers.add_parser("serve", help="Launch FastAPI server with sane testing defaults")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8123)
    p_srv.add_argument("--no-mock-llm", action="store_true", help="Disable mock LLM mode")
    p_srv.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    if hasattr(args, "func"):
        sys.exit(args.func(args))


if __name__ == "__main__":
    main()
