#!/usr/bin/env python3
"""
kitcheck.py - lightweight, read-only structural validator for Gravwell kits.

Deliberately narrow scope: structural/mechanical checks only, traced to
specific sections of the current kit standards docs (Kit Standards.pdf,
Peer Review Process.pdf, Kit Build Process.pdf — see
docs/kitcheck-standards-checklist.md in kit-management for the full
citation-by-citation mapping and the real-kit evidence behind each check).
Nothing here executes a query, installs a kit, or judges detection
quality — that's the separate, deeper "kit audit" skill's job. This is
the "does it pass the basic structural bar" pass, meant to run on every
PR without slowing anyone down.

Design principles (each one exists because of a bug found in a prior
tool used for this purpose):
  - Never writes to the kit directory. Read-only, full stop. No "helpful"
    auto-creation of missing files.
  - --input must point directly at the kit root. No parent-directory
    auto-discovery walk — that class of fallback previously produced a
    silent, empty, exit-0 "all clean" report when pointed at the wrong
    directory. Here, failing to find a MANIFEST is a loud, non-zero exit.
  - JSON output is the primary output, always produced the same way
    regardless of which display flags are passed — no display mode can
    silently suppress it.
  - This is a component, not a gate: findings never affect the exit
    code. Only a genuine "couldn't evaluate this input" condition does.
"""

import argparse
import inspect
import json
import re
import string
import sys
from pathlib import Path

KIT_ID_RE = re.compile(r"^io\.gravwell\.([A-Za-z0-9._-]+)$")
ZERO_HASH_RE = re.compile(r"^0+$")
EXPECTED_MAX_VERSION = {"Major": 5, "Minor": 99, "Point": 99}
EXPECTED_SCHEDULED_DURATION = -3600  # -1h, per Standards §21

# Standards § citation building blocks, named so a doc renumbering is a
# one-line edit here instead of a multi-site find/replace through every
# finding() call site. SEC holds bare section refs (not the "Standards "
# prefix) specifically so multi-section citations compose correctly —
# e.g. f"{STANDARDS} {SEC['7']} / {SEC['22']}" reads "Standards §7 / §22",
# not "Standards §7 / Standards §22". Composed per call site rather than
# one constant per combined string, since call sites mix sections +
# secondary-doc citations in different combinations.
STANDARDS = "Standards"
SEC = {
    "5.1": "§5.1",
    "5.2": "§5.2",
    "5.3": "§5.3",
    "6": "§6",
    "7": "§7",
    "8": "§8",
    "9": "§9",
    "10": "§10",
    "12": "§12",
    "14": "§14",
    "16": "§16",
    "21": "§21",
    "22": "§22",
}
PEER_REVIEW = "Peer Review"
PEER_REVIEW_GITHUB = "Peer Review:GitHub"
PEER_REVIEW_PLATFORM = "Peer Review:In-Platform"
BUILD_PROCESS_15A = "Build Process step 15a"


def finding(findings, severity, section, resource, message):
    # "check" is the calling check_* function's name, captured automatically
    # so every call site gets a stable identifier for free — no risk of it
    # drifting out of sync with a hand-maintained slug at ~30 call sites.
    # Lets a downstream fixer-dispatcher (e.g. kit-utilities) match on
    # finding["check"] instead of pattern-matching free-text `message`.
    # One known caveat: check_naming_consistency emits two conceptually
    # distinct findings (whitespace hygiene vs. dominant-prefix mismatch)
    # under this same id — distinguishable via `section` ("naming hygiene"
    # vs "Standards §6") if a consumer ever needs to dispatch them
    # differently.
    check = inspect.stack()[1].function
    findings.append(
        {"severity": severity, "section": section, "resource": resource,
         "message": message, "check": check}
    )


def load_manifest(root: Path):
    manifest_path = root / "MANIFEST"
    if not manifest_path.exists():
        return None, f"No MANIFEST found at {manifest_path}"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as e:
        return None, f"MANIFEST at {manifest_path} is not valid JSON: {e}"


def kitname_from_id(kit_id):
    if not isinstance(kit_id, str):
        return None
    m = KIT_ID_RE.match(kit_id.strip())
    return m.group(1) if m else None


# ---------------------------- MANIFEST checks ----------------------------

def check_manifest_core(manifest, findings):
    kit_id = manifest.get("ID")
    if not kitname_from_id(kit_id):
        finding(findings, "error", f"{STANDARDS} {SEC['5.1']}", "MANIFEST.ID",
                f"expected io.gravwell.<name>, found {kit_id!r}")

    name = manifest.get("Name")
    if not isinstance(name, str) or not name.strip():
        finding(findings, "error", f"{STANDARDS} {SEC['5.1']} / {PEER_REVIEW_GITHUB}", "MANIFEST.Name",
                "Name is missing or empty")

    desc = manifest.get("Desc")
    if not isinstance(desc, str) or not desc.strip():
        finding(findings, "warning", f"{STANDARDS} {SEC['5.1']} / {PEER_REVIEW_GITHUB}", "MANIFEST.Desc",
                "Desc is missing or empty")

    version = manifest.get("Version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        finding(findings, "error", f"{STANDARDS} {SEC['5.1']}", "MANIFEST.Version",
                f"expected a positive integer, found {version!r}")


def check_max_version(manifest, findings):
    mv = manifest.get("MaxVersion")
    if mv != EXPECTED_MAX_VERSION:
        finding(findings, "warning", f"{STANDARDS} {SEC['5.1']}", "MANIFEST.MaxVersion",
                f"expected {EXPECTED_MAX_VERSION} (5.99.99), found {mv!r} — "
                "not universally followed in existing kits, worth a look for new/changed ones")


def check_hashes_zeroed(manifest, findings):
    items = manifest.get("Items") or []
    for i, item in enumerate(items):
        h = item.get("Hash") if isinstance(item, dict) else None
        if h and not ZERO_HASH_RE.match(h):
            name = item.get("Name", f"Items[{i}]") if isinstance(item, dict) else f"Items[{i}]"
            finding(findings, "error", f"{BUILD_PROCESS_15A} / {PEER_REVIEW_GITHUB}",
                    f"MANIFEST.Items[{i}] ({name})",
                    "Hash is not zeroed — run `kitctl -zero-hash unpack` before committing")


def check_config_macro_tags(manifest, findings):
    for cm in (manifest.get("ConfigMacros") or []):
        if not isinstance(cm, dict):
            continue
        desc = (cm.get("Description") or "")
        if "tag" in desc.lower() and cm.get("Type") != "TAG":
            finding(findings, "error", f"{STANDARDS} {SEC['16']} / {PEER_REVIEW_GITHUB}",
                    f"MANIFEST.ConfigMacros ({cm.get('MacroName')})",
                    f"description mentions a tag but Type is {cm.get('Type')!r}, expected 'TAG'")


# ---------------------------- Filesystem checks ----------------------------

def check_build_assets(root, kitname, findings):
    if not (root / "BUILD").exists():
        finding(findings, "error", f"{STANDARDS} {SEC['16']} / {PEER_REVIEW_GITHUB}", "BUILD",
                "missing at kit root")
    if not (root / "README.md").exists():
        finding(findings, "error", f"{STANDARDS} {SEC['16']} / {SEC['5.3']} / {PEER_REVIEW_GITHUB}", "README.md",
                "missing at kit root")
    # The {kit}.metadata filename tracks the kit's directory/package name, not
    # necessarily MANIFEST.ID's suffix — confirmed via aws_guardduty, whose ID
    # is "io.gravwell.guardduty" but whose metadata file is
    # "aws_guardduty.metadata" (matching the directory, not the ID).
    meta_file = root / f"{root.name}.metadata"
    if not meta_file.exists():
        finding(findings, "error", f"{STANDARDS} {SEC['16']} / {PEER_REVIEW_GITHUB}",
                f"{root.name}.metadata", "missing at kit root")
    if kitname and kitname != root.name:
        finding(findings, "warning", f"{STANDARDS} {SEC['5.1']}", "MANIFEST.ID",
                f"ID suffix ({kitname!r}) differs from the directory name "
                f"({root.name!r}) — not necessarily wrong, but worth a second look")


def _find_image(root, stem):
    for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
        for candidate in (stem, stem.capitalize(), stem.upper(), stem.lower()):
            p = root / f"{candidate}{ext}"
            if p.exists():
                return p
    return None


def check_images(root, findings):
    if not _find_image(root, "cover"):
        finding(findings, "error", f"{STANDARDS} {SEC['5.2']} / {SEC['16']}", "cover image",
                "no cover.{png,jpg} found at kit root — note: must be a plain filename, "
                "not <kitname>-cover.*")
    if not _find_image(root, "banner"):
        finding(findings, "error", f"{STANDARDS} {SEC['5.2']} / {SEC['16']}", "banner image",
                "no banner.{png,jpg} found at kit root")
    icon_matches = list(root.glob("*[Ii]con*.png")) + list(root.glob("*[Ii]con*.jpg"))
    if not icon_matches:
        finding(findings, "warning", f"{STANDARDS} {SEC['5.2']}", "icon image",
                "no file matching *icon*.{png,jpg} found — filename convention for Icon "
                "isn't confirmed against a real sample, treat as best-effort")


def check_license(root, findings):
    license_dir = root / "license"
    files = [p for p in license_dir.glob("*") if p.is_file()] if license_dir.exists() else []
    if not files:
        finding(findings, "error", f"{STANDARDS} {SEC['14']} / {PEER_REVIEW}", "license/",
                "no license file found")
        return
    text = ""
    for p in files:
        try:
            text += p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    if "bsd" not in text.lower() or "redistribution and use in source and binary forms" not in text.lower():
        finding(findings, "warning", f"{STANDARDS} {SEC['14']} / {PEER_REVIEW}", "license/",
                "license file present but doesn't clearly contain BSD 2-Clause boilerplate")


def check_macros_no_leading_pipe(root, findings):
    macro_dir = root / "macro"
    if not macro_dir.exists():
        return
    for p in sorted(macro_dir.glob("*.expansion")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if text.lstrip().startswith("|"):
            finding(findings, "error", f"{STANDARDS} {SEC['9']}", f"macro/{p.name}",
                    "macro expansion starts with a preceding pipe")


def _load_json_safe(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def check_playbooks(root, findings):
    playbook_dir = root / "playbook"
    if not playbook_dir.exists():
        finding(findings, "warning", f"{STANDARDS} {SEC['12']}", "playbook/",
                "no playbook directory found — 2 required (Kit Overview, Copy of Readme)")
        return
    names = []
    for p in sorted(playbook_dir.glob("*.meta")):
        d = _load_json_safe(p)
        if isinstance(d, dict) and d.get("Name"):
            names.append(str(d["Name"]))
        else:
            names.append(p.stem)
    lowered = [n.lower() for n in names]
    if not any("overview" in n for n in lowered):
        finding(findings, "warning", f"{STANDARDS} {SEC['12']}", "playbook/",
                "no playbook name suggests 'Kit Overview' (heuristic match, not exact-name verified)")
    if not any("readme" in n for n in lowered):
        finding(findings, "warning", f"{STANDARDS} {SEC['12']}", "playbook/",
                "no playbook name suggests 'Copy of Readme' (heuristic match, not exact-name verified)")


def check_dashboards(root, findings):
    dashboard_dir = root / "dashboard"
    if not dashboard_dir.exists():
        finding(findings, "error", f"{STANDARDS} {SEC['8']}", "dashboard/",
                "no dashboard directory found — an Overview dashboard is required for every kit")
        return
    names = []
    for p in sorted(dashboard_dir.glob("*.meta")):
        d = _load_json_safe(p)
        names.append(str(d.get("Name", p.stem)) if isinstance(d, dict) else p.stem)
    if not any("overview" in n.lower() for n in names):
        finding(findings, "warning", f"{STANDARDS} {SEC['8']}", "dashboard/",
                "no dashboard name suggests 'Overview' (heuristic match — required for every kit)")


def check_actionables(root, findings):
    # Actionables live on disk as pivot/ — confirmed via real .meta structure:
    # top-level Name follows the general dash-style resource convention, but
    # Data.menuLabel and Data.actions[].name are what actually correspond to
    # the Actionable-specific requirements in Standards §10 (proper menu
    # label, descriptive/clear action names) and Peer Review's "Names of
    # actionables are unique to the kit."
    pivot_dir = root / "pivot"
    if not pivot_dir.exists():
        return  # not every kit has actionables

    menu_labels = []  # (label, resource) for the uniqueness pass below
    for p in sorted(pivot_dir.glob("*.meta")):
        d = _load_json_safe(p)
        if not isinstance(d, dict):
            continue
        name = d.get("Name", p.stem)
        data = d.get("Data") or {}
        menu_label = data.get("menuLabel")
        if not isinstance(menu_label, str) or not menu_label.strip():
            finding(findings, "error", f"{STANDARDS} {SEC['10']}", f"pivot/{p.name} ({name})",
                    "Data.menuLabel is missing or empty")
        elif menu_label.strip():
            menu_labels.append((menu_label.strip(), f"pivot/{p.name} ({name})"))
        for i, action in enumerate(data.get("actions") or []):
            if not isinstance(action, dict):
                continue
            action_name = action.get("name")
            if not isinstance(action_name, str) or not action_name.strip():
                finding(findings, "error", f"{STANDARDS} {SEC['10']}", f"pivot/{p.name} ({name})",
                        f"actions[{i}].name is missing or empty")

    # Uniqueness check only exercised against sparse real data (most sampled
    # kits have empty menuLabels, already flagged above) — logic is simple
    # enough to trust, but flagging that a genuine duplicate hasn't been
    # observed in practice yet.
    from collections import Counter
    counts = Counter(label for label, _ in menu_labels)
    for label, resource in menu_labels:
        if counts[label] > 1:
            finding(findings, "warning", PEER_REVIEW_PLATFORM, resource,
                    f"menuLabel {label!r} is not unique within this kit")


def check_resource_labels(root, findings):
    # Standards §7: dashboards/actionables(pivot)/macros/templates should
    # carry "EVs used" labels; detections need ATT&CK + metadata labels.
    # Confirmed real field: a "Labels" list/null on all four resource types.
    # Kept as warning, not error — confirmed inconsistently applied even in
    # otherwise-clean sample kits (aws_cloudtrail's dashboards/pivots/
    # templates all have Labels: null), so this isn't a reliable "must" in
    # current practice despite being documented.
    for d in ("dashboard", "pivot", "macro", "template"):
        dir_path = root / d
        if not dir_path.exists():
            continue
        for p in sorted(dir_path.glob("*.meta")):
            data = _load_json_safe(p)
            if not isinstance(data, dict):
                continue
            name = data.get("Name", p.stem)
            labels = data.get("Labels")
            if not labels:
                finding(findings, "warning", f"{STANDARDS} {SEC['7']}", f"{d}/{p.name} ({name})",
                        "no Labels set (EVs-used labeling convention)")


ATTCK_RE = re.compile(r"^T\d{4}(\.\d{3})?$")


def _scheduled_is_detection(root, d):
    # Standards §21 (via §18.1) and §7/§22's ATT&CK-labeling requirement
    # only bind genuine detection-driven scheduled searches. scheduled/
    # also holds ScheduledType "flow"/"script" aggregation/data-fetch jobs
    # that are legitimately meant to ship enabled — confirmed via
    # barracuda's 6 "flow" aggregates, all Disabled: false by design — and
    # ScheduledType "search" jobs with no real SearchReference, i.e.
    # aggregation work in disguise — confirmed via o365's "Historical User
    # Info" (search type, SearchReference null, 30-day lookback, also
    # Disabled: false). Scope to jobs that are actually a detection: type
    # "search" AND a SearchReference that resolves to a real searchlibrary
    # entry.
    if d.get("ScheduledType") != "search":
        return False
    search_ref = d.get("SearchReference")
    if not isinstance(search_ref, str) or not search_ref:
        return False
    return (root / "searchlibrary" / f"{search_ref}.meta").exists()


def check_detection_labels(root, findings):
    # Standards §7's Detections entry: ATT&CK Techniques + metadata labels.
    # Confirmed real shape via azure's scheduled search .meta: a Labels
    # array mixing categorical tags with literal ATT&CK IDs (e.g. T1562.004).
    scheduled_dir = root / "scheduled"
    if not scheduled_dir.exists():
        return
    for p in sorted(scheduled_dir.glob("*.meta")):
        d = _load_json_safe(p)
        if not isinstance(d, dict):
            continue
        if not _scheduled_is_detection(root, d):
            continue
        name = d.get("Name", p.stem)
        labels = d.get("Labels") or []
        if not any(isinstance(l, str) and ATTCK_RE.match(l) for l in labels):
            finding(findings, "warning", f"{STANDARDS} {SEC['7']} / {SEC['22']}", f"scheduled/{p.name} ({name})",
                    "no label matches an ATT&CK technique ID pattern (T####[.###])")


def check_macro_documentation(root, findings):
    # Standards §9 asks for Purpose/Parameters/Referencing resources/
    # Modification safety notes. The real macro .meta shape only exposes a
    # single Description field — no structured Parameters/safety-notes
    # fields exist to check. This is a weak proxy (non-empty description),
    # not real compliance verification of the full §9 documentation ask.
    macro_dir = root / "macro"
    if not macro_dir.exists():
        return
    for p in sorted(macro_dir.glob("*.meta")):
        d = _load_json_safe(p)
        if not isinstance(d, dict):
            continue
        name = d.get("Name", p.stem)
        desc = d.get("Description")
        if not isinstance(desc, str) or not desc.strip():
            finding(findings, "warning", f"{STANDARDS} {SEC['9']}", f"macro/{p.name} ({name})",
                    "Description is missing or empty (weak proxy for the full "
                    "purpose/parameters/safety-notes documentation ask)")


def check_scheduled_searches(root, findings):
    scheduled_dir = root / "scheduled"
    if not scheduled_dir.exists():
        return  # Part III only binds when a kit includes detections
    for p in sorted(scheduled_dir.glob("*.meta")):
        d = _load_json_safe(p)
        if not isinstance(d, dict):
            continue
        if not _scheduled_is_detection(root, d):
            continue
        name = d.get("Name", p.stem)
        ddr = d.get("DefaultDeploymentRules") or {}
        if ddr.get("Disabled") is not True:
            finding(findings, "error", f"{STANDARDS} {SEC['21']} / {PEER_REVIEW}", f"scheduled/{p.name} ({name})",
                    "DefaultDeploymentRules.Disabled is not true — scheduled searches must ship disabled")
        duration = d.get("Duration")
        if duration != EXPECTED_SCHEDULED_DURATION:
            finding(findings, "warning", f"{STANDARDS} {SEC['21']}", f"scheduled/{p.name} ({name})",
                    f"Duration is {duration!r}, expected {EXPECTED_SCHEDULED_DURATION} (1h)")


def _resource_names(root):
    """Collect (path, name) pairs from directories that carry human-readable
    resource names, for the naming-consistency check (§6)."""
    out = []
    for d in ("dashboard", "searchlibrary", "scheduled", "pivot"):
        dir_path = root / d
        if not dir_path.exists():
            continue
        for p in sorted(dir_path.glob("*.meta")):
            data = _load_json_safe(p)
            if isinstance(data, dict) and isinstance(data.get("Name"), str) and data["Name"].strip():
                out.append((f"{d}/{p.name}", data["Name"]))
    return out


def _prefix_of(name: str) -> str:
    # Always just the first word, regardless of whether a " - " separator is
    # present. An earlier version branched on dash-presence (full phrase
    # before " - " if present, else first word) and that inconsistency
    # produced false positives within a single kit — e.g. "Auditd Service
    # Reload - Linux" (dash-branch: prefix "Auditd Service Reload") vs
    # "Auditd Command Execution" (no-dash branch: prefix "Auditd") were
    # flagged as mismatched despite both genuinely being Auditd resources.
    # Trailing punctuation is stripped too — real kits (syslog, sysmon)
    # mix "Syslog: <thing>" (searchlibrary) with "Syslog <thing>"
    # (dashboard/pivot), both already leading with the kit name; without
    # this the trailing colon alone split one dominant prefix into two.
    return name.strip().split(" ", 1)[0].strip().rstrip(string.punctuation)


def check_naming_consistency(root, findings):
    resources = _resource_names(root)

    # whitespace hygiene — cheap, deterministic, found a real example in the wild
    for path, name in resources:
        if name != name.strip():
            finding(findings, "warning", "naming hygiene", path,
                    f"resource name has leading/trailing whitespace: {name!r}")

    if len(resources) < 3:
        return  # not enough samples to establish a dominant prefix meaningfully

    from collections import Counter
    prefixes = Counter(_prefix_of(name) for _, name in resources)
    dominant, dominant_count = prefixes.most_common(1)[0]
    if dominant_count / len(resources) <= 0.5:
        return  # no clear dominant convention in this kit, don't guess

    for path, name in resources:
        if _prefix_of(name) != dominant:
            finding(findings, "warning", f"{STANDARDS} {SEC['6']}", path,
                    f"name {name!r} doesn't share this kit's dominant naming prefix "
                    f"({dominant!r}) — possible leftover from another kit or inconsistent naming")


def check_readme_content(root, findings):
    readme = root / "README.md"
    if not readme.exists():
        return  # already flagged by check_build_assets
    try:
        text = readme.read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return
    if "integration guide" not in text and "docs.gravwell.io" not in text:
        finding(findings, "warning", f"{STANDARDS} {SEC['5.3']}", "README.md",
                "no mention of an integration guide link")
    if "changelog" not in text:
        finding(findings, "warning", f"{STANDARDS} {SEC['5.3']}", "README.md",
                "no Changelog section found")


# ---------------------------- Orchestration ----------------------------

def _verify_all_checks_registered():
    # Catches the exact mistake a standards-doc revision pass is most
    # likely to introduce: adding a new check_* function and forgetting
    # to call it from run_all_checks(). That mistake fails silently
    # otherwise — no crash, no warning, the check just never runs. This
    # is a textual check against run_all_checks()'s own source rather
    # than a separate registry, so there's nothing extra to keep in
    # sync — the call list stays the single source of truth, this just
    # verifies every check_* function is actually mentioned in it.
    module = sys.modules[__name__]
    source = inspect.getsource(run_all_checks)
    all_check_fns = sorted(
        name for name, obj in inspect.getmembers(module, inspect.isfunction)
        if name.startswith("check_")
    )
    missing = [name for name in all_check_fns if name not in source]
    if missing:
        raise RuntimeError(
            "kitcheck.py internal error: check function(s) defined but never "
            f"called from run_all_checks(): {', '.join(missing)}. Add the call, "
            "or remove the function if it's genuinely unused."
        )


def run_all_checks(root: Path):
    manifest, err = load_manifest(root)
    if err:
        return None, err

    findings = []
    check_manifest_core(manifest, findings)
    check_max_version(manifest, findings)
    check_hashes_zeroed(manifest, findings)
    check_config_macro_tags(manifest, findings)

    kitname = kitname_from_id(manifest.get("ID"))
    check_build_assets(root, kitname, findings)
    check_images(root, findings)
    check_license(root, findings)
    check_macros_no_leading_pipe(root, findings)
    check_macro_documentation(root, findings)
    check_playbooks(root, findings)
    check_dashboards(root, findings)
    check_actionables(root, findings)
    check_resource_labels(root, findings)
    check_detection_labels(root, findings)
    check_scheduled_searches(root, findings)
    check_naming_consistency(root, findings)
    check_readme_content(root, findings)

    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")

    # "Meets initial-release threshold" is defined as zero error-severity
    # findings. Warnings don't count against it — several warning-level
    # checks are heuristics or document requirements that real released
    # kits don't universally follow (see docs/kitcheck-standards-checklist.md),
    # so treating them as blocking would be a false bar, not a true one.
    result = {
        "kit": {
            "directory": root.name,
            "id": manifest.get("ID"),
            "name": manifest.get("Name"),
            "version": manifest.get("Version"),
        },
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "total": len(findings),
            "meets_initial_threshold": errors == 0,
        },
        "findings": findings,
    }
    return result, None


def render_text(result) -> str:
    lines = []
    kit = result["kit"]
    verdict = "PASSES" if result["summary"]["meets_initial_threshold"] else "NEEDS ATTENTION"
    lines.append(f"kitcheck: {kit.get('name') or kit.get('directory')} ({kit.get('id')}) — {verdict}")
    lines.append(f"  {result['summary']['errors']} error(s), {result['summary']['warnings']} warning(s)")
    if not result["findings"]:
        lines.append("  no findings")
        return "\n".join(lines)
    for f in result["findings"]:
        marker = "ERROR" if f["severity"] == "error" else "warn "
        lines.append(f"  [{marker}] {f['resource']} — {f['message']} ({f['section']})")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Lightweight, read-only structural check for a Gravwell kit directory."
    )
    parser.add_argument("--input", "-i", required=True,
                         help="path directly to the kit directory (containing MANIFEST, BUILD, "
                              "resource folders) — not a parent directory")
    parser.add_argument("--output", "-o", help="also write the JSON result to this file")
    parser.add_argument("--format", choices=["json", "text", "both"], default="json",
                         help="stdout format (default: json). JSON is always well-formed and "
                              "complete regardless of this choice.")
    args = parser.parse_args()

    root = Path(args.input).resolve()
    if not root.exists() or not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    result, err = run_all_checks(root)
    if err:
        print(f"error: {err}", file=sys.stderr)
        print(f"error: {root} does not look like a kit directory. Point --input directly "
              "at the kit (the directory containing MANIFEST, BUILD, and resource folders), "
              "not a parent directory — this tool does not auto-discover a kit root.",
              file=sys.stderr)
        sys.exit(1)

    if args.format in ("json", "both"):
        print(json.dumps(result, indent=2))
    if args.format in ("text", "both"):
        print(render_text(result))

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    # Findings never affect the exit code — this is a component, not a gate.
    # Only "couldn't evaluate the input at all" (handled above) is a failure.
    sys.exit(0)


_verify_all_checks_registered()  # runs on import, not just direct execution

if __name__ == "__main__":
    main()
