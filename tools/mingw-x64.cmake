# Cross toolchain: MinGW-w64 x86_64 → Windows (R2, issue #3).
#
# Used by tools/make_release.py --windows (and tools/win_cross_deps.py for
# the dependency prefix builds):
#   cmake -DCMAKE_TOOLCHAIN_FILE=tools/mingw-x64.cmake ...
#
# Same compiler triple the engine's MSYS2 path targets (x86_64-w64-mingw32):
# every WIN32/MINGW branch in gbarecompx/CMakeLists.txt and the game's
# CMakeLists.txt applies here. Static-dependency prefix (tools/win_cross_deps.py
# output — raylib only since the 2026-10 launcher track) is appended to
# CMAKE_PREFIX_PATH + FIND_ROOT_PATH so the engine's
# GBARECOMP_MINGW_PREFIX_UNIX discovery works.

set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR AMD64)

set(CMAKE_C_COMPILER x86_64-w64-mingw32-gcc)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)
set(CMAKE_RC_COMPILER x86_64-w64-mingw32-windres)
set(CMAKE_AR x86_64-w64-mingw32-ar)
set(CMAKE_RANLIB x86_64-w64-mingw32-ranlib)
set(CMAKE_STRIP x86_64-w64-mingw32-strip)

# Repository-relative locations (the toolchain file may be used from any
# build directory).
get_filename_component(_ffta_repo "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(FFTA_CROSS_PREFIX "${_ffta_repo}/cross-prefix"
    CACHE PATH "Static cross-dependency prefix (tools/win_cross_deps.py)")

list(APPEND CMAKE_PREFIX_PATH "${FFTA_CROSS_PREFIX}")

# Search order: our dependency prefix first, then the compiler's sysroot.
# Programs (build tools) stay native — NEVER would hide the host cmake/ninja.
set(CMAKE_FIND_ROOT_PATH "${FFTA_CROSS_PREFIX}" "/usr/x86_64-w64-mingw32")
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)