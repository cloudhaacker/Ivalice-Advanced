// Backend-selection predicate, exercised in whichever configuration builds it.
//
// The closed-window test asserts host_using_raylib_backend() agrees with the
// compiled-in backend, but that test lives in the app build (SDL). This one is
// built in BOTH configurations so the predicate is also checked where it
// returns true -- otherwise "returns true" is never executed anywhere.

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

    // The factory must return something usable and independently owned.
    WindowBackend* a = host_make_backend();
    WindowBackend* b = host_make_backend();
    assert(a != nullptr && b != nullptr && a != b);
    assert(!a->is_open() && !b->is_open());
    delete a;
    delete b;

    std::printf("backend_select_tests: PASS (raylib=%d)\n",
                host_using_raylib_backend() ? 1 : 0);
    return 0;
}
