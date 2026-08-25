#!/usr/bin/env python3
"""Render a kit's cover/banner/icon images inline in the PR Job Summary.

GitHub's file viewer shows a symlink's target path as text, it doesn't
follow it to render an image -- confirmed real, not hypothetical, the
moment cover.png/banner.png became symlinks into file/*.contents per the
2026-08-25 standards revision (§16). This resolves the symlink (or reads
the raw file, for a kit that hasn't adopted the convention yet) and
embeds the actual bytes as a base64 data URI, so a reviewer sees the
resolved image without leaving the PR.

Sniffs the actual image format from file content (PNG/JPEG magic bytes)
rather than trusting the .png/.jpg filename before choosing the data
URI's MIME type -- confirmed necessary against real fleet data: 27 of 98
sampled real Cover/Banner/Icon file/*.contents entries are actually JPEG
despite the filename convention (including juniper's), so declaring
image/png for JPEG bytes would be asserting false metadata, not a
hypothetical edge case. Mirrors kitcheck.py's own _sniff_image_format /
_find_image logic (duplicated, not imported -- kept small and dependency-free
on purpose, since this only ever needs to run from the workflow, not from
kitcheck.py itself).

Usage: kitcheck_render_images.py <kit-dir>
"""
import base64
import os
import sys
from pathlib import Path

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def _sniff_format(data):
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_JPEG_MAGIC):
        return "jpeg"
    return None


def _find_image(root, stem):
    for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
        for candidate in (stem, stem.capitalize(), stem.upper(), stem.lower()):
            p = root / f"{candidate}{ext}"
            if p.exists():
                return p
    return None


def main():
    root = Path(sys.argv[1])

    images = [("cover", _find_image(root, "cover")), ("banner", _find_image(root, "banner"))]
    icon_matches = list(root.glob("*[Ii]con*.png")) + list(root.glob("*[Ii]con*.jpg"))
    images.append(("icon", icon_matches[0] if icon_matches else None))

    lines = []
    for label, path in images:
        if path is None:
            continue

        is_link = path.is_symlink()
        link_note = ""
        if is_link:
            target = os.readlink(path)
            link_note = f" — symlink → `{target}`"
        else:
            link_note = " — raw file, not yet symlinked (§16)"

        try:
            data = path.read_bytes()  # follows the symlink automatically
        except OSError as e:
            lines.append(f"**{label}** (`{path.name}`){link_note}  ")
            lines.append(f"*couldn't read: {e}*")
            lines.append("")
            continue

        fmt = _sniff_format(data)
        if fmt is None:
            lines.append(f"**{label}** (`{path.name}`){link_note}  ")
            lines.append(f"*unrecognized image format, can't render (first bytes: {data[:8].hex()})*")
            lines.append("")
            continue

        fmt_note = "" if fmt == "png" else f" — **{fmt.upper()}**, not PNG (§5.2)"
        b64 = base64.b64encode(data).decode("ascii")
        lines.append(f"**{label}** (`{path.name}`){link_note}{fmt_note}  ")
        lines.append(f'<img src="data:image/{fmt};base64,{b64}" alt="{label}" height="120">')
        lines.append("")

    if lines:
        print("<details><summary>🖼️ Cover / Banner / Icon preview</summary>")
        print()
        print("\n".join(lines))
        print("</details>")
        print()


if __name__ == "__main__":
    main()
