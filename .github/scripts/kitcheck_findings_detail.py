#!/usr/bin/env python3
"""Print the tiered, collapsible markdown detail section for one kit's
kitcheck.py JSON result. Used by kitcheck-report.yml in place of dumping
--format text output into a flat, non-wrapping code fence — split out as
its own script for the same reason as kitcheck_verdict.py (avoid
multi-line Python nested inside bash nested inside YAML).

Groups findings by kit-utilities fixer tier (mechanical / partial /
manual — see kitcheck_fixer_tiers.py) rather than the flat order
kitcheck.py itself emits them in, so a reviewer's first read answers
"how much of this needs a human" before "what exactly is wrong."

Usage: kitcheck_findings_detail.py <kit-name> <result.json>
"""
import json
import sys

from kitcheck_fixer_tiers import classify

kit_name = sys.argv[1]
result_path = sys.argv[2]

with open(result_path, encoding="utf-8") as f:
    result = json.load(f)

kit = result["kit"]
s = result["summary"]
verdict = "PASSES" if s["meets_initial_threshold"] else "NEEDS ATTENTION"

print(f"kitcheck: {kit.get('name') or kit.get('directory')} ({kit.get('id')}) — {verdict}  ")
print(f"{s['errors']} error(s), {s['warnings']} warning(s)")
print()

if not result["findings"]:
    print("no findings")
    print()
    sys.exit(0)

TIER_LABELS = {
    "mechanical": "🔧 Mechanical fix available",
    "partial": "🟡 Partial fixer coverage — some covered, some need review",
    "manual": "🔴 No fixer — manual review",
}

# Bucket findings by tier, then within each tier by (fixer, check) so
# multiple findings from the same tool/check sit together instead of
# interleaved.
buckets = {"mechanical": {}, "partial": {}, "manual": {}}
for finding in result["findings"]:
    tier, fixer = classify(finding)
    key = (fixer, finding["check"])
    buckets[tier].setdefault(key, []).append(finding)

counts = {tier: sum(len(v) for v in groups.values()) for tier, groups in buckets.items()}
print(f"**{counts['mechanical']} mechanical** · **{counts['partial']} partial** · "
      f"**{counts['manual']} manual** (of {s['total']} total)")
print()

for tier in ("mechanical", "partial", "manual"):
    groups = buckets[tier]
    if not groups:
        continue
    print(f"<details><summary>{TIER_LABELS[tier]} ({counts[tier]})</summary>")
    print()
    for (fixer, check), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        heading = f"**`{fixer}`**" if fixer else "**no fixer**"
        print(f"{heading} — `{check}` ({len(items)})")
        # Errors first within each group, so a real standards violation
        # doesn't sit behind a pile of warnings from the same check.
        for finding in sorted(items, key=lambda x: x["severity"] != "error"):
            marker = "**ERROR**" if finding["severity"] == "error" else "warn"
            print(f"- {marker} `{finding['resource']}` — {finding['message']} ({finding['section']})")
        print()
    print("</details>")
    print()
