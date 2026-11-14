package com.sphereplatform.agent.commands;

/** Three stable contact IDs on one physical gesture. Pure Java; no Android authority. */
public final class RootContactState {
    public static final int MAX_CONTACTS = 3, CANCEL_ALL = 28;
    public interface Injector {
        boolean inject(int action, int[] ids, int[] xs, int[] ys, long down, long at) throws Exception;
    }
    private final Injector injector;
    private final java.util.LinkedHashMap<Integer, int[]> contacts = new java.util.LinkedHashMap<>();
    private long downTime;
    private boolean releaseUnknown;

    public RootContactState(Injector injector) { this.injector = injector; }
    public static int encode(int id, int action) {
        return id >= 0 && id < MAX_CONTACTS && action >= 0 && action <= 2 ? 16 + id * 4 + action : -1;
    }
    public static boolean event(int value) { return value >= 16 && value <= 26 && (value - 16) % 4 <= 2; }
    public static int id(int value) { return event(value) ? (value - 16) / 4 : -1; }
    public static int action(int value) { return event(value) ? (value - 16) % 4 : -1; }
    public boolean held() { return !contacts.isEmpty(); }

    public boolean valid(int encoded) {
        if (encoded == CANCEL_ALL) return held();
        int id = id(encoded), action = action(encoded);
        return id >= 0 && (action == 0 ? !contacts.containsKey(id) && contacts.size() < MAX_CONTACTS
                : contacts.containsKey(id));
    }

    /** Caller validates dimensions, sequence, lease, capture and gesture identity. */
    public boolean apply(int encoded, int x, int y, long now) throws Exception {
        if (!valid(encoded) || releaseUnknown) return false;
        if (encoded == CANCEL_ALL) return cancel(now);
        int id = id(encoded), action = action(encoded);
        boolean first = contacts.isEmpty();
        if (first) downTime = now;
        // Reserve an uncertain DOWN before calling the privileged dispatcher.
        contacts.put(id, new int[]{x, y});
        int index = new java.util.ArrayList<>(contacts.keySet()).indexOf(id);
        int androidAction = action == 0 ? (first ? 0 : 5 | index << 8)
                : action == 1 ? (contacts.size() == 1 ? 1 : 6 | index << 8) : 2;
        boolean accepted = inject(androidAction, now);
        if (!accepted) return false; // Caller must retire and cancel uncertain state.
        if (action == 1) contacts.remove(id);
        return true;
    }

    public boolean cancel(long now) {
        if (contacts.isEmpty()) return !releaseUnknown;
        try { releaseUnknown |= !inject(3, now); }
        catch (Exception failure) { releaseUnknown = true; }
        finally { contacts.clear(); }
        return !releaseUnknown;
    }

    private boolean inject(int action, long now) throws Exception {
        int[] ids = new int[contacts.size()], xs = new int[ids.length], ys = new int[ids.length];
        int at = 0;
        for (java.util.Map.Entry<Integer, int[]> contact : contacts.entrySet()) {
            ids[at] = contact.getKey(); xs[at] = contact.getValue()[0]; ys[at] = contact.getValue()[1]; at++;
        }
        return injector.inject(action, ids, xs, ys, downTime, now);
    }
}
