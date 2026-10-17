#!/usr/bin/env python3
"""Device-free Android checks for FFTARecomp (check.py suite: `android-static`).

Validates the game-repo Android surface without a phone, an SDK, or a Gradle
build, and self-tests the device gate script against a fake `adb`:

  identity  applicationId / variant / ROM / BIOS / save pins consistent
            across android/app/build.gradle, android/game_android.toml,
            game.toml, the gate script constants and the engine default
  payload   android/payload/mods/state.toml keeps the widescreen feature
            enabled (the second-launch fix) and matches the preloaded catalog
  hygiene   no ROM/save/APK/binary artifacts tracked; android build outputs
            stay gitignored
  scaffold  the Android base is the raylib/NativeActivity scaffold: no SDL
            submodule entry/gitlink, no SDLActivity, no SDL CMake subproject,
            no sdlRoot in the Gradle plugin (Phase 4f). The retired desktop
            SDL stack (Track L) is out of scope.
  gate      tools/validate_android.sh passes a clean fake-device run (evidence
            pulled) and fails SELF-HEAL / missing-log / crash-buffer /
            setup-still-resumed runs; usage errors exit 2

Usage: tools/android_static_check.py        (stdlib only; runs from any cwd)
Exit codes: 0 = all checks pass, 1 = at least one failure.
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # Python 3.10 (tomllib landed in 3.11)
    _tomllib = None

# The committed clean-room BIOS pin (emibios main @c4d5d71,
# https://github.com/coolbho3k/emibios — LGPL-3.0-or-later) — the engine
# template's default since the 2026-10-18 fork flip. The retail dump hash
# lives in the engine (gba_bios.h kExpectedSha1) and
# THIRD_PARTY_ATTRIBUTION.md; it is no longer a default anywhere.
EMIBIOS_SHA1 = "0c0d404d16c6b55b3071aba714f82077da132f14"


# ---------------------------------------------------------------------------
# Minimal TOML reading (tomllib when available, subset fallback for 3.10)
# ---------------------------------------------------------------------------

def _strip_comment(line):
    out = []
    in_string = False
    escaped = False
    for ch in line:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if in_string and ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if ch == "#" and not in_string:
            break
        out.append(ch)
    return "".join(out)


def _parse_scalar(text):
    text = text.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text, 0)
    except ValueError:
        return text


def _mini_load(path):
    """Subset reader for the shapes this repo's Android TOMLs use: flat
    [tables], [[arrays of tables]], string/bool/int scalars, comments."""
    root = {}
    current = root
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[[") and line.endswith("]]"):
            current = {}
            root.setdefault(line[2:-2].strip(), []).append(current)
            continue
        if line.startswith("[") and line.endswith("]"):
            current = root.setdefault(line[1:-1].strip(), {})
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError("%s:%d: unsupported line: %s"
                             % (path, lineno, raw.strip()))
        current[key.strip()] = _parse_scalar(value)
    return root


def sha1_bytes(data):
    return hashlib.sha1(data).hexdigest()


def load_toml(rel):
    path = REPO / rel
    if _tomllib is not None:
        with path.open("rb") as handle:
            return _tomllib.load(handle)
    return _mini_load(path)


def read_text(rel):
    return (REPO / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Check plumbing
# ---------------------------------------------------------------------------

class CheckFailure(Exception):
    pass


def need(condition, message):
    if not condition:
        raise CheckFailure(message)


def one(pattern, text, what, flags=0):
    match = re.search(pattern, text, flags)
    need(match is not None, "could not find %s" % what)
    return match.group(1)


class Suite:
    def __init__(self):
        self.results = []  # (name, ok, detail)

    def run(self, name, fn):
        try:
            fn()
        except CheckFailure as exc:
            self.results.append((name, False, str(exc)))
        except Exception as exc:  # keep the suite summarizing on bugs too
            self.results.append(
                (name, False, "%s: %s" % (type(exc).__name__, exc)))
        else:
            self.results.append((name, True, ""))


def tail(completed, limit=300):
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "(no output)"
    return " | ".join(lines[-2:])[:limit]


# ---------------------------------------------------------------------------
# Identity checks
# ---------------------------------------------------------------------------

def check_package_constants():
    gradle = read_text("android/app/build.gradle")
    package = one(r'applicationId\s*:\s*"([^"]+)"', gradle, "applicationId")
    gate = read_text("tools/validate_android.sh")
    gate_package = one(r'^PACKAGE="([^"]+)"', gate, "PACKAGE", re.M)
    need(package == gate_package,
         "applicationId %r != gate PACKAGE %r" % (package, gate_package))
    setup = one(r'^SETUP_ACTIVITY="([^"]+)"', gate, "SETUP_ACTIVITY", re.M)
    game = one(r'^GAME_ACTIVITY="([^"]+)"', gate, "GAME_ACTIVITY", re.M)
    need(setup.endswith(".GbaSetupActivity") and game.endswith(".GbaGameActivity"),
         "gate activity constants look renamed: %s / %s" % (setup, game))


def check_variant():
    gradle = read_text("android/app/build.gradle")
    gradle_variant = one(r'^\s*variant\s*:\s*"([^"]+)"', gradle,
                         "gbaGame variant", re.M)
    game = load_toml("game.toml")["game"]["short_name"]
    android = load_toml("android/game_android.toml")["game"]["short_name"]
    need(len({gradle_variant, game, android}) == 1,
         "variant/short_name mismatch: build.gradle=%r game.toml=%r "
         "game_android.toml=%r" % (gradle_variant, game, android))


def check_rom_pins():
    gradle = read_text("android/app/build.gradle")
    gradle_sha = one(r'romSha1\s*:\s*\["([0-9a-f]{40})"\]', gradle, "romSha1")
    gradle_size = int(one(r'romSize\s*:\s*(\d+)', gradle, "romSize"))
    gradle_file = one(r'romFile\s*:\s*"([^"]+)"', gradle, "romFile")
    game = load_toml("game.toml")
    android = load_toml("android/game_android.toml")
    shas = {gradle_sha, game["identity"]["sha1"], game["rom"]["sha1"],
            android["rom"]["sha1"]}
    need(len(shas) == 1, "ROM sha1 mismatch across build.gradle / game.toml "
                         "[identity] / game.toml [rom] / game_android.toml: %s"
                         % sorted(shas))
    need(game["program"]["size"] == gradle_size,
         "game.toml [program].size %d != build.gradle romSize %d"
         % (game["program"]["size"], gradle_size))
    android_file = Path(android["rom"]["path"]).name
    need(android_file == gradle_file,
         "game_android.toml [rom].path basename %r != romFile %r"
         % (android_file, gradle_file))


def check_bios_pins():
    # The launch BIOS is the committed clean-room emibios (issue #17):
    # every pin — both game TOMLs, the build.gradle manifest pin, and the
    # committed bin itself — must agree, the payload must stage it, and the
    # engine-side acceptance (bios pin-set + public-guard exemption) must
    # exist in the framework tree (the gbarecompx fork submodule).
    game = load_toml("game.toml")
    android = load_toml("android/game_android.toml")
    for name, toml in (("game.toml", game), ("android/game_android.toml", android)):
        need(toml["bios"]["sha1"] == EMIBIOS_SHA1,
             "%s [bios].sha1 %s != the committed emibios pin %s"
             % (name, toml["bios"]["sha1"], EMIBIOS_SHA1))
    need(game["bios"]["path"] == "bios/emibios_gba_bios.bin",
         "game.toml [bios].path %r must point at the committed bin"
         % game["bios"]["path"])
    need(android["bios"]["path"] == "../../bios/emibios_gba_bios.bin",
         "game_android.toml [bios].path %r must resolve to the staged "
         "payload bin (payload/bios/emibios_gba_bios.bin)"
         % android["bios"]["path"])
    need(game["bios"]["hle"] is True,
         "game.toml must keep [bios].hle = true (HLE)")
    need(android["bios"]["hle"] is True,
         "game_android.toml must keep [bios].hle = true (HLE)")
    need(android["bios"]["hle"] == game["bios"]["hle"],
         "BIOS HLE mismatch: game.toml hle=%r != game_android.toml hle=%r"
         % (game["bios"]["hle"], android["bios"]["hle"]))
    gradle = (REPO / "android/app/build.gradle").read_text(encoding="utf-8")
    pin = one(r'biosSha1\s*:\s*"([0-9a-f]{40})"', gradle, "build.gradle biosSha1")
    need(pin == EMIBIOS_SHA1,
         "android/app/build.gradle biosSha1 %s != the committed emibios "
         "pin %s (the manifest verify pin must match the payload BIOS)"
         % (pin, EMIBIOS_SHA1))
    need(re.search(r"biosRequired\s*:\s*false", gradle) is not None,
         "android/app/build.gradle must set biosRequired: false — the "
         "clean-room BIOS is bundled, so the SAF setup must not prompt "
         "for a BIOS dump (which the emibios pin would reject)")
    need("bios/emibios_gba_bios.bin\"), into: \"bios\"" in gradle,
         "android/app/build.gradle payloadDirs must stage "
         "bios/emibios_gba_bios.bin into the payload bios/ dir")
    # Upstream's engine template carried a retail default as the fallback
    # for games that do not declare their own BIOS; the gbarecompx fork
    # flipped that default to the clean-room emibios (2026-10-18). The
    # game's build.gradle override is the pin that reaches the manifest.
    # Any OTHER value means the default moved again — re-review the
    # public-guard exemption (emibios-public-guard-bundled semantics).
    template = REPO / "gbarecompx/platform/android/gbarecomp-app.gradle"
    need(template.is_file(),
         "%s missing — initialize the gbarecomp submodule"
         % template.relative_to(REPO))
    default = one(r'gbaBiosSha1:\s*g\.biosSha1\s*\?:\s*"([0-9a-f]{40})"',
                  template.read_text(encoding="utf-8"),
                  "engine biosSha1 default")
    need(default == EMIBIOS_SHA1,
         "engine template biosSha1 default %s != the emibios default %s "
         "— deliberate? Re-review the public-artifact guard exemption "
         "(a declared pin equal to the retail hash must stay "
         "unbundleable)" % (default, EMIBIOS_SHA1))


def check_emibios_engine_acceptance():
    # The engine must actually accept the clean-room BIOS on both surfaces:
    # the bios pin-set (gba_bios.h kEmibiosSha1 — pin set {retail, emibios},
    # recognized by the asset picker) and the Android public-artifact guard
    # (declared-bundled-BIOS exemption). On a fresh clone (pristine
    # submodule) the acceptance lives in the recorded patches, so accept
    # either form (the `patches` suite pins fidelity).
    sources = ""
    for rel in ("gbarecompx/src/gba/gba_bios.h",
                "gbarecompx/src/runtime/launcher_seam.h",
                "gbarecompx/platform/android/gbarecomp-app.gradle"):
        path = REPO / rel
        if path.is_file():
            sources += path.read_text(encoding="utf-8")
    def present(token, what):
        need(token in sources,
             "%s missing from the gbarecomp framework tree (the "
             "gbarecompx fork submodule)" % what)
    present("kEmibiosSha1", "the emibios pin constant (gba_bios.h)")
    present("GbaBios::kEmibiosSha1",
            "the launcher pin-set verify (launcher_seam.h)")
    present("exemptBundledBios",
            "the public-guard bundled-BIOS exemption (gbarecomp-app.gradle)")


def check_payload_version():
    gradle = (REPO / "android/app/build.gradle").read_text(encoding="utf-8")
    m = re.search(r'payloadVersion:\s*"([^"]+)"', gradle)
    need(m, "payloadVersion missing in android/app/build.gradle")
    ver = m.group(1)
    need(ver != "1" and ver != "2",
         "payloadVersion %r is stale: bump it whenever staged payload "
         "content changes (game_android.toml or anything under payload/), "
         "or reinstalls keep running the old payload" % ver)


def check_emibios_integrity():
    # The committed clean-room BIOS (LGPL-3.0-or-later, freely
    # redistributable — NOT private material; see bios/emibios_gba_bios.toml
    # header) is the launch-pinned [bios] target after the E2 swap. Guard it
    # like any pinned fixture: exact size + SHA-1 against the TOML identity,
    # so corruption or an accidental replacement fails tier-1 loudly instead
    # of producing a subtly wrong BIOS corpus at build time.
    bin_path = REPO / "bios/emibios_gba_bios.bin"
    toml_path = REPO / "bios/emibios_gba_bios.toml"
    need(bin_path.is_file(),
         "bios/emibios_gba_bios.bin missing — the committed clean-room BIOS "
         "is repo material (LGPL), not a dump; restore it from the branch")
    need(toml_path.is_file(),
         "bios/emibios_gba_bios.toml missing (the recompile config)")
    data = bin_path.read_bytes()
    need(len(data) == 16384,
         "emibios bin is %d bytes, expected 16384 (16 KiB BIOS image)"
         % len(data))
    need(sha1_bytes(data) == EMIBIOS_SHA1,
         "emibios bin sha1 %r != pin %r — corrupted or replaced?"
         % (sha1_bytes(data), EMIBIOS_SHA1))
    text = toml_path.read_text(encoding="utf-8")
    m = re.search(r'sha1\s*=\s*"([0-9a-f]{40})"', text)
    need(m and m.group(1) == EMIBIOS_SHA1,
         "bios/emibios_gba_bios.toml [identity].sha1 does not match the "
         "committed bin pin %s" % EMIBIOS_SHA1)


def check_save_config():
    game = load_toml("game.toml")
    android = load_toml("android/game_android.toml")
    need(android["save"]["type"] == game["save"]["type"],
         "save type mismatch: game.toml %r != game_android.toml %r"
         % (game["save"]["type"], android["save"]["type"]))
    need(android["save"]["size"] == game["save"]["size"],
         "save size mismatch: game.toml %d != game_android.toml %d"
         % (game["save"]["size"], android["save"]["size"]))


def check_save_picker_wiring():
    # Issue #20: optional .sav import on the setup screen (desktop parity).
    # The setup card is game-agnostic (saveFile/saveSize manifest pins); the
    # FFTA pins must match both TOML save declarations, the engine must carry
    # the card + validation + dual-write, and the import must never gate PLAY.
    game = load_toml("game.toml")
    android = load_toml("android/game_android.toml")
    gradle = read_text("android/app/build.gradle")
    save_file = one(r'saveFile\s*:\s*"([^"]+)"', gradle, "build.gradle saveFile")
    save_size = int(one(r'saveSize\s*:\s*(\d+)', gradle, "build.gradle saveSize"))
    need(save_file == Path(android["save"]["path"]).name,
         "build.gradle saveFile %r != game_android.toml [save].path basename %r"
         % (save_file, Path(android["save"]["path"]).name))
    need(save_file == Path(game["save"]["path"]).name,
         "build.gradle saveFile %r != game.toml [save].path basename %r"
         % (save_file, Path(game["save"]["path"]).name))
    need(save_size == android["save"]["size"] == game["save"]["size"],
         "saveSize mismatch: build.gradle=%d game_android.toml=%d game.toml=%d"
         % (save_size, android["save"]["size"], game["save"]["size"]))
    # Engine template + manifest plumbing (the gbarecompx fork submodule —
    # the fork carries the save-picker wiring as committed code; see
    # check_save_external_wiring).
    template = read_text("gbarecompx/platform/android/gbarecomp-app.gradle")
    manifest = read_text("gbarecompx/platform/android/AndroidManifest.xml")
    config_java = read_text(
        "gbarecompx/platform/android/java/org/gbarecomp/GbaGameConfig.java")
    setup_java = read_text(
        "gbarecompx/platform/android/java/org/gbarecomp/GbaSetupActivity.java")
    combined = template + manifest + config_java + setup_java
    for token, what in (
            ("gbaSaveFile", "engine placeholder gbaSaveFile"),
            ("gbaSaveSize", "engine placeholder gbaSaveSize"),
            ("gbarecomp.save_file", "manifest meta-data save_file"),
            ("gbarecomp.save_size", "manifest meta-data save_size"),
            ("saveFile", "GbaGameConfig.saveFile"),
            ("saveSize", "GbaGameConfig.saveSize"),
            ("PICK_SAVE", "setup PICK_SAVE request"),
            ("installVerifiedSave", "setup save installer"),
            ("hasSaveImport", "setup save-card gate"),
            ("externalSaveFile", "setup external mirror"),
            ("IMPORT SAVE", "setup save affordance (launch-screen redesign)")):
        need(token in combined,
             "save-picker token %r missing (%s)" % (token, what))
    # The import is optional: ready() must not consult the save state.
    m = re.search(r"private boolean ready\(\) \{([^}]*)\}", setup_java)
    need(m is not None, "setup ready() unreadable")
    need("saveReady" not in m.group(1) and "save" not in m.group(1).lower(),
         "setup ready() must not gate PLAY on the optional save (issue #20)")
    # Dual-write: the installer must mirror to external so a re-import after
    # the issue-#6 migration is not stranded in app-private storage.
    need("copyFile(destination, external)" in setup_java
         or "copyFile(destination, external)" in recorded,
         "setup save installer must mirror to the external saves/ dir")


def check_save_external_wiring():
    # Issue #6: battery saves + save states must land in the user-visible
    # external app directory. The TOML keeps the app-private fallback (used
    # when external storage is unavailable); src/main.cpp migrates + appends
    # --save-path/--state-dir on Android; the engine honors --state-dir for
    # slots/suspend; the lifecycle gate asserts the external locations.
    android = load_toml("android/game_android.toml")
    need(android["save"]["path"].replace("\\", "/").endswith(
        "saves/ffta_us.sav"),
         "game_android.toml [save].path must keep the app-private fallback "
         "saves/ffta_us.sav, found %r" % android["save"]["path"])
    main = read_text("src/main.cpp")
    # The lookup is the baked applicationId (the raylib/NativeActivity base
    # since Phase 4f; the pre-4f shell asked its own storage API instead).
    need("GBARECOMP_ANDROID_PACKAGE" in main and "/sdcard/Android/data/" in main,
         "src/main.cpp lost the external-storage lookup (issue #6)")
    for token in ("--save-path", "--state-dir", "saves/ffta_us.sav",
                  "ffta_usa.state", "ffta_usa.suspend.state",
                  ".suspend.pending"):
        need(token in main,
             "src/main.cpp missing external-redirect token %r (issue #6)"
             % token)
    gradle = read_text("android/app/build.gradle")
    need('romFile' in gradle and 'ffta_usa.gba' in gradle,
         "build.gradle romFile pin unreadable (state basenames derive "
         "from it)")
    need("ffta_usa" in main,
         "src/main.cpp state basenames drifted from romFile ffta_usa.gba")
    runtime = read_text("gbarecompx/src/runtime/runtime.cpp")
    runtime_ok = ('"--state-dir"' in runtime and "args->state_dir" in runtime
                  and "state_base" in runtime)
    need(runtime_ok,
         "engine --state-dir knob missing from gbarecompx/src/runtime/"
         "runtime.cpp (slots/suspend would stay app-private)")
    lifecycle = read_text("tools/android_lifecycle_test.py")
    need("/sdcard/Android/data/" in lifecycle
         and "/states/ffta_usa" in lifecycle
         and "/saves/ffta_us.sav" in lifecycle,
         "android_lifecycle_test.py must assert the external save/state "
         "locations (issue #6)")


def check_logs_external_wiring():
    # Diagnostics (runtime log, miss frag, coverage) must land in the
    # user-visible external app directory next to saves/states, so they can
    # be pulled without run-as. src/main.cpp resolves the external logs/ dir
    # before the engine redirect (MobileProcessOptions.log_file) and points
    # the frag/coverage env there; the engine hardens a failed log open with
    # a logcat fallback instead of silent loss (2026-10-11 sessions).
    main = read_text("src/main.cpp")
    for token in ("ffta_redirect_diagnostics", "ffta_log_manifest",
                  "GBARECOMP_MISS_FRAG", "GBARECOMP_COVERAGE_JSON",
                  "recomp_master_misses_AFXE.toml.frag",
                  "recomp_coverage_AFXE.json",
                  "mobile.log_file", '/ "logs"'):
        need(token in main,
             "src/main.cpp missing diagnostics-redirect token %r" % token)
    plat = read_text("gbarecompx/src/runtime/mobile_platform.cpp")
    plat_ok = ("__android_log_print" in plat and "cannot open log" in plat)
    need(plat_ok,
         "engine log-open fallback missing from gbarecompx/src/runtime/"
         "mobile_platform.cpp (silent-log class)")


# ---------------------------------------------------------------------------
# Payload checks
# ---------------------------------------------------------------------------

def check_state_toml():
    state = load_toml("android/payload/mods/state.toml")
    packages = state.get("package", [])
    need(len(packages) == 1,
         "expected one [[package]] in state.toml, found %d" % len(packages))
    package = packages[0]
    need(package.get("id") == "ffta.enhancement.widescreen",
         "unexpected default package %r — update this check and the docs if "
         "the default selection is deliberate" % package.get("id"))
    matches = [f for f in state.get("feature", [])
               if f.get("package_id") == package.get("id")
               and f.get("id") == "widescreen"]
    need(matches and matches[0].get("enabled") is True,
         "state.toml must ship enabled = true for the widescreen feature: the "
         "engine persists raw false for never-touched features from the "
         "second launch on (see android/README.md § Mods state)")


def check_state_catalog():
    state = load_toml("android/payload/mods/state.toml")
    package = state["package"][0]
    package_id = package["id"]
    version = package["version"]
    manifest_path = (REPO / "mods/preloaded/packages" / package_id / version
                     / "manifest.toml")
    need(manifest_path.is_file(),
         "catalog manifest missing: %s" % manifest_path.relative_to(REPO))
    manifest = load_toml(str(manifest_path.relative_to(REPO)))
    need(manifest.get("id") == package_id
         and manifest.get("version") == version,
         "state.toml package %s/%s != catalog manifest %s/%s"
         % (package_id, version, manifest.get("id"), manifest.get("version")))
    catalog_features = {f.get("id") for f in manifest.get("feature", [])}
    state_features = {f.get("id") for f in state.get("feature", [])}
    unknown = state_features - catalog_features
    need(not unknown,
         "state.toml enables feature(s) the catalog does not declare: %s"
         % ", ".join(sorted(unknown)))


def check_payload_wiring():
    for rel in ("mods/preloaded/packages", "android/payload/mods"):
        path = REPO / rel
        need(path.is_dir() and any(path.iterdir()),
             "%s missing or empty" % rel)
    gradle = read_text("android/app/build.gradle")
    need('"mods/preloaded"' in gradle and '"payload/mods"' in gradle,
         "build.gradle payloadDirs no longer stages both mods sources")


def check_resize_view():
    android = load_toml("android/game_android.toml")
    need(android["video"].get("resize_view") is True,
         "game_android.toml must keep [video] resize_view = true — the "
         "Android expanded-view opt-in (deliberate change? update "
         "android/README.md § Decisions and this check)")


# ---------------------------------------------------------------------------
# Hygiene checks
# ---------------------------------------------------------------------------

def check_tracked_artifacts():
    completed = subprocess.run(["git", "ls-files"], cwd=str(REPO),
                               capture_output=True, text=True, timeout=60)
    need(completed.returncode == 0,
         "git ls-files failed: %s" % tail(completed))
    offenders = []
    for name in completed.stdout.splitlines():
        base = name.rsplit("/", 1)[-1].lower()
        if base == "gba_bios.bin" or re.search(
                r"\.(gba|sav|apk|aab|state\d*)$", base):
            offenders.append(name)
    need(not offenders,
         "tracked private/binary artifacts: %s" % ", ".join(offenders[:5]))


def check_ignored_outputs():
    paths = [
        "android/artifacts/last-run/screenshot.png",
        "android/.fetchcontent/arm64-v8a/raylib-subbuild/CMakeCache.txt",
        "android/app/build/outputs/apk/debug/app-debug.apk",
        "android/local.properties",
        "android/signing.local.properties",
        "android/.gradle/file-system.probe",
        "sample.apk",
    ]
    missing = []
    for rel in paths:
        completed = subprocess.run(["git", "check-ignore", "-q", rel],
                                   cwd=str(REPO), capture_output=True,
                                   text=True, timeout=60)
        if completed.returncode != 0:
            missing.append(rel)
    need(not missing, "path(s) no longer gitignored: %s" % ", ".join(missing))


def check_scaffold_sdl_free():
    """The Android base is the raylib/NativeActivity scaffold (Phase 4f).

    Scans the framework's platform/android scaffold and the game's android/
    project for SDL: submodule entry/gitlink, SDLActivity, the SDL CMake
    subproject, sdlRoot. Build outputs, artifacts and the framework's
    third_party tree are excluded; the retired desktop SDL stack (Track L,
    recomp-ui — removed in the 2026-10 launcher track) is out of scope."""
    engine = REPO / "gbarecompx"
    if not (engine / "platform/android").is_dir():
        return  # the raylib tree is absent (CI before Phase 7): nothing to scan
    offenders = []

    gitmodules = engine / ".gitmodules"
    if gitmodules.is_file() and "third_party/SDL" in gitmodules.read_text():
        offenders.append("gbarecompx/.gitmodules still lists the SDL submodule")
    if (engine / "platform/android/third_party/SDL").exists():
        offenders.append("platform/android/third_party/SDL still exists")

    token = re.compile(r"sdl", re.IGNORECASE)
    skip_parts = {"third_party", ".cxx", ".fetchcontent", "build", ".gradle",
                  "artifacts"}
    exts = {".gradle", ".java", ".xml", ".txt", ".md", ".ps1", ".c", ".h",
            ".cmake", ".toml", ".properties"}
    for root in (engine / "platform/android", REPO / "android"):
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in exts:
                continue
            if any(part in skip_parts for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if token.search(line):
                    offenders.append(
                        "%s:%d: %s" % (path.relative_to(REPO), line_no,
                                       line.strip()[:80]))
    need(not offenders, "SDL references in the Android scaffold:\n    " +
         "\n    ".join(offenders[:12]))


# ---------------------------------------------------------------------------
# Gate self-test (fake adb)
# ---------------------------------------------------------------------------

FAKE_ADB = '''\
#!/usr/bin/env bash
# Fake `adb` for tools/android_static_check.py — not a device tool.
# FADB_SCENARIO selects the canned behavior: clean | selfheal | missing-log |
# crash | setup-resumed. Outputs mimic a device just closely enough for
# tools/validate_android.sh to walk its normal code paths.
set -u

scenario="${FADB_SCENARIO:-clean}"

args=("$@")
if [ "${args[0]:-}" = "devices" ]; then
  printf 'List of devices attached\\nFADB123\\tdevice\\n'
  exit 0
fi
if [ "${args[0]:-}" = "-s" ]; then
  args=("${args[@]:2}")
fi
cmd="${args[0]:-}"
sub="${args[1]:-}"

case "$cmd" in
  get-state)
    printf 'device\\n' ;;
  install)
    printf 'Success\\n' ;;
  shell)
    case "$sub" in
      getprop)
        case "${args[2]:-}" in
          ro.product.model) printf 'FakePhone\\n' ;;
          ro.build.version.release) printf '14\\n' ;;
          ro.build.version.sdk) printf '34\\n' ;;
          ro.product.cpu.abi) printf 'arm64-v8a\\n' ;;
          *) printf '\\n' ;;
        esac ;;
      pidof)
        printf '4242\\n' ;;
      am)
        if [ "${args[2]:-}" = "start" ]; then
          printf 'Starting: Intent { cmp=org.gbarecomp.fftarecomp/org.gbarecomp.GbaSetupActivity }\\n'
        fi ;;
      dumpsys)
        if [ "${args[2]:-}" = "package" ]; then
          # Stale-build guard: only the stale-version scenario carries a
          # versionName; every other scenario reports none (guard skips).
          if [ "$scenario" = "stale-version" ]; then
            printf '    versionName=1.6-0-goldcommit\\n'
          fi
        elif [ "$scenario" = "setup-resumed" ]; then
          printf '    topResumedActivity=ActivityRecord{1 u0 org.gbarecomp.fftarecomp/org.gbarecomp.GbaSetupActivity t1}\\n'
        else
          printf '    topResumedActivity=ActivityRecord{1 u0 org.gbarecomp.fftarecomp/org.gbarecomp.GbaGameActivity t1}\\n'
        fi ;;
      *) : ;;
    esac ;;
  exec-out)
    # exec-out run-as <pkg> cat <path>
    path="${args[4]:-}"
    case "$path" in
      files/android-runtime.log)
        case "$scenario" in
          selfheal)
            printf 'gbarecomp: cpu_backend=static-recompiled\\n'
            printf 'runtime: SELF-HEAL dispatch miss pc=0x08001234\\n' ;;
          missing-log)
            printf 'cat: files/android-runtime.log: No such file or directory\\n' ;;
          *)
            printf 'gbarecomp: cpu_backend=static-recompiled\\n'
            printf 'gbarecomp: frames=2400 self_heal_coverage=FULLY_STATIC\\n' ;;
        esac ;;
      *)
        # Every other app-private read (miss frag, coverage json) is absent.
        # `exec-out` folds the remote stderr into stdout; the gate must
        # tolerate that instead of treating "cat: ..." as file content.
        printf 'cat: %s: No such file or directory\\n' "$path" ;;
    esac ;;
  logcat)
    if [ "${args[2]:-}" = "crash" ] && [ "${args[3]:-}" = "-c" ]; then
      exit 0
    fi
    if [ "$scenario" = "crash" ]; then
      printf 'F DEBUG   : Fatal signal 11 (SIGSEGV), code 1, fault addr 0x0 in tid 4242 (fftarecomp)\\n'
      printf 'F DEBUG   : pid: 4242, tid: 4242, name: fftarecomp  >>> org.gbarecomp.fftarecomp <<<\\n'
    fi ;;
  *) : ;;
esac
exit 0
'''

# Fake `git` beside the fake adb: a deterministic `describe --tags` so the
# gate's stale-build assertion compares against a fixed checkout version
# (real repos vary; tag-less CI checkouts would skip — this pins the FAIL
# path device-free).
FAKE_GIT = '''\
#!/usr/bin/env bash
case "${1:-} ${2:-}" in
  "describe --tags") printf 'v1.6-99-gnewcommit\\n' ;;
  *) exit 0 ;;
esac
'''


def run_gate(scenario, extra_args=()):
    """Run tools/validate_android.sh with the fake adb; returns the completed
    process plus a name->bytes snapshot of the pulled evidence."""
    with tempfile.TemporaryDirectory(prefix="ffta_android_static_") as tmp:
        tmp_path = Path(tmp)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        adb = bindir / "adb"
        adb.write_text(FAKE_ADB, encoding="utf-8")
        adb.chmod(0o755)
        git = bindir / "git"
        git.write_text(FAKE_GIT, encoding="utf-8")
        git.chmod(0o755)
        evidence = tmp_path / "evidence"
        env = dict(os.environ)
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        env["FADB_SCENARIO"] = scenario
        cmd = ["bash", str(REPO / "tools/validate_android.sh"),
               "--no-install", "--wait", "0", "--no-screenshot",
               "--pull-dir", str(evidence)]
        cmd.extend(extra_args)
        completed = subprocess.run(cmd, cwd=str(REPO), env=env,
                                   capture_output=True, text=True, timeout=180)
        pulled = {}
        if evidence.is_dir():
            for item in sorted(evidence.iterdir()):
                pulled[item.name] = item.read_bytes()
        return completed, pulled


def run_gate_cli(*args):
    return subprocess.run(
        ["bash", str(REPO / "tools/validate_android.sh"), *args],
        cwd=str(REPO), capture_output=True, text=True, timeout=60)


def check_gate_clean():
    completed, pulled = run_gate("clean")
    need(completed.returncode == 0,
         "clean fake-device run should pass (rc=%d): %s"
         % (completed.returncode, tail(completed)))
    out = completed.stdout
    need("GATE PASSED" in out, "no GATE PASSED line: %s" % tail(completed))
    counts = re.search(r"(\d+) passed, (\d+) failed", out)
    need(counts is not None and counts.group(2) == "0",
         "clean run reported failures: %s" % tail(completed))
    log = pulled.get("android-runtime.log", b"").decode("utf-8", "replace")
    need("cpu_backend=static-recompiled" in log,
         "evidence runtime log lacks the backend line")
    need("crash.log" in pulled, "crash.log evidence was not pulled")
    need("screenshot.png" not in pulled,
         "--no-screenshot must not produce a screenshot")
    need("recomp_master_misses_AFXE.toml.frag" not in pulled,
         "an absent miss frag must not appear in the evidence dir")


def check_gate_selfheal():
    completed, _ = run_gate("selfheal")
    need(completed.returncode == 1,
         "SELF-HEAL log should fail the gate (rc=%d)" % completed.returncode)
    out = completed.stdout
    need("GATE FAILED" in out and "dispatch-miss entries" in out,
         "expected the dispatch-miss assertion to fail: %s" % tail(completed))


def check_gate_missing_log():
    completed, _ = run_gate("missing-log")
    need(completed.returncode == 1,
         "missing runtime log should fail the gate (rc=%d)"
         % completed.returncode)
    need("app-private read failed" in completed.stdout,
         "expected the app-private read reason: %s" % tail(completed))


def check_gate_crash():
    completed, _ = run_gate("crash")
    need(completed.returncode == 1,
         "crash-buffer entry should fail the gate (rc=%d)"
         % completed.returncode)
    need("crash buffer has" in completed.stdout,
         "expected the crash assertion to fail: %s" % tail(completed))


def check_gate_setup_resumed():
    completed, _ = run_gate("setup-resumed")
    need(completed.returncode == 1,
         "setup-still-resumed should fail the gate (rc=%d)"
         % completed.returncode)
    need("the setup screen is resumed instead" in completed.stdout,
         "expected the resumed-activity assertion to fail: %s"
         % tail(completed))


def check_gate_stale_version():
    completed, _ = run_gate("stale-version")
    need(completed.returncode == 1,
         "a stale installed APK should fail the gate (rc=%d)"
         % completed.returncode)
    need("is not this checkout" in completed.stdout,
         "expected the stale-build assertion to fail: %s" % tail(completed))


def check_gate_usage():
    helped = run_gate_cli("--help")
    need(helped.returncode == 0 and "Usage:" in helped.stdout,
         "--help should print usage and exit 0: %s" % tail(helped))
    bad_wait = run_gate_cli("--wait", "nope")
    need(bad_wait.returncode == 2,
         "bad --wait should exit 2 (got %d)" % bad_wait.returncode)
    bad_flag = run_gate_cli("--bogus")
    need(bad_flag.returncode == 2,
         "unknown option should exit 2 (got %d)" % bad_flag.returncode)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def check_boxart_drawable_wiring():
    """Launch-screen box art must flow through the engine template's
    launchBoxartRes mechanism (staged as drawable-nodpi/launcher_boxart.png,
    resolved by name via getIdentifier), never as an APK asset — the assets
    contract is payload-only."""
    gradle = read_text("android/app/build.gradle")
    need("launchBoxartRes" in gradle,
         "build.gradle must set the engine template's launchBoxartRes "
         "(the boxart staging mechanism)")
    need("recomp/launcher/boxart.png" in gradle,
         "build.gradle must point launchBoxartRes at the tracked "
         "recomp/launcher/boxart.png")
    setup_java = read_text(
        "gbarecompx/platform/android/java/org/gbarecomp/GbaSetupActivity.java")
    need('"launcher_boxart", "drawable"' in setup_java,
         "GbaSetupActivity must resolve the launcher_boxart drawable by "
         "name (getIdentifier — game-namespace-agnostic)")
    need((REPO / "recomp/launcher/boxart.png").is_file(),
         "recomp/launcher/boxart.png missing (the tracked boxart source)")


def check_launch_screen_skip_classification():
    """src/main.cpp must classify the MUTATED args vector — the Android
    native entry's argv is raylib's synthetic {"raylib"}, invisible to
    appended flags; classifying the raw argv made the launch screen
    un-skippable on Android (2026-10-16 device finding)."""
    main_cpp = read_text("src/main.cpp")
    need("launcher_should_skip_screen(args)" in main_cpp,
         "src/main.cpp must classify the mutated args vector "
         "(launcher_should_skip_screen(args)), not the raw argv")
    need("launcher_should_skip_screen(argc" not in main_cpp,
         "src/main.cpp must not classify the raw argv (invisible on Android)")
    need("launcher_wants_screen(args)" in main_cpp,
         "src/main.cpp must honor an explicit --launcher force "
         "(launcher_wants_screen(args))")


    need((REPO / "recomp/launcher/boxart.png").is_file(),
         "recomp/launcher/boxart.png missing (the tracked boxart source)")


def check_launch_screen_skip_classification():
    """src/main.cpp must classify the MUTATED args vector — the Android
    native entry's argv is raylib's synthetic {"raylib"}, invisible to
    appended flags; classifying the raw argv made the launch screen
    un-skippable on Android (2026-10-16 device finding). The Android posture
    (user decision, 2026-10-16): the platform setup activity is the pre-boot
    surface; the raygui launch screen is desktop-only."""
    main_cpp = read_text("src/main.cpp")
    need("launcher_should_skip_screen(args)" in main_cpp,
         "src/main.cpp must classify the mutated args vector "
         "(launcher_should_skip_screen(args)), not the raw argv")
    need("launcher_should_skip_screen(argc" not in main_cpp,
         "src/main.cpp must not classify the raw argv (invisible on Android)")
    need("launcher_wants_screen(args)" in main_cpp,
         "src/main.cpp must honor an explicit --launcher force "
         "(launcher_wants_screen(args))")


CHECKS = [
    ("identity: applicationId and gate package/activity constants",
     check_package_constants),
    ("identity: variant matches [game] short_name (3 files)", check_variant),
    ("identity: ROM sha1/size/file consistent (build.gradle, game.toml, "
     "game_android.toml)", check_rom_pins),
    ("identity: BIOS pins all-emibios (game TOMLs, manifest pin, payload "
     "staging)", check_bios_pins),
    ("identity: committed emibios bin matches its TOML pin (16 KiB)",
     check_emibios_integrity),
    ("identity: engine accepts the clean-room BIOS (bios pin-set + "
     "public-guard exemption)", check_emibios_engine_acceptance),
    ("identity: save type/size mirror the desktop config", check_save_config),
    ("identity: optional .sav import on setup (issue #20)",
     check_save_picker_wiring),
    ("identity: saves/states land in the user-visible app dir (issue #6)",
     check_save_external_wiring),
    ("identity: logs/frag/coverage land in the user-visible app dir",
     check_logs_external_wiring),
    ("payload: state.toml keeps the widescreen feature enabled",
     check_state_toml),
    ("payload: state.toml matches the preloaded catalog manifest",
     check_state_catalog),
    ("payload: version bumped past stale installs",
     check_payload_version),
    ("payload: mods catalog + payload dirs staged", check_payload_wiring),
    ("payload: resize_view opt-in present", check_resize_view),
    ("hygiene: no ROM/save/APK/bin artifacts tracked", check_tracked_artifacts),
    ("hygiene: android outputs stay gitignored", check_ignored_outputs),
    ("scaffold: the Android base is SDL-free (raylib/NativeActivity)",
     check_scaffold_sdl_free),
    ("gate: clean fake-device run passes and pulls evidence", check_gate_clean),
    ("gate: SELF-HEAL runtime log fails the gate", check_gate_selfheal),
    ("gate: missing runtime log fails the gate", check_gate_missing_log),
    ("gate: crash-buffer entry fails the gate", check_gate_crash),
    ("gate: setup-still-resumed fails the gate", check_gate_setup_resumed),
    ("gate: stale installed APK fails the gate", check_gate_stale_version),
    ("gate: usage contract (--help 0, bad --wait 2, unknown option 2)",
     check_gate_usage),
    ("identity: launch-screen box art staged as a drawable",
     check_boxart_drawable_wiring),
    ("android: launch-screen skip classification uses the mutated args "
     "vector", check_launch_screen_skip_classification),
]


def main():
    suite = Suite()
    for name, fn in CHECKS:
        suite.run(name, fn)
    passed = 0
    for name, ok, detail in suite.results:
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             "" if ok else " — " + detail))
        if ok:
            passed += 1
    total = len(suite.results)
    if passed == total:
        print("android-static: OK (%d checks passed)" % total)
        return 0
    failing = ", ".join(name for name, ok, _ in suite.results if not ok)
    print("android-static: FAILED (%d/%d passed; failing: %s)"
          % (passed, total, failing))
    return 1


if __name__ == "__main__":
    sys.exit(main())
