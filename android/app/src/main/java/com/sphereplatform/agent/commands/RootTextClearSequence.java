package com.sphereplatform.agent.commands;

/** Focused editor shortcut. No clipboard read/write, text value or CUT command. */
public final class RootTextClearSequence {
    public interface Injector {
        boolean inject(int action, int keyCode, int metaState) throws Exception;
    }

    private static final int DOWN = 0;
    private static final int UP = 1;
    private static final int CTRL_LEFT = 113;
    private static final int A = 29;
    private static final int DELETE = 67;
    // Android META_CTRL_ON | META_CTRL_LEFT_ON.
    private static final int CTRL_META = 0x1000 | 0x2000;

    public static void clear(Injector injector) throws Exception {
        try {
            accepted(injector, DOWN, CTRL_LEFT, CTRL_META);
            accepted(injector, DOWN, A, CTRL_META);
            accepted(injector, UP, A, CTRL_META);
            accepted(injector, UP, CTRL_LEFT, 0);
            accepted(injector, DOWN, DELETE, 0);
            accepted(injector, UP, DELETE, 0);
        } finally {
            // A rejected/throwing injection can still have delivered its DOWN.
            // Attempt each release independently; never repeat the deletion.
            release(injector, A);
            release(injector, CTRL_LEFT);
            release(injector, DELETE);
        }
    }

    private static void accepted(Injector injector, int action, int code, int meta) throws Exception {
        if (!injector.inject(action, code, meta)) {
            throw new IllegalStateException("input_clear_injection_rejected");
        }
    }

    private static void release(Injector injector, int code) {
        try {
            injector.inject(UP, code, 0);
        } catch (Exception ignored) {
            // Preserve the first delivery failure without leaking platform output.
        }
    }

    private RootTextClearSequence() {}
}
