package com.sphereplatform.agent.commands;

/** One private pipe owns one single-finger gesture. No Android dependency in the state machine. */
public final class RootTouchSession {
    public static final int DOWN = 0, UP = 1, MOVE = 2, CANCEL = 3, HEARTBEAT = 4;
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

    private final Injector injector;
    private final Geometry geometry;
    private final int width, height;
    private int sequence;
    private long gesture, lastGesture, downTime, lastActivity, lastTime;
    private int x, y;
    private boolean held, closed;

    public RootTouchSession(int width, int height, long now, Injector injector, Geometry geometry) {
        if (width < 1 || height < 1 || now < 0) throw new IllegalArgumentException("touch_configuration_invalid");
        this.width = width;
        this.height = height;
        this.injector = injector;
        this.geometry = geometry;
        lastActivity = lastTime = now;
    }

    public synchronized Result apply(int nextSequence, long nextGesture, int action, int nextX, int nextY, long now) {
        if (closed) return Result.REJECTED;
        Result expiry = tick(now);
        if (expiry != null) return expiry;
        // Gaps are permitted when MOVE is coalesced; duplicates/reordering are not.
        if (nextSequence <= sequence || nextSequence < 1 || action < DOWN || action > HEARTBEAT
                || nextX < 0 || nextX >= width || nextY < 0 || nextY >= height
                || (action == DOWN ? held || nextGesture <= lastGesture
                    : action == HEARTBEAT ? nextGesture != (held ? gesture : 0)
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
        if (closed) return Result.REJECTED;
        return fail(Math.max(now, lastTime), Result.CANCELLED);
    }

    private Result fail(long now, Result result) {
        closed = true;
        return release(now) ? result : Result.UNKNOWN;
    }

    private boolean release(long now) {
        if (!held) return true;
        // Retire ownership before injection. An uncertain CANCEL must never invite a new DOWN.
        held = false;
        try { return injector.inject(CANCEL, x, y, downTime, now); }
        catch (Exception failure) { return false; }
    }

    public synchronized boolean isClosed() { return closed; }
    public synchronized boolean isHeld() { return held; }
}
