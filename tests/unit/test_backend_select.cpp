// Backend-selection predicate, exercised in whichever configuration builds it.
//
// Phase 4b made the selection binary: raylib ON builds the product backend,
// raylib OFF is the stub compile-check (host_make_backend() == nullptr). Both
// halves are asserted here, in whichever configuration builds this test.

#include "host_backend_factory.h"
#include "window_backend.h"

#include <cassert>
#include <cstdio>

int main() {
    using gbarecomp::WindowBackend;
    using gbarecomp::host_make_backend;
    using gbarecomp::host_using_raylib_backend;

#if defined(GBARECOMP_USE_RAYLIB)
    assert(host_using_raylib_backend());   // the case the SDL build never runs
#else
    assert(!host_using_raylib_backend());
#endif

#if defined(GBARECOMP_USE_RAYLIB)
    // The factory must return something usable and independently owned.
    WindowBackend* a = host_make_backend();
    WindowBackend* b = host_make_backend();
    assert(a != nullptr && b != nullptr && a != b);
    assert(!a->is_open() && !b->is_open());
    delete a;
    delete b;
#else
    // The stub compile-check build: no window backend at all.
    assert(host_make_backend() == nullptr);
#endif

    std::printf("backend_select_tests: PASS (raylib=%d)\n",
                host_using_raylib_backend() ? 1 : 0);
    return 0;
}
