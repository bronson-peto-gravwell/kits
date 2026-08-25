"""Classify a kitcheck finding by kit-utilities fixer coverage.

Vendored snapshot of `kit-utilities`' `bin/list-fixers` output, synced
2026-08-25 -- not a live query. `kit-utilities` is a local, unhosted lab
tool (`~/development/kit-program-lab/kit-utilities`), not reachable from
`gravwell/kits`' CI runner, so this has to be a periodically-refreshed
copy rather than computed at run time. Same discipline as the
`standards/*.pdf` copies: re-sync by re-running `bin/list-fixers` in
kit-utilities and updating FIXER_TIERS below whenever fixer coverage
changes there. A stale copy here fails safe -- a finding just falls
through to "manual" (no fixer known), never a false claim of coverage.

Deliberately does NOT try to annotate *which* manual findings are known
non-issues (e.g. a kit's intentional Duration tuning) -- that's a
developer judgment call informed by their own context, not something
this tool asserts. "Manual" means "no fixer exists," not "definitely
needs fixing."
"""

# Keyed on (check, section). A section of None matches any section for
# that check -- used by every check except check_naming_consistency,
# which emits two genuinely different finding types under one check id
# (see kitcheck.py's own finding() docstring) and needs the section to
# tell them apart, since only one of the two has full fixer coverage.
FIXER_TIERS = {
    ("check_macros_no_leading_pipe", None): ("mechanical", "bin/macrofix"),
    ("check_playbooks", None): ("mechanical", "bin/playbookgen --readme"),
    ("check_hashes_zeroed", None): ("mechanical", "bin/zerohash"),
    ("check_naming_consistency", "naming hygiene"): ("mechanical", "bin/namingfix --fix-whitespace"),
    ("check_detection_labels", None): ("partial", "bin/attcklabels"),
    ("check_resource_labels", None): ("partial", "bin/labelsuggest"),
    ("check_naming_consistency", "Standards §6"): ("partial", "bin/namingfix --fix-naming-prefix"),
    ("check_images", None): ("partial", "bin/artlink"),
}


def classify(finding):
    """Return (tier, fixer) for a single finding dict. tier is one of
    "mechanical", "partial", "manual". fixer is the bin/<tool> command,
    or None for "manual"."""
    key = (finding["check"], finding["section"])
    if key in FIXER_TIERS:
        return FIXER_TIERS[key]
    key = (finding["check"], None)
    if key in FIXER_TIERS:
        return FIXER_TIERS[key]
    return ("manual", None)


def tier_counts(findings):
    """Return {"mechanical": n, "partial": n, "manual": n} for a list of
    finding dicts."""
    counts = {"mechanical": 0, "partial": 0, "manual": 0}
    for f in findings:
        tier, _ = classify(f)
        counts[tier] += 1
    return counts
