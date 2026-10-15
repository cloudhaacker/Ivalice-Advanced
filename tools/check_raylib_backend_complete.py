#!/usr/bin/env python3
"""Completeness check: every WindowBackend virtual must be overridden by
RaylibBackend.

Why this exists
---------------
The `override` keyword in raylib_backend.h only catches *signature drift* — a
base virtual whose signature changed, or a .cpp definition with no declaration.
It does NOT catch a brand-new virtual added to WindowBackend that RaylibBackend
silently fails to override (it just inherits the default). Member-pointer
comparison cannot detect this either: `&Derived::f != &Base::f` folds to false
even for a genuine override.

raylib_backend_test.cpp catches this for methods with observable results, but a
void method with no observable effect slips through. This closes that gap at
review / CI time.

Parsing notes
-------------
Both scans use balanced-paren argument extraction. A naive `\\([^)]*\\)` regex
silently drops `set_host_overlay(void (*overlay)(HostOverlay*))` because the
function-pointer argument contains its own parentheses.

Usage:  python3 tools/check_raylib_backend_complete.py
Exit 0 when complete, 1 when a virtual is missing or mismatched.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IFACE = ROOT / "gbarecompx/src/runtime/window_backend.h"
DEFAULT_BACKEND = ROOT / "gbarecompx/src/runtime/raylib_backend.h"
DEFAULT_SDL = ROOT / "gbarecompx/src/runtime/host_window.cpp"


TYPE_WORDS = {
    "void", "bool", "char", "short", "int", "long", "float", "double",
    "signed", "unsigned", "const", "volatile", "size_t", "auto",
}


def _strip_param_name(param: str) -> str:
    """Drop a trailing parameter NAME, which is not part of the signature.

    `float low` and `float low_frequency` are the same parameter type. Also
    drops leading `::` global-scope qualifiers.
    """
    param = param.strip()
    param = re.sub(r"^::", "", param)
    m = re.match(r"^(.*?)([A-Za-z_]\w*)$", param, re.DOTALL)
    if not m:
        return param
    prefix, last = m.group(1), m.group(2)
    if not prefix.strip():
        return param
    if last in TYPE_WORDS:
        return param                      # e.g. "unsigned long"
    if prefix.rstrip().endswith(("*", "&", "&&")):
        return prefix.rstrip()             # e.g. "const char* title"
    # `int base_w` / `float low`: the token before the name is the type itself.
    prev = prefix.rstrip().split()[-1] if prefix.strip() else ""
    if prev in {"int", "char", "short", "long", "float", "double", "bool",
                "void", "signed", "unsigned", "size_t"} or re.match(
                    r"^[A-Za-z_]\w*_t$", prev
                ):
        return prefix.rstrip()
    return param


def norm(text: str) -> str:
    """Canonicalize an argument list for signature comparison.

    Normalizes, in order: pointer/reference spacing (`int* w` == `int *w`), the
    `std::` qualifier (`std::uint8_t` == `uint8_t`), global-scope `::`, and
    parameter NAMES (not part of a C++ signature).
    """
    text = re.sub(r"\s*([*&])\s*", r"\1", text)
    text = text.replace("std::", "")
    parts, depth, cur = [], 0, ""
    for ch in text:                        # split on top-level commas only
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    return ",".join(_strip_param_name(p) for p in parts)


def balanced_args(text: str, open_paren: int) -> tuple[str, int] | None:
    """Return (normalized args, index just past the matching ')')."""
    depth = 0
    i = open_paren
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return norm(text[open_paren + 1:i]), i + 1
        i += 1
    return None


def interface_methods(text: str) -> dict[tuple[str, str], bool]:
    """Map (name, args) -> is_const for every `virtual` member function."""
    out: dict[tuple[str, str], bool] = {}
    for m in re.finditer(r"\bvirtual\b[^;{]*?\b(\w+)\s*\(", text):
        got = balanced_args(text, m.end() - 1)
        if got is None:
            continue
        args, after = got
        # A virtual *data* member (none today) would not be followed by `{`.
        if "{" not in text[after:after + 24]:
            continue
        rest = text[after:after + 24]
        out.setdefault((m.group(1), args), bool(re.match(r"\s*const\b", rest)))
    return out


def struct_body(text: str, struct_name: str) -> str:
    """Return the text inside `struct <name> { ... }`, brace-balanced."""
    m = re.search(rf"\bstruct\s+{re.escape(struct_name)}\b[^{{]*\{{", text)
    if not m:
        return ""
    i = m.end() - 1
    depth = 0
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[m.end():i]
        i += 1
    return ""


def inline_struct_methods(body: str) -> dict[tuple[str, str], bool]:
    """Map (name, args) -> is_const for inline-defined methods in a struct body.

    The SDL Backend defines its methods as inline bodies inside `struct Backend`
    (no `override`, no trailing `;`), so it needs its own scan.
    """
    out: dict[tuple[str, str], bool] = {}
    for m in re.finditer(r"\b(\w+)\s*\(", body):
        got = balanced_args(body, m.end() - 1)
        if got is None:
            continue
        args, after = got
        rest = body[after:after + 200]   # signatures may wrap across lines
        # Either an inline definition (`{`) or an override declaration (`;`).
        if not re.match(
            r"\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:\{|;)", rest
        ):
            continue
        out.setdefault((m.group(1), args), bool(re.match(r"\s*const\b", rest)))
    return out


def backend_methods(text: str) -> dict[tuple[str, str], bool]:
    """Map (name, args) -> is_const for every declared override."""
    out: dict[tuple[str, str], bool] = {}
    for m in re.finditer(r"\b(\w+)\s*\(", text):
        got = balanced_args(text, m.end() - 1)
        if got is None:
            continue
        args, after = got
        rest = text[after:after + 40]
        if "override" not in rest.split(";")[0]:
            continue
        out.setdefault((m.group(1), args), bool(re.match(r"\s*const\b", rest)))
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iface", type=Path, default=DEFAULT_IFACE)
    ap.add_argument("--backend", type=Path, default=DEFAULT_BACKEND)
    ap.add_argument("--sdl", type=Path, default=DEFAULT_SDL,
                    help="host_window.cpp holding the SDL Backend struct")
    args = ap.parse_args(argv)

    iface_path, backend_path = args.iface, args.backend
    if not iface_path.exists() or not backend_path.exists():
        print(f"check_raylib_backend_complete: missing {iface_path} or {backend_path}",
              file=sys.stderr)
        return 1

    want = interface_methods(iface_path.read_text())
    have = backend_methods(backend_path.read_text())

    missing = sorted(k for k in want if k not in have)
    mismatched = [
        f"{key[0]}({key[1]}) const-ness: interface "
        f"{'const' if is_const else 'non-const'}, backend "
        f"{'const' if have[key] else 'non-const'}"
        for key, is_const in sorted(want.items())
        if key in have and have[key] != is_const
    ]

    total = len(want)
    if missing or mismatched:
        print(f"raylib backend INCOMPLETE ({total} interface methods)")
        for name, args in missing:
            print(f"  MISSING override: {name}({args})")
        for problem in mismatched:
            print(f"  MISMATCH: {problem}")
        return 1

    # The SDL Backend lives in an anonymous namespace inside host_window.cpp and
    # its methods are declared without `override`, so the same silent-inheritance
    # bug applies to it. `audio_enabled_state()` shipped for a while doing exactly
    # that: a needless rename that stopped it overriding the interface method, so
    # the base default `false` was returned while SDL audio was actually playing.
    sdl_rc, sdl_note = 0, "sdl backend n/a"
    if args.sdl and args.sdl.exists():
        sdl_text = args.sdl.read_text()
        have_sdl = inline_struct_methods(struct_body(sdl_text, "Backend"))
        # Methods too large to inline live out-of-line as `Backend::name(...)`.
        for m in re.finditer(r"\bBackend::(\w+)\s*\(", sdl_text):
            got = balanced_args(sdl_text, m.end() - 1)
            if got is None:
                continue
            args_s, after = got
            rest = sdl_text[after:after + 200]
            have_sdl.setdefault(
                (m.group(1), args_s), bool(re.match(r"\s*const\b", rest)))
        missing_sdl = sorted(f"{n}({a})" for (n, a) in want if (n, a) not in have_sdl)
        if missing_sdl:
            sdl_rc = 1
            sdl_note = f"SDL backend missing {len(missing_sdl)}: " + ", ".join(
                m.split("(")[0] for m in missing_sdl[:6])
        else:
            sdl_note = f"sdl backend complete: {total}/{total}"

    if sdl_rc != 0:
        print(f"SDL backend INCOMPLETE ({total} interface methods)")
        print(f"  {sdl_note}")
        return sdl_rc

    print(f"raylib backend complete: all {total} interface methods overridden")
    print(f"  {sdl_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))