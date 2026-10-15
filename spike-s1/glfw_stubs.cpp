// Spike S1 stub — GLFW gamepad queries on the Memory platform.
//
// raylib 6's PLATFORM_MEMORY has no input system (§4.2), so the desktop GLFW
// gamepad path in raylib_backend.cpp (find_standard_pad / pump) can never see
// a pad here. The real desktop build gets these symbols from raylib's GLFW;
// the headless build links no GLFW, so the spike satisfies the linker with
// truthful "no gamepad" answers.
//
// This is spike-only scaffolding. Phase 2's `RaylibApi` seam (plan §2/§5.2
// item 4) makes the backend's raylib/GLFW calls injectable, and Phase 5's
// fake supplies exactly this behaviour without a stub TU.
extern "C" {

int glfwJoystickPresent(int) { return 0; }
int glfwJoystickIsGamepad(int) { return 0; }

struct RayGlfwGamepadStateStub;
int glfwGetGamepadState(int, RayGlfwGamepadStateStub*) { return 0; }

const char* glfwGetJoystickGUID(int) { return ""; }

}  // extern "C"
