#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test local application HTTP endpoints outside Docker."""
import sys
import os
import time
import threading
import urllib.request
import json

# Ensure encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, ".")

from web_copilot_app import run_server, ThreadedHTTPServer, CopilotHTTPHandler, PORT, CASES_DB

def test_endpoints():
    test_port = 8555
    server_address = ('127.0.0.1', test_port)
    httpd = ThreadedHTTPServer(server_address, CopilotHTTPHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(1.0)

    base_url = f"http://127.0.0.1:{test_port}"
    print(f"Testing server at {base_url}...")

    # 1. GET /health
    req = urllib.request.Request(f"{base_url}/health")
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
        body = json.loads(resp.read().decode('utf-8'))
        print(f"[PASS] GET /health -> {status} (body: {body})")
        assert status == 200
        assert body.get("status") == "ok"
        assert body.get("app") == "msb-credit-proposal-copilot"

    # 2. GET /
    req = urllib.request.Request(f"{base_url}/")
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
        content_type = resp.headers.get("Content-Type")
        body_snippet = resp.read()[:100].decode('utf-8', errors='ignore')
        print(f"[PASS] GET / -> {status} (content-type: {content_type})")
        assert status == 200

    # 3. GET /api/case
    req = urllib.request.Request(f"{base_url}/api/case")
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
        case_data = json.loads(resp.read().decode('utf-8'))
        cid = case_data.get("id")
        cname = case_data.get("customer", {}).get("name")
        print(f"[PASS] GET /api/case -> {status} (active case: {cid} - {cname})")
        assert status == 200
        assert cid in CASES_DB

    # 4. GET /api/telemetry
    req = urllib.request.Request(f"{base_url}/api/telemetry")
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
        telem = json.loads(resp.read().decode('utf-8'))
        print(f"[PASS] GET /api/telemetry -> {status} (provider: {telem.get('provider')})")
        assert status == 200

    httpd.shutdown()
    print("\nAll local HTTP contract tests passed successfully!")

if __name__ == "__main__":
    test_endpoints()
