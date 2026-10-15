# Spike S1 (plan §4.3): raylib 6 headless enablement proof.
#
# Route: raylib's own CMake supports `PLATFORM=Memory` — cmake/LibraryConfigurations.cmake
# sets PLATFORM_CPP=PLATFORM_MEMORY + GRAPHICS=GRAPHICS_API_OPENGL_SOFTWARE and
# cmake/CompileDefinitions.cmake exports both PUBLIC on the raylib target. No
# injected defines, no second build tree, no Makefile needed.
#
# Builds the REAL RaylibBackend (same sources the tree builds) against that
# raylib and links the assertion harness. No display, no GPU.
cmake_minimum_required(VERSION 3.22)
project(s1_headless CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(FW_ROOT "${CMAKE_CURRENT_LIST_DIR}/../gbarecompx" CACHE PATH
    "gbarecomp-raylib tree")
if(NOT EXISTS "${FW_ROOT}/CMakeLists.txt")
    message(FATAL_ERROR "gbarecompx tree not found at ${FW_ROOT}")
endif()

# Reuse the pinned source the app build already fetched (read-only use).
set(RAYLIB_SRC "" CACHE PATH "raylib 6 source tree (pin dbc56a87...)")
if(NOT EXISTS "${RAYLIB_SRC}/CMakeLists.txt")
    message(FATAL_ERROR "Pass -DRAYLIB_SRC=<raylib 6 source tree>")
endif()

set(PLATFORM "Memory" CACHE STRING "" FORCE)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
add_subdirectory("${RAYLIB_SRC}" raylib_build)

# Same source list the Android spike proved (rab_* is header-inlined in
# recomp_audio_drc.h, so no bridge TU is needed).
add_executable(s1_headless
    s1_headless.cpp
    glfw_stubs.cpp   # Memory has no input system; see the file header
    "${FW_ROOT}/src/runtime/raylib_backend.cpp"
    "${FW_ROOT}/src/runtime/recomp_audio_drc.cpp"
    "${FW_ROOT}/src/runtime/color_lut.cpp"
    "${FW_ROOT}/src/runtime/touch_input.cpp")
target_include_directories(s1_headless PRIVATE "${FW_ROOT}/src/runtime")
target_compile_definitions(s1_headless PRIVATE GBARECOMP_USE_RAYLIB=1)
# raylib's Memory platform names no system libs (only winmm on Windows);
# miniaudio + std::thread + dlopen need these on Linux.
target_link_libraries(s1_headless PRIVATE raylib m pthread dl)
