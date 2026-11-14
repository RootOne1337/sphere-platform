package com.sphereplatform.agent.commands;

/** One private pipe owns a gesture; explicit contact mode supports three stable IDs. */
public final class RootTouchSession {
    public static final int DOWN = 0, UP = 1, MOVE = 2, CANCEL = 3, HEARTBEAT = 4;
    public static final int KEY_TAP = 5, KEY_RELEASE = -1;
    public static final int KEY_DOWN = 6, KEY_UP = 7, KEY_RESET = 8;
    private static final int KEY_META_MASK = 0x711003;
    public static final long LEASE_MS = 1500;
    public enum Result {
        DISPATCHER_ACCEPTED(1), HEARTBEAT_ACCEPTED(2), CANCELLED(3), EXPIRED(4), REJECTED(5), UNKNOWN(6);
        public final int wireCode;
        Result(int wireCode) { this.wireCode = wireCode; }
    }
    public interface Injector {
        boolean inject(int action, int x, int y, long downTime, long eventTime) throws Exception;
    }
    public interface Geometry { boolean matches() throws Exception; }
    public interface KeyInjector {
        boolean inject(int action, int keyCode, int metaState, long downTime, long eventTime) throws Exception;
    }

    private final Injector injector;
    private final KeyInjector keyInjector;
    private final RootContactState contacts;
    private final Geometry geometry;
    private final int width, height;
    private int sequence;
    private long gesture, lastGesture, downTime, lastActivity, lastTime;
    private int x, y;
    private boolean held, closed, releaseUnknown;
    private boolean keyHeld;
    private int heldKey, heldMeta;
    private long keyDownTime;
    private final java.util.LinkedHashMap<Integer, long[]> keyboardHeld = new java.util.LinkedHashMap<>();

    public RootTouchSession(int width, int height, long now, Injector injector, Geometry geometry) {
        this(width, height, now, injector, geometry, null);
    }

    public RootTouchSession(int width, int height, long now, Injector injector, Geometry geometry, KeyInjector keyInjector) {
        this(width, height, now, injector, geometry, keyInjector, null);
    }

    public RootTouchSession(int width, int height, long now, Injector injector, Geometry geometry,
                            KeyInjector keyInjector, RootContactState.Injector contactInjector) {
        if (width < 1 || height < 1 || now < 0) throw new IllegalArgumentException("touch_configuration_invalid");
        this.width = width;
        this.height = height;
        this.injector = injector;
        this.keyInjector = keyInjector;
        this.contacts = contactInjector == null ? null : new RootContactState(contactInjector);
        this.geometry = geometry;
        lastActivity = lastTime = now;
    }

    public synchronized Result apply(int nextSequence, long nextGesture, int action, int nextX, int nextY, long now) {
        if (closed) return Result.REJECTED;
        Result expiry = tick(now);
        if (expiry != null) return expiry;
        if (RootContactState.event(action) || action == RootContactState.CANCEL_ALL)
            return contact(nextSequence, nextGesture, action, nextX, nextY, now);
        if (action == KEY_TAP) return keyTap(nextSequence, nextGesture, nextX, nextY, now);
        if (action >= KEY_DOWN && action <= KEY_RESET) return keyboard(nextSequence, nextGesture, action, nextX, nextY, now);
        // Gaps are permitted when MOVE is coalesced; duplicates/reordering are not.
        if (nextSequence <= sequence || nextSequence < 1 || action < DOWN || action > HEARTBEAT
                || nextX < 0 || nextX >= width || nextY < 0 || nextY >= height
                || (action == DOWN ? isHeld() || nextGesture <= lastGesture
                    : action == HEARTBEAT ? nextGesture != (isHeld() ? gesture : 0)
                    : !held || nextGesture != gesture)) {
            return fail(now, Result.REJECTED);
        }
        sequence = nextSequence;
        lastActivity = lastTime = now;
        if (action == HEARTBEAT) return Result.HEARTBEAT_ACCEPTED;
        if (action == CANCEL) {
            return release(now) ? Result.CANCELLED : fail(now, Result.UNKNOWN);
        }
        x = nextX;
        y = nextY;
        if (action == DOWN) {
            gesture = lastGesture = nextGesture;
            downTime = now;
            // A false/throwing reply can follow delivery. Cleanup must cover uncertain DOWN too.
            held = true;
        }
        try {
            if (!injector.inject(action, x, y, downTime, now)) return fail(now, Result.UNKNOWN);
            if (action == UP) held = false;
            return Result.DISPATCHER_ACCEPTED;
        } catch (Exception failure) {
            return fail(now, Result.UNKNOWN);
        }
    }

    private Result contact(int nextSequence, long nextGesture, int action, int nextX, int nextY, long now) {
        if (contacts == null || held || keyHeld || !keyboardHeld.isEmpty() || nextSequence < 1
                || nextSequence <= sequence || nextX < 0 || nextX >= width || nextY < 0 || nextY >= height
                || !contacts.valid(action) || (contacts.held() ? nextGesture != gesture : nextGesture <= lastGesture))
            return fail(now, Result.REJECTED);
        sequence = nextSequence; lastActivity = lastTime = now;
        if (!contacts.held()) gesture = lastGesture = nextGesture;
        try {
            if (!contacts.apply(action, nextX, nextY, now)) return fail(now, Result.UNKNOWN);
            return action == RootContactState.CANCEL_ALL ? Result.CANCELLED : Result.DISPATCHER_ACCEPTED;
        } catch (Exception failure) { return fail(now, Result.UNKNOWN); }
    }

    /** A finite Android navigation/edit key, on the same ordered native pipe as touch. */
    public static boolean supportedKey(int code) {
        switch (code) {
            case 3: case 4: case 187: case 82: // Home, Back, Recents, Menu
            case 67: case 112: case 66: case 61: // Backspace, Delete, Enter, Tab
            case 19: case 20: case 21: case 22: case 23: // D-pad
            case 111: case 122: case 123: case 92: case 93: // Escape, line/page navigation
            case 278: case 277: case 279: // Android copy/cut/paste
                return true;
            default: return false;
        }
    }

    /** Physical keyboard keys only. Power/volume and arbitrary Android actions stay excluded. */
    public static boolean supportedHardwareKey(int code) {
        return supportedKey(code) || code >= 7 && code <= 16 || code >= 29 && code <= 77
                || code == 81 || code >= 113 && code <= 118 || code == 124
                || code >= 131 && code <= 164;
    }
    public static boolean supportedMeta(int meta) { return meta >= 0 && (meta & ~KEY_META_MASK) == 0; }

    private Result keyboard(int nextSequence, long nextGesture, int action, int code, int meta, long now) {
        if (keyInjector == null || contacts != null && contacts.held() || nextSequence < 1 || nextSequence <= sequence || nextGesture != 0
                || !supportedMeta(meta) || (action == KEY_RESET ? code != 0 || meta != 0 : !supportedHardwareKey(code)))
            return fail(now, Result.REJECTED);
        sequence = nextSequence; lastActivity = lastTime = now;
        if (action == KEY_RESET) return releaseKeyboard(now) ? Result.DISPATCHER_ACCEPTED : fail(now, Result.UNKNOWN);
        long[] prior = keyboardHeld.get(code);
        if (action == KEY_DOWN) {
            // Repeated browser keydown must not inject duplicate DOWN edges.
            if (prior != null) return Result.DISPATCHER_ACCEPTED;
            if (keyboardHeld.size() >= 16) return fail(now, Result.REJECTED);
            keyboardHeld.put(code, new long[]{now, meta}); // Covers an uncertain native DOWN.
            try {
                return keyInjector.inject(DOWN, code, meta, now, now)
                        ? Result.DISPATCHER_ACCEPTED : fail(now, Result.UNKNOWN);
            } catch (Exception failure) { return fail(now, Result.UNKNOWN); }
        }
        // A stale UP after takeover/reset has no held edge to replay.
        if (prior == null) return Result.DISPATCHER_ACCEPTED;
        try {
            if (!keyInjector.inject(UP, code, meta, prior[0], now)) return fail(now, Result.UNKNOWN);
            keyboardHeld.remove(code);
            return Result.DISPATCHER_ACCEPTED;
        } catch (Exception failure) { return fail(now, Result.UNKNOWN); }
    }

    private boolean releaseKeyboard(long now) {
        for (java.util.Map.Entry<Integer, long[]> key : keyboardHeld.entrySet()) {
            try { releaseUnknown |= !keyInjector.inject(KEY_RELEASE, key.getKey(), (int) key.getValue()[1], key.getValue()[0], now); }
            catch (Exception failure) { releaseUnknown = true; }
        }
        keyboardHeld.clear();
        return !releaseUnknown;
    }

    private Result keyTap(int nextSequence, long nextGesture, int code, int meta, long now) {
        if (keyInjector == null || isHeld() || keyHeld || nextSequence < 1 || nextSequence <= sequence
                || nextGesture != 0 || !supportedKey(code) || meta != 0) return fail(now, Result.REJECTED);
        sequence = nextSequence;
        lastActivity = lastTime = now;
        heldKey = code; heldMeta = meta; keyDownTime = now;
        keyHeld = true; // A throwing/false DOWN may already have been delivered.
        try {
            if (!keyInjector.inject(DOWN, code, meta, now, now)) return fail(now, Result.UNKNOWN);
            if (!keyInjector.inject(UP, code, meta, now, now)) return fail(now, Result.UNKNOWN);
            keyHeld = false;
            return Result.DISPATCHER_ACCEPTED;
        } catch (Exception failure) { return fail(now, Result.UNKNOWN); }
    }

    /** Called locally even when the APK, WebSocket or browser no longer sends anything. */
    public synchronized Result tick(long now) {
        if (closed) return null;
        if (now < lastTime) return fail(lastTime, Result.REJECTED);
        lastTime = now;
        if (now - lastActivity >= LEASE_MS) return fail(now, Result.EXPIRED);
        try {
            if (!geometry.matches()) return fail(now, Result.REJECTED);
        } catch (Exception failure) {
            return fail(now, Result.UNKNOWN);
        }
        return null;
    }

    public synchronized Result close(long now) {
        if (closed) return releaseUnknown ? Result.UNKNOWN : Result.REJECTED;
        return fail(Math.max(now, lastTime), Result.CANCELLED);
    }

    /** Normal termination proves release, even when the owner expired or its input was rejected. */
    public synchronized int cleanupExitCode() {
        return closed && !isHeld() && !keyHeld && keyboardHeld.isEmpty() && !releaseUnknown ? 0 : 2;
    }

    private Result fail(long now, Result result) {
        closed = true;
        return release(now) ? result : Result.UNKNOWN;
    }

    private boolean release(long now) {
        releaseKeyboard(now);
        if (contacts != null) releaseUnknown |= !contacts.cancel(now);
        if (keyHeld) {
            keyHeld = false;
            try { releaseUnknown |= !keyInjector.inject(KEY_RELEASE, heldKey, heldMeta, keyDownTime, now); }
            catch (Exception failure) { releaseUnknown = true; }
        }
        if (!held) return !releaseUnknown;
        // Retire ownership before injection. An uncertain CANCEL must never invite a new DOWN.
        held = false;
        try { releaseUnknown |= !injector.inject(CANCEL, x, y, downTime, now); }
        catch (Exception failure) { releaseUnknown = true; }
        return !releaseUnknown;
    }

    public synchronized boolean isClosed() { return closed; }
    public synchronized boolean isHeld() { return held || contacts != null && contacts.held(); }
}
