"""
Build NEW reactive DAG: scan screen → see element → tap it → loop.
Uses tap_first_visible (one dump, all candidates, auto-tap).
Uses find_first_element + condition(Lua) for special routing (password, game-loaded).
"""
import json
import subprocess
import sys

DOCKER = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
SCRIPT_ID = "770bf806-6fb6-4e44-abc6-dc20b53c32ef"

# ══════════════════════════════════════════════════════════════════════════════
# ALL known clickable elements from the user's XPath list.
# Priority order matters — checked top-to-bottom in one XML dump.
# ══════════════════════════════════════════════════════════════════════════════

# ── Elements that mean "game loaded" (end condition) ──
# We check these FIRST via find_first_element before tapping anything.
END_CANDIDATES = [
    {"selector": "com.br.top:id/donate_header_value_rub", "strategy": "id", "label": "donate_header"},
    {"selector": "com.br.top:id/donate_header_value_bc",  "strategy": "id", "label": "donate_bc"},
]

# ── Password screen (special handling) ──
PASSWORD_CANDIDATES = [
    {"selector": "com.br.top:id/password_enter", "strategy": "id", "label": "password_enter"},
]

# ── All clickable elements (tap_first_visible candidates) ──
# Order: most important / blocking first
TAP_CANDIDATES = [
    # Permission dialog
    {"selector": "com.android.packageinstaller:id/permission_allow_button", "strategy": "id", "label": "perm_allow"},
    # OK button (various dialogs)
    {"selector": "com.br.top:id/button_ok", "strategy": "id", "label": "button_ok"},
    # "YES, LOAD" button
    {"selector": "com.br.top:id/button_repeat", "strategy": "id", "label": "button_repeat"},
    # SKIP button (registration)
    {"selector": "com.br.top:id/but_skip", "strategy": "id", "label": "but_skip"},
    # CONTINUE buttons
    {"selector": "com.br.top:id/but_continue", "strategy": "id", "label": "but_continue"},
    {"selector": "com.br.top:id/butt", "strategy": "id", "label": "butt_continue"},
    # Server play button (inside server selection)
    {"selector": "com.br.top:id/br_servers_play", "strategy": "id", "label": "servers_play"},
    # Main menu PLAY button
    {"selector": "com.br.top:id/button_play", "strategy": "id", "label": "button_play"},
    # Gender select (male)
    {"selector": "com.br.top:id/male_butt", "strategy": "id", "label": "male_butt"},
    # START GAME button
    {"selector": "com.br.top:id/play_butt", "strategy": "id", "label": "play_butt"},
    # Arrow right (tutorial/slider)
    {"selector": "com.br.top:id/arrow_right", "strategy": "id", "label": "arrow_right"},
    # "Choose" button (dialog)
    {"selector": "com.br.top:id/dw_button_ok", "strategy": "id", "label": "dw_ok"},
    # "Close" button (dialog)
    {"selector": "com.br.top:id/dw_button_cancel", "strategy": "id", "label": "dw_cancel"},
    # Auto switch
    {"selector": "com.br.top:id/auto_switch", "strategy": "id", "label": "auto_switch"},
    # "Далее" text button
    {"selector": "//*[@text='\u0414\u0430\u043b\u0435\u0435']", "strategy": "xpath", "label": "text_next"},
    # "ЗАКРЫТЬ" text button
    {"selector": "//*[@text='\u0417\u0410\u041a\u0420\u042b\u0422\u042c']", "strategy": "xpath", "label": "text_close"},
    # "Нажмите, чтобы продолжить"
    {"selector": "//*[@text='\u041d\u0430\u0436\u043c\u0438\u0442\u0435, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c']", "strategy": "xpath", "label": "text_tap_continue"},
    # "Открыть ×1"
    {"selector": "//*[@text='\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u00d71']", "strategy": "xpath", "label": "text_open"},
    # play_but (login screen PLAY)
    {"selector": "com.br.top:id/play_but", "strategy": "id", "label": "play_but_login"},
]


# ══════════════════════════════════════════════════════════════════════════════
# DAG NODES
# ══════════════════════════════════════════════════════════════════════════════

nodes = []

# ── Phase 1: Stop → Start → Wait ──
nodes.append({
    "id": "start",
    "retry": 0,
    "action": {"type": "start"},
    "on_success": "stop_app",
    "on_failure": None,
    "timeout_ms": 5000
})

nodes.append({
    "id": "stop_app",
    "retry": 1,
    "action": {"type": "stop_app", "package": "com.br.top"},
    "on_success": "sleep_stop",
    "on_failure": "sleep_stop",
    "timeout_ms": 10000
})

nodes.append({
    "id": "sleep_stop",
    "retry": 0,
    "action": {"ms": 2000, "type": "sleep"},
    "on_success": "launch_app",
    "on_failure": None,
    "timeout_ms": 5000
})

nodes.append({
    "id": "launch_app",
    "retry": 1,
    "action": {"type": "launch_app", "package": "com.br.top"},
    "on_success": "sleep_launch",
    "on_failure": "end_fail",
    "timeout_ms": 15000
})

nodes.append({
    "id": "sleep_launch",
    "retry": 0,
    "action": {"ms": 8000, "type": "sleep"},
    "on_success": "check_end",
    "on_failure": None,
    "timeout_ms": 12000
})

# ── Phase 2: SCAN LOOP ──

# Step 1: Check if we're already in the game (end condition)
nodes.append({
    "id": "check_end",
    "retry": 0,
    "action": {
        "type": "find_first_element",
        "candidates": END_CANDIDATES,
        "timeout_ms": 2000,
        "fail_if_not_found": False,
        "save_to": "end_check"
    },
    "on_success": "cond_in_game",
    "on_failure": "check_password",  # not found = move on
    "timeout_ms": 5000
})

# If find_first_element returned something, check if it's the game screen
nodes.append({
    "id": "cond_in_game",
    "retry": 0,
    "action": {
        "type": "condition",
        "code": "local r = ctx['end_check']; return r ~= nil and (r['label'] == 'donate_header' or r['label'] == 'donate_bc')",
        "on_true": "end_success",
        "on_false": "check_password"
    },
    "on_failure": "check_password",
    "on_success": None,
    "timeout_ms": 3000
})

# Step 2: Check if password screen is visible
nodes.append({
    "id": "check_password",
    "retry": 0,
    "action": {
        "type": "find_first_element",
        "candidates": PASSWORD_CANDIDATES,
        "timeout_ms": 2000,
        "fail_if_not_found": False,
        "save_to": "pw_check"
    },
    "on_success": "cond_password",
    "on_failure": "scan_and_tap",  # no password field = go to generic scan
    "timeout_ms": 5000
})

nodes.append({
    "id": "cond_password",
    "retry": 0,
    "action": {
        "type": "condition",
        "code": "local r = ctx['pw_check']; return r ~= nil and r['label'] == 'password_enter'",
        "on_true": "handle_password",
        "on_false": "scan_and_tap"
    },
    "on_failure": "scan_and_tap",
    "on_success": None,
    "timeout_ms": 3000
})

# ── Password special flow: tap field → type password → tap PLAY ──
nodes.append({
    "id": "handle_password",
    "retry": 1,
    "action": {
        "type": "tap_element",
        "selector": "com.br.top:id/password_enter",
        "strategy": "id"
    },
    "on_success": "sleep_pw_tap",
    "on_failure": "scan_and_tap",
    "timeout_ms": 10000
})

nodes.append({
    "id": "sleep_pw_tap",
    "retry": 0,
    "action": {"ms": 500, "type": "sleep"},
    "on_success": "type_password",
    "on_failure": None,
    "timeout_ms": 3000
})

nodes.append({
    "id": "type_password",
    "retry": 1,
    "action": {"type": "type_text", "text": "NaftaliN1337228"},
    "on_success": "sleep_pw_type",
    "on_failure": "scan_and_tap",
    "timeout_ms": 10000
})

nodes.append({
    "id": "sleep_pw_type",
    "retry": 0,
    "action": {"ms": 500, "type": "sleep"},
    "on_success": "tap_play_login",
    "on_failure": None,
    "timeout_ms": 3000
})

nodes.append({
    "id": "tap_play_login",
    "retry": 2,
    "action": {
        "type": "tap_element",
        "selector": "com.br.top:id/play_but",
        "strategy": "id"
    },
    "on_success": "sleep_after_action",
    "on_failure": "sleep_after_action",
    "timeout_ms": 10000
})

# ── Step 3: Generic scan — tap first visible element from ALL candidates ──
nodes.append({
    "id": "scan_and_tap",
    "retry": 0,
    "action": {
        "type": "tap_first_visible",
        "candidates": TAP_CANDIDATES,
        "timeout_ms": 5000
    },
    "on_success": "sleep_after_action",
    "on_failure": "sleep_nothing_found",  # nothing clickable found
    "timeout_ms": 10000
})

# After tapping something → small wait → loop back to check_end
nodes.append({
    "id": "sleep_after_action",
    "retry": 0,
    "action": {"ms": 3000, "type": "sleep"},
    "on_success": "check_end",
    "on_failure": None,
    "timeout_ms": 5000
})

# Nothing found on screen → longer wait → retry
nodes.append({
    "id": "sleep_nothing_found",
    "retry": 0,
    "action": {"ms": 5000, "type": "sleep"},
    "on_success": "check_end",
    "on_failure": None,
    "timeout_ms": 8000
})

# ── End nodes ──
nodes.append({
    "id": "end_success",
    "retry": 0,
    "action": {"type": "end"},
    "on_success": None,
    "on_failure": None,
    "timeout_ms": 5000
})

nodes.append({
    "id": "end_fail",
    "retry": 0,
    "action": {"type": "end"},
    "on_success": None,
    "on_failure": None,
    "timeout_ms": 5000
})

# ══════════════════════════════════════════════════════════════════════════════
# Build DAG
# ══════════════════════════════════════════════════════════════════════════════

dag = {
    "entry_node": "start",
    "nodes": nodes,
    "timeout_ms": 600000  # 10 minutes global timeout
}

print(f"Total nodes: {len(nodes)}")

# Verify all nodes are reachable
node_map = {n['id']: n for n in nodes}
visited = set()
queue = ["start"]
while queue:
    nid = queue.pop(0)
    if nid in visited or not nid:
        continue
    visited.add(nid)
    n = node_map.get(nid)
    if not n:
        print(f"  WARNING: node '{nid}' referenced but not defined!")
        continue
    for key in ['on_success', 'on_failure']:
        nx = n.get(key)
        if nx and nx not in visited:
            queue.append(nx)
    a = n.get('action', {})
    for key in ['on_true', 'on_false']:
        nx = a.get(key)
        if nx and nx not in visited:
            queue.append(nx)

unreachable = set(node_map.keys()) - visited
if unreachable:
    print(f"WARNING: UNREACHABLE: {unreachable}")
else:
    print("All nodes reachable!")

# Show the flow
print("\n=== REACTIVE LOOP FLOW ===")
print("Phase 1: start → stop_app → sleep(2s) → launch_app → sleep(8s)")
print("Phase 2 (LOOP):")
print("  check_end → donate found? → end_success")
print("  check_end → not found → check_password")
print("  check_password → found → tap_field → type_password → tap_play → sleep → LOOP")
print("  check_password → not found → scan_and_tap (all elements)")
print("  scan_and_tap → tapped something → sleep(3s) → LOOP")
print("  scan_and_tap → nothing found → sleep(5s) → LOOP")

# Show candidates
print(f"\n=== TAP CANDIDATES ({len(TAP_CANDIDATES)}) ===")
for c in TAP_CANDIDATES:
    sel = c['selector']
    if len(sel) > 50:
        sel = sel[:50] + "..."
    print(f"  {c['label']:20s} {c['strategy']:6s} {sel}")

# ── Write to DB ──
dag_json = json.dumps(dag, ensure_ascii=False)
dag_escaped = dag_json.replace("'", "''")
sql = f"UPDATE script_versions SET dag = '{dag_escaped}' WHERE script_id = '{SCRIPT_ID}';"

result = subprocess.run(
    [DOCKER, "--context", "default", "exec", "-i", "sphere-platform-postgres-1",
     "psql", "-U", "sphere", "-d", "sphereplatform", "-c", sql],
    capture_output=True, text=True, encoding='utf-8'
)
if result.returncode != 0:
    print("ERROR updating DAG:", result.stderr)
    sys.exit(1)

print(f"\nDB update: {result.stdout.strip()}")
print("\n✓ REACTIVE DAG deployed!")
