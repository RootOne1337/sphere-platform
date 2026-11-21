"""Keyboard-driven tests must never capture the operator's Windows cursor."""

# Apply before navigation, including to subframes. Keep keyboard input, WebGPU and recording active.
NO_POINTER_LOCK = """(() => {
    window.spherePointerLockAttempts = 0;
    Object.defineProperty(Element.prototype, 'requestPointerLock', {
        configurable: false, writable: false,
        value() {
            window.spherePointerLockAttempts++;
            return Promise.reject(new DOMException('Keyboard-only test', 'NotAllowedError'));
        }
    });
})();"""
