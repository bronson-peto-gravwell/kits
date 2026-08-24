#!/usr/bin/env python3
"""Print one markdown table row summarizing a kitcheck.py JSON result.
Used by kitcheck-report.yml — split out as its own script rather than
embedding this logic inline in the workflow YAML, since a multi-line
Python snippet nested inside a bash command inside a YAML block scalar
is exactly the kind of triple-nested quoting/indentation that's easy to
get subtly wrong (and easy to misdiagnose when it is wrong).

Usage: kitcheck_verdict.py <kit-name> <result.json>
"""
import json
import sys

kit_name = sys.argv[1]
result_path = sys.argv[2]

with open(result_path, encoding="utf-8") as f:
    result = json.load(f)

s = result["summary"]
mark = "✅ PASSES" if s["meets_initial_threshold"] else "❌ NEEDS ATTENTION"
print(f"| `{kit_name}` | {mark} | {s['errors']} | {s['warnings']} |")
