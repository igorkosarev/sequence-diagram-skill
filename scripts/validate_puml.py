#!/usr/bin/env python3
"""
Validate a PlantUML sequence diagram *without* needing Java.

Catches the two failure modes that break generated PlantUML most often:
  1. Unbalanced blocks  — alt/opt/loop/par/critical/break/group need `end`;
                          box needs `end box`; note-block needs `end note`.
  2. Unbalanced activation — orphan activate / deactivate.

Also sanity-checks @startuml/@enduml.

Usage:
    python3 validate_puml.py diagram.puml            # lint only
    python3 validate_puml.py diagram.puml --render   # lint + render to SVG (needs Java)

Exit code 0 = clean, 1 = problems found.
"""
import argparse
import os
import re
import subprocess
import sys
import urllib.request

CTRL_BLOCKS = ("alt", "opt", "loop", "par", "critical", "break", "group")
# keyword possibly followed directly by #color (e.g. alt#Gold) -> \b handles it
CTRL_RE = re.compile(r"^(" + "|".join(CTRL_BLOCKS) + r")\b")
BOX_OPEN_RE = re.compile(r"^box\b")
NOTE_OPEN_RE = re.compile(r"^(note|hnote|rnote)\b")
ACT_RE = re.compile(r"^activate\s+(\S+)")
DEACT_RE = re.compile(r"^deactivate\s+(\S+)")


def strip_comments(lines):
    """Yield (lineno, text) with '-comments and /'...'/ block comments removed."""
    in_block_comment = False
    for i, raw in enumerate(lines, 1):
        line = raw
        if in_block_comment:
            end = line.find("'/")
            if end == -1:
                continue
            line = line[end + 2:]
            in_block_comment = False
        # remove inline /' ... '/ pairs on the same line
        while "/'" in line:
            start = line.find("/'")
            end = line.find("'/", start + 2)
            if end == -1:
                line = line[:start]
                in_block_comment = True
                break
            line = line[:start] + line[end + 2:]
        stripped = line.strip()
        if stripped.startswith("'"):
            continue
        yield i, stripped


def lint(path):
    with open(path, encoding="utf-8") as f:
        raw_lines = f.readlines()

    errors, warnings = [], []
    stack = []                 # (kind, lineno, label) for box/ctrl structure
    in_note = False
    act_depth = {}             # participant -> current activation depth
    saw_start = saw_end = False

    # Activation is branch-aware: alt/else branches are alternatives, not
    # sequential, so a deactivate in each branch is correct. For every control
    # block we snapshot the activation state at the opener; on `else` we record
    # the finished branch and reset to the snapshot; on `end` we merge branches.
    scope_stack = []           # list of {open, branches:[dict], line}

    def snap():
        return dict(act_depth)

    for lineno, text in strip_comments(raw_lines):
        if not text:
            continue

        if in_note:                       # skip note-block bodies entirely
            if text == "end note":
                in_note = False
            continue

        low = text.lower()

        if low.startswith("@startuml"):
            saw_start = True
            continue
        if low.startswith("@enduml"):
            saw_end = True
            continue

        if NOTE_OPEN_RE.match(low):        # block note has no ':'
            if ":" not in text:
                in_note = True
            continue

        # ---- closers ----
        if low == "end box":
            if stack and stack[-1][0] == "box":
                stack.pop()
            else:
                errors.append(f"line {lineno}: `end box` with no open `box`")
            continue
        if low == "end":
            if stack and stack[-1][0] == "ctrl":
                stack.pop()
                sc = scope_stack.pop()
                sc["branches"].append(snap())          # close final branch
                names = set().union(*[b.keys() for b in sc["branches"]])
                merged = {}
                for n in names:
                    vals = {b.get(n, 0) for b in sc["branches"]}
                    if len(vals) > 1:
                        warnings.append(
                            f"line {lineno}: branches of block opened at line "
                            f"{sc['line']} leave `{n}` in different activation "
                            f"states {sorted(vals)}")
                    merged[n] = max(vals)               # carry a consistent state
                # anti-pattern: a participant that was already active when the
                # block opened gets deactivated inside it. If it was activated by
                # the request this alt branches on, its activation should stay
                # open across the whole block and be closed once AFTER `end` —
                # closing it inside branches chops the bar and PlantUML can draw
                # a stray/floating activation stub.
                for n, opened in sc["open"].items():
                    if merged.get(n, 0) < opened:
                        warnings.append(
                            f"line {lineno}: `{n}` was active when the block "
                            f"opened (line {sc['line']}) but is deactivated "
                            f"inside it. If `{n}` was activated by the request "
                            f"this block branches on, move its `deactivate` to "
                            f"just after this `end` (one continuous bar).")
                act_depth.clear(); act_depth.update(merged)
            elif stack and stack[-1][0] == "box":
                errors.append(
                    f"line {lineno}: `end` but the open block is a `box` "
                    f"(opened line {stack[-1][1]}) — use `end box`")
            else:
                errors.append(f"line {lineno}: `end` with no open block")
            continue

        # ---- openers ----
        if BOX_OPEN_RE.match(low):
            stack.append(("box", lineno, text))
            continue
        m = CTRL_RE.match(low)
        if m:
            stack.append(("ctrl", lineno, m.group(1)))
            scope_stack.append({"open": snap(), "branches": [], "line": lineno})
            continue

        # ---- else / elseif : end current branch, reset to opener state ----
        if low.startswith("else") or low.startswith("elseif"):
            if scope_stack:
                sc = scope_stack[-1]
                sc["branches"].append(snap())
                act_depth.clear(); act_depth.update(sc["open"])
            else:
                warnings.append(f"line {lineno}: `else` outside any block")
            continue

        # ---- activation ----
        m = ACT_RE.match(low)
        if m:
            name = m.group(1)
            act_depth[name] = act_depth.get(name, 0) + 1
            continue
        m = DEACT_RE.match(low)
        if m:
            name = m.group(1)
            if act_depth.get(name, 0) <= 0:
                warnings.append(
                    f"line {lineno}: `deactivate {name}` but {name} is not active")
            else:
                act_depth[name] -= 1
            continue

        if "++" in text:
            warnings.append(
                f"line {lineno}: `++` shorthand used — linter can't verify its "
                f"balance; explicit activate/deactivate is easier to check")

    # ---- end-of-file checks ----
    if not saw_start:
        errors.append("missing @startuml")
    if not saw_end:
        errors.append("missing @enduml")
    for kind, ln, label in stack:
        opener = "box" if kind == "box" else label
        closer = "end box" if kind == "box" else "end"
        errors.append(f"line {ln}: `{opener}` never closed (needs `{closer}`)")
    for name, depth in act_depth.items():
        if depth > 0:
            warnings.append(
                f"`{name}`: {depth} `activate` without matching `deactivate` "
                f"(PlantUML auto-closes it, but it's usually an oversight)")

    return errors, warnings


def find_or_get_jar():
    cache = os.path.expanduser("~/.cache/plantuml")
    os.makedirs(cache, exist_ok=True)
    existing = [f for f in os.listdir(cache) if f.endswith(".jar")]
    if existing:
        return os.path.join(cache, existing[0])
    import json
    api = "https://api.github.com/repos/plantuml/plantuml/releases/latest"
    with urllib.request.urlopen(api, timeout=30) as r:
        data = json.load(r)
    asset = None
    for a in data.get("assets", []):
        n = a["name"]
        if re.match(r"^plantuml-\d[\d.]*\.jar$", n):  # plain versioned jar
            asset = a
            break
    if not asset:  # fall back to any .jar that isn't sources/javadoc
        for a in data.get("assets", []):
            n = a["name"]
            if n.endswith(".jar") and "source" not in n and "javadoc" not in n:
                asset = a
                break
    if not asset:
        raise RuntimeError("could not locate a plantuml jar in the latest release")
    dest = os.path.join(cache, asset["name"])
    print(f"  downloading {asset['name']} ...")
    urllib.request.urlretrieve(asset["browser_download_url"], dest)
    return dest


def render(path):
    if subprocess.run(["which", "java"], capture_output=True).returncode != 0:
        print("  Java not found — skipping render. Install a JRE to enable it.")
        return
    try:
        jar = find_or_get_jar()
    except Exception as e:
        print(f"  Could not obtain plantuml.jar: {e}")
        return
    out = subprocess.run(
        ["java", "-jar", jar, "-tsvg", path],
        capture_output=True, text=True)
    svg = os.path.splitext(path)[0] + ".svg"
    if out.returncode == 0 and os.path.exists(svg):
        print(f"  Rendered: {svg}")
    else:
        print("  Render failed:")
        print("  " + (out.stderr or out.stdout).strip().replace("\n", "\n  "))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--render", action="store_true",
                    help="also render to SVG (needs Java; fetches plantuml.jar)")
    args = ap.parse_args()

    errors, warnings = lint(args.file)

    for w in warnings:
        print(f"  ⚠ {w}")
    for e in errors:
        print(f"  ✗ {e}")

    if not errors and not warnings:
        print("  ✓ structure OK")
    elif not errors:
        print(f"  ✓ no structural errors ({len(warnings)} warning(s))")

    if args.render:
        render(args.file)

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
