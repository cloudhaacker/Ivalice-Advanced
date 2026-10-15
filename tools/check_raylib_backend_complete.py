#!/usr/bin/env python3
"""Completeness guard for the single-generation window seam (Phase 4b).

Three checks, all against the sources:

  1. single generation — the flat generation and the SDL backend are gone:
     no `WindowBackendOpenParams` in the seam, no `host_make_sdl_backend` in
     the runtime, no `GBARECOMP_HAVE_SDL2` in host_window.cpp /
     host_backend_factory.cpp, and no inline `Backend` struct in
     host_window.cpp. (SDL *scancode* vocabulary in the input/config layer is
     data, not the backend — out of scope.)
  2. pure interfaces — every virtual in every seam interface (the facade
     `WindowBackend` plus `Video`/`Audio`/`Input`/`Fx`/`Overlay`/`Menu`) is
     pure (`= 0`). A defaulted body is the silent-inheritance bug class this
     guard exists for: the SDL backend's `audio_enabled_state()` once stopped
     overriding the interface method, so the base default answered while
     audio was actually playing.
  3. complete backend — every interface method has a matching `override` in
     the raylib backend sources (raylib_backend.h for the facade,
     raylib_backend.cpp for the nested concern impls).

Why the parsing is fussy: `override` catches signature drift, but not a
method that silently stops overriding (see check 2), and a naive
`\\([^)]*\\)` regex drops `set_host_overlay(void (*overlay)(HostOverlay*))`
because the function-pointer argument contains its own parentheses.

Usage:  python3 tools/check_raylib_backend_complete.py
Exit 0 when all three hold, 1 otherwise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IFACE = ROOT / "gbarecompx/src/runtime/window_backend.h"
DEFAULT_BACKEND_H = ROOT / "gbarecompx/src/runtime/raylib_backend.h"
DEFAULT_BACKEND_CPP = ROOT / "gbarecompx/src/runtime/raylib_backend.cpp"
DEFAULT_HOST_WINDOW = ROOT / "gbarecompx/src/runtime/host_window.cpp"
DEFAULT_FACTORY = ROOT / "gbarecompx/src/runtime/host_backend_factory.cpp"

# The seam interfaces whose methods must all be pure and implemented.
INTERFACE_NAMES = ["WindowBackend", "Video", "Audio", "Input", "Fx",
                   "Overlay", "Menu"]

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


def struct_body(text: str, struct_name: str) -> str:
    """Return the text inside `class|struct <name> { ... }`, brace-balanced."""
    m = re.search(rf"\b(?:class|struct)\s+{re.escape(struct_name)}\b[^{{]*\{{",
                  text)
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


def interface_methods(body: str) -> dict[tuple[str, str], tuple[bool, bool]]:
    """Map (name, args) -> (is_const, is_pure) for every virtual member.

    Destructors are skipped (they are never pure and never `override`n in the
    backend sources as regular methods).
    """
    out: dict[tuple[str, str], tuple[bool, bool]] = {}
    for m in re.finditer(r"\bvirtual\b[^;{]*?(\w+)\s*\(", body):
        # Destructors are never pure and never `override`n as regular methods.
        # (The `~` cannot be captured in the group: the lazy prefix skips it.)
        if body[m.start(1) - 1:m.start(1)] == "~":
            continue
        name = m.group(1)
        got = balanced_args(body, m.end() - 1)
        if got is None:
            continue
        args, after = got
        semi = body.find(";", after)
        if semi < 0:
            continue
        decl = body[after:semi]
        out.setdefault((name, args),
                       (bool(re.match(r"\s*const\b", decl)),
                        bool(re.search(r"=\s*0\s*$", decl.rstrip()))))
    return out


def override_methods(text: str) -> dict[tuple[str, str], bool]:
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


def strip_comments(text: str) -> str:
    """Remove // line comments and /* */ blocks before marker scans.

    The single-generation markers must be judged in *code*: a comment that
    explains the retirement ("Phase 4b retired GBARECOMP_HAVE_SDL2 ...") is
    documentation, not a live reference. (Naive on string literals containing
    `//`; none of the scanned files carry one, and the markers are
    identifiers, so the trade is fine.)
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def single_generation_failures(iface_text: str, host_text: str,
                               factory_text: str) -> list[str]:
    out: list[str] = []
    if "WindowBackendOpenParams" in iface_text:
        out.append("flat generation: WindowBackendOpenParams still in the seam")
    if "host_make_sdl_backend" in host_text or "host_make_sdl_backend" in factory_text:
        out.append("SDL backend: host_make_sdl_backend still present")
    if "GBARECOMP_HAVE_SDL2" in host_text:
        out.append("SDL backend: GBARECOMP_HAVE_SDL2 still in host_window.cpp")
    if "GBARECOMP_HAVE_SDL2" in factory_text:
        out.append("SDL backend: GBARECOMP_HAVE_SDL2 still in "
                   "host_backend_factory.cpp")
    if re.search(r"\b(?:class|struct)\s+Backend\b", host_text):
        out.append("SDL backend: an inline `Backend` struct still exists in "
                   "host_window.cpp")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iface", type=Path, default=DEFAULT_IFACE)
    ap.add_argument("--backend-h", type=Path, default=DEFAULT_BACKEND_H)
    ap.add_argument("--backend-cpp", type=Path, default=DEFAULT_BACKEND_CPP)
    ap.add_argument("--host-window", type=Path, default=DEFAULT_HOST_WINDOW)
    ap.add_argument("--factory", type=Path, default=DEFAULT_FACTORY)
    args = ap.parse_args(argv)

    for p in (args.iface, args.backend_h, args.backend_cpp, args.host_window,
              args.factory):
        if not p.exists():
            print(f"check_raylib_backend_complete: missing {p}", file=sys.stderr)
            return 1

    iface_text = strip_comments(args.iface.read_text())
    host_text = strip_comments(args.host_window.read_text())
    factory_text = strip_comments(args.factory.read_text())

    # ── 1. single generation ─────────────────────────────────────────────
    failures = single_generation_failures(iface_text, host_text, factory_text)

    # ── 2. pure interfaces ───────────────────────────────────────────────
    want: dict[tuple[str, str], tuple[bool, bool]] = {}
    for name in INTERFACE_NAMES:
        body = struct_body(iface_text, name)
        if not body:
            failures.append(f"interface: class {name} not found in the seam")
            continue
        for key, (is_const, is_pure) in interface_methods(body).items():
            if not is_pure:
                failures.append(
                    f"impure interface method: {name}::{key[0]}({key[1]}) has "
                    "a defaulted body — pure-virtual interfaces are the "
                    "contract (silent-inheritance bug class)")
            want.setdefault(key, (name, is_const))

    # ── 3. complete backend ──────────────────────────────────────────────
    have = override_methods(strip_comments(args.backend_h.read_text()))
    have.update(override_methods(strip_comments(args.backend_cpp.read_text())))
    missing = sorted(k for k in want if k not in have)
    mismatched = [
        f"{key[0]}({key[1]}) const-ness: interface "
        f"{'const' if want[key][1] else 'non-const'}, backend "
        f"{'const' if have[key] else 'non-const'}"
        for key in sorted(want)
        if key in have and have[key] != want[key][1]
    ]

    if failures or missing or mismatched:
        print(f"window seam INCOMPLETE ({len(want)} interface methods)")
        for f in failures:
            print(f"  {f}")
        for name, args_ in missing:
            print(f"  MISSING override: {name}({args_})")
        for problem in mismatched:
            print(f"  MISMATCH: {problem}")
        return 1

    print(f"window seam complete: {len(want)} interface methods, all pure, "
          "all overridden by the raylib backend")
    print("single generation: no flat class, no SDL backend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
