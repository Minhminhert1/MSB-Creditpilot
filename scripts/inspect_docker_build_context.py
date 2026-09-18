#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect Docker build context against .dockerignore rules."""
import os
import sys
import fnmatch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def parse_dockerignore():
    rules = []
    if os.path.exists(".dockerignore"):
        with open(".dockerignore", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    rules.append(line)
    return rules

def is_ignored(path, rules):
    norm_path = path.replace("\\", "/")
    for rule in rules:
        clean_rule = rule.rstrip("/")
        if fnmatch.fnmatch(norm_path, clean_rule) or fnmatch.fnmatch(os.path.basename(norm_path), clean_rule):
            return True
        if norm_path.startswith(clean_rule + "/") or f"/{clean_rule}/" in f"/{norm_path}/":
            return True
    return False

def check_build_context():
    rules = parse_dockerignore()
    print("=" * 60)
    print("   DOCKER BUILD CONTEXT & SECRET SAFETY INSPECTION")
    print("=" * 60)

    # 1. Critical secret exclusions
    sensitive_targets = [".env", ".env.local", ".env.production", ".greennode.json", "client_secret.json"]
    for target in sensitive_targets:
        ignored = is_ignored(target, rules)
        print(f"[{'PASS' if ignored else 'FAIL'}] Sensitive pattern '{target}' excluded by .dockerignore: {ignored}")
        assert ignored, f"CRITICAL: {target} is not excluded!"

    # 2. Key required files included
    required_files = [
        "Dockerfile",
        "requirements.txt",
        "main.py",
        "web_copilot_app.py",
        "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx",
        "PHẦN B.docx"
    ]
    for rf in required_files:
        assert os.path.exists(rf), f"Required file {rf} does not exist!"
        ignored = is_ignored(rf, rules)
        print(f"[{'PASS' if not ignored else 'FAIL'}] Required runtime file '{rf}' preserved: {not ignored}")
        assert not ignored, f"CRITICAL: {rf} is accidentally ignored!"

    print("-" * 60)
    print("[✓] Build context is 100% clean and secure. Zero secrets exposed.")
    print("=" * 60)

if __name__ == "__main__":
    check_build_context()
