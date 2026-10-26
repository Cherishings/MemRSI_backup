"""Use the original NativeWorld loop with relocated interpreter and EGL device."""
from libero_runtime import install_physics_runtime


if __name__ == '__main__':
    install_physics_runtime()
    from reliable_policy import install
    install()
    import native_world
    native_world.main()
