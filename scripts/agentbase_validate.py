#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AgentBase Local Static Validator per official GreenNode AgentBase contract."""
import os
import sys
import re

def validate():
    results = []
    failed = 0
    warnings = 0

    # 1. Python version
    py_ver = sys.version_info
    ver_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    if py_ver >= (3, 10):
        results.append(f"[PASS] Python version: {ver_str}")
    else:
        results.append(f"[FAIL] Python version: {ver_str} (must be >= 3.10)")
        failed += 1

    # 2. Dockerfile EXPOSE 8080
    if os.path.exists("Dockerfile"):
        with open("Dockerfile", "r", encoding="utf-8") as f:
            df_content = f.read()
        if "EXPOSE 8080" in df_content:
            results.append("[PASS] Dockerfile exposes port 8080")
        else:
            results.append("[FAIL] Dockerfile does not contain 'EXPOSE 8080'")
            failed += 1
    else:
        results.append("[FAIL] Dockerfile not found")
        failed += 1

    # 3. Entrypoint file exists
    if os.path.exists("main.py"):
        results.append("[PASS] Entrypoint main.py exists")
    else:
        results.append("[FAIL] Entrypoint main.py not found")
        failed += 1

    # 4. Health endpoint handler
    health_found = False
    for fname in ["main.py", "web_copilot_app.py"]:
        if os.path.exists(fname):
            with open(fname, "r", encoding="utf-8") as f:
                content = f.read()
            if "/health" in content and ("200" in content or "status_code" in content):
                health_found = True
                break
    if health_found:
        results.append("[PASS] Health endpoint handler found (GET /health -> 200)")
    else:
        results.append("[FAIL] Health endpoint handler not found")
        failed += 1

    # 5. Invocation endpoint
    results.append("[INFO] Custom Agent HTTP endpoints exposed: GET /health, GET /, GET /api/case, POST /api/preview_legal_pdf, POST /api/preview_financial_pdf, POST /api/generate_docx")

    # 6. .dockerignore exclusions
    if os.path.exists(".dockerignore"):
        with open(".dockerignore", "r", encoding="utf-8") as f:
            di_content = f.read().splitlines()
        di_rules = [line.strip() for line in di_content if line.strip() and not line.startswith("#")]
        required_patterns = [".env", ".env.*", ".greennode.json", ".agentbase/", "*.credentials.json", "__pycache__", ".git"]
        missing = [p for p in required_patterns if p not in di_rules]
        if not missing:
            results.append("[PASS] .dockerignore excludes all required sensitive patterns")
        else:
            results.append(f"[WARN] .dockerignore missing: {missing}")
            warnings += 1
    else:
        results.append("[FAIL] .dockerignore not found")
        failed += 1

    # 7. requirements.txt
    if os.path.exists("requirements.txt"):
        with open("requirements.txt", "r", encoding="utf-8") as f:
            reqs = f.read()
        results.append(f"[PASS] requirements.txt exists with {len(reqs.strip().splitlines())} dependencies")
    else:
        results.append("[FAIL] requirements.txt not found")
        failed += 1

    print("\n" + "=" * 50)
    print("AgentBase Custom Agent Static Validation")
    print("=" * 50)
    for r in results:
        print(r)
    print("=" * 50)
    print(f"Summary: {len(results) - failed - warnings} passed, {failed} failed, {warnings} warnings")
    return failed == 0

if __name__ == "__main__":
    success = validate()
    sys.exit(0 if success else 1)
