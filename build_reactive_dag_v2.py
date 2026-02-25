"""
Build reactive DAG v6 — ONE smart scan per cycle.

FIXES vs v5:
  - REMOVED check_game_pid (Lua condition was broken — ctx vars need ctx.xxx prefix)
    Shell pidof success/failure is sufficient: success = game running, failure = not running
  - FIXED watchdog counter: uses new increment_variable action (atomic Kotlin ctx update)
    instead of broken Lua increment (Lua ctx changes don't persist back to Kotlin)
  - ONE tap_first_visible scan with ALL candidates (was 3 separate UI dumps per cycle)
  - Conditional routing based on tapped_label for password/name special handling

FLOW:
  check_game_alive (pidof)
    success -> increment_counter -> check_watchdog -> scan_all
    failure -> launch_game -> wait -> scan_all
  scan_all (tap_first_visible: ALL candidates, ONE UI dump)
    tapped password_enter -> type password -> tap play -> sleep -> loop
    tapped edit_text_name -> type name -> tap surname -> type surname -> sleep -> loop
    tapped anything else  -> sleep -> loop (tap already done)
  watchdog: 28 cycles without password -> restart (stop + launch)
"""
import json, asyncio, asyncpg

DB_DSN = "postgresql://sphere:A80fXnwMLNmwa-ebjhUm5RV_2evs1BLq@localhost:5432/sphereplatform"
SCRIPT_VERSION_ID = "21e7f39a-f1ea-4b16-bbe0-c20f1f611e61"

MAX_CYCLES_BEFORE_RESTART = 28

# ── ALL candidates for tap_first_visible ──────────────────────────────────
# Order = priority: first match in the UI dump wins.
# password_enter and edit_text_name FIRST — they need follow-up typing.
# play_but and auto_switch LAST — only relevant after password is already handled.
ALL_CANDIDATES = [
    # ── Special: need follow-up typing (highest priority) ─────────────────
    {"selector": "com.br.top:id/password_enter",  "strategy": "id", "label": "pw"},
    {"selector": "com.br.top:id/edit_text_name",  "strategy": "id", "label": "name"},

    # ── SU / System permissions ───────────────────────────────────────────
    {"selector": "com.android.settings:id/remember_forever",               "strategy": "id", "label": "su_remember"},
    {"selector": "com.android.settings:id/allow",                          "strategy": "id", "label": "su_allow"},
    {"selector": "com.android.packageinstaller:id/permission_allow_button", "strategy": "id", "label": "perm_allow"},

    # ── Game buttons (tap-only, sorted by expected frequency) ─────────────
    {"selector": "com.br.top:id/button_ok",          "strategy": "id", "label": "button_ok"},
    {"selector": "com.br.top:id/button_repeat",      "strategy": "id", "label": "button_repeat"},
    {"selector": "com.br.top:id/but_skip",           "strategy": "id", "label": "but_skip"},
    {"selector": "com.br.top:id/but_continue",       "strategy": "id", "label": "but_continue"},
    {"selector": "com.br.top:id/butt",               "strategy": "id", "label": "butt"},
    {"selector": "com.br.top:id/br_servers_play",    "strategy": "id", "label": "servers_play"},
    {"selector": "com.br.top:id/button_play",        "strategy": "id", "label": "button_play"},
    {"selector": "com.br.top:id/play_butt",          "strategy": "id", "label": "play_butt"},
    {"selector": "com.br.top:id/male_butt",          "strategy": "id", "label": "male_butt"},
    {"selector": "com.br.top:id/arrow_right",        "strategy": "id", "label": "arrow_right"},
    {"selector": "com.br.top:id/dw_button_ok",       "strategy": "id", "label": "dw_ok"},
    {"selector": "com.br.top:id/dw_button_cancel",   "strategy": "id", "label": "dw_cancel"},
    {"selector": "com.br.top:id/all_servers_button",  "strategy": "id", "label": "all_servers"},
    {"selector": "com.br.top:id/reg_butt",           "strategy": "id", "label": "reg_butt"},
    {"selector": "com.br.top:id/invite_nick",        "strategy": "id", "label": "invite_nick"},
    {"selector": "com.br.top:id/list_servers_choose", "strategy": "id", "label": "servers_list"},
    {"selector": "com.br.top:id/edit2",              "strategy": "id", "label": "reg_pw"},
    {"selector": "com.br.top:id/edit3",              "strategy": "id", "label": "reg_pw_repeat"},

    # ── Login screen buttons (lower priority — password_enter comes first) ──
    {"selector": "com.br.top:id/play_but",           "strategy": "id", "label": "play_but"},
    {"selector": "com.br.top:id/auto_switch",        "strategy": "id", "label": "auto_switch"},

    # ── Text-based fallbacks ──────────────────────────────────────────────
    {"selector": "Далее",                             "strategy": "text", "label": "text_dalhe"},
    {"selector": "ЗАКРЫТЬ",                           "strategy": "text", "label": "text_close"},
    {"selector": "Нажмите, чтобы продолжить",         "strategy": "text", "label": "text_continue"},
    {"selector": "Открыть ×1",                        "strategy": "text", "label": "text_open_x1"},
]


def build_dag():
    nodes = []

    # ═══════════════════════════════════════════════════════════════════════
    # 1. START + init watchdog counter
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "start",
        "retry": 0,
        "action": {"type": "start"},
        "on_success": "init_counter",
        "on_failure": None,
        "timeout_ms": 1000
    })

    nodes.append({
        "id": "init_counter",
        "retry": 0,
        "action": {"type": "set_variable", "key": "cycle_count", "value": "0"},
        "on_success": "check_game_alive",
        "on_failure": None,
        "timeout_ms": 1000
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 2. Game alive check: pidof success = running, failure = not running
    #    NO separate Lua condition — shell exit code is sufficient!
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "check_game_alive",
        "retry": 0,
        "action": {
            "type": "shell",
            "command": "pidof com.br.top"
        },
        "on_success": "increment_counter",
        "on_failure": "launch_game",
        "timeout_ms": 3000
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 3. Watchdog: increment counter (Kotlin-side, persists across nodes)
    #    then check if limit exceeded
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "increment_counter",
        "retry": 0,
        "action": {"type": "increment_variable", "key": "cycle_count"},
        "on_success": "check_watchdog",
        "on_failure": "scan_all",
        "timeout_ms": 1000
    })

    nodes.append({
        "id": "check_watchdog",
        "retry": 0,
        "action": {
            "type": "condition",
            "code": f"return (tonumber(ctx.cycle_count) or 0) < {MAX_CYCLES_BEFORE_RESTART}",
            "on_true": "scan_all",
            "on_false": "restart_app"
        },
        "on_success": "scan_all",
        "on_failure": "restart_app",
        "timeout_ms": 2000
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 4. Launch game (game not running)
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "launch_game",
        "retry": 1,
        "action": {"type": "launch_app", "package": "com.br.top"},
        "on_success": "launch_game_wait",
        "on_failure": "launch_game_wait",
        "timeout_ms": 10000
    })

    nodes.append({
        "id": "launch_game_wait",
        "retry": 0,
        "action": {"type": "sleep", "ms": 8000},
        "on_success": "scan_all",
        "on_failure": None,
        "timeout_ms": 12000
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 5. Watchdog restart (game stuck for 28 cycles)
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "restart_app",
        "retry": 0,
        "action": {"type": "stop_app", "package": "com.br.top"},
        "on_success": "restart_sleep",
        "on_failure": "restart_sleep",
        "timeout_ms": 5000
    })

    nodes.append({
        "id": "restart_sleep",
        "retry": 0,
        "action": {"type": "sleep", "ms": 3000},
        "on_success": "restart_launch",
        "on_failure": None,
        "timeout_ms": 5000
    })

    nodes.append({
        "id": "restart_launch",
        "retry": 1,
        "action": {"type": "launch_app", "package": "com.br.top"},
        "on_success": "restart_wait",
        "on_failure": None,
        "timeout_ms": 10000
    })

    nodes.append({
        "id": "restart_wait",
        "retry": 0,
        "action": {"type": "sleep", "ms": 8000},
        "on_success": "reset_counter",
        "on_failure": None,
        "timeout_ms": 12000
    })

    nodes.append({
        "id": "reset_counter",
        "retry": 0,
        "action": {"type": "set_variable", "key": "cycle_count", "value": "0"},
        "on_success": "scan_all",
        "on_failure": None,
        "timeout_ms": 1000
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 6. SMART SCAN — ONE UI dump, tap first match, route by label
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "scan_all",
        "retry": 0,
        "action": {
            "type": "tap_first_visible",
            "candidates": ALL_CANDIDATES,
            "timeout_ms": 3000
        },
        "on_success": "route_pw",
        "on_failure": "sleep_wait",
        "timeout_ms": 8000
    })

    # ── Route: was it the password field? ─────────────────────────────────
    nodes.append({
        "id": "route_pw",
        "retry": 0,
        "action": {
            "type": "condition",
            "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'pw'",
            "on_true": "reset_counter_pw",
            "on_false": "route_name"
        },
        "on_success": "reset_counter_pw",
        "on_failure": "sleep_ok",
        "timeout_ms": 2000
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 7. PASSWORD FLOW: field already tapped by scan_all -> type -> play
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "reset_counter_pw",
        "retry": 0,
        "action": {"type": "set_variable", "key": "cycle_count", "value": "0"},
        "on_success": "sleep_before_type",
        "on_failure": None,
        "timeout_ms": 1000
    })

    nodes.append({
        "id": "sleep_before_type",
        "retry": 0,
        "action": {"type": "sleep", "ms": 500},
        "on_success": "type_pw",
        "on_failure": None,
        "timeout_ms": 3000
    })

    nodes.append({
        "id": "type_pw",
        "retry": 1,
        "action": {
            "type": "type_text",
            "text": "NaftaliN1337228",
            "clear_first": True
        },
        "on_success": "sleep_after_type",
        "on_failure": "sleep_ok",
        "timeout_ms": 8000
    })

    nodes.append({
        "id": "sleep_after_type",
        "retry": 0,
        "action": {"type": "sleep", "ms": 500},
        "on_success": "tap_play_login",
        "on_failure": None,
        "timeout_ms": 3000
    })

    nodes.append({
        "id": "tap_play_login",
        "retry": 1,
        "action": {
            "type": "tap_element",
            "selector": "com.br.top:id/play_but",
            "strategy": "id",
            "timeout_ms": 2000
        },
        "on_success": "sleep_ok",
        "on_failure": "sleep_ok",
        "timeout_ms": 5000
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 8. NAME FLOW: field already tapped by scan_all -> type name + surname
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "route_name",
        "retry": 0,
        "action": {
            "type": "condition",
            "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'name'",
            "on_true": "type_name",
            "on_false": "sleep_ok"
        },
        "on_success": "type_name",
        "on_failure": "sleep_ok",
        "timeout_ms": 2000
    })

    nodes.append({
        "id": "type_name",
        "retry": 1,
        "action": {
            "type": "type_text",
            "text": "Naftali",
            "clear_first": True
        },
        "on_success": "tap_surname",
        "on_failure": "sleep_ok",
        "timeout_ms": 8000
    })

    nodes.append({
        "id": "tap_surname",
        "retry": 0,
        "action": {
            "type": "tap_element",
            "selector": "com.br.top:id/edit_text_surname",
            "strategy": "id",
            "timeout_ms": 2000
        },
        "on_success": "type_surname",
        "on_failure": "sleep_ok",
        "timeout_ms": 5000
    })

    nodes.append({
        "id": "type_surname",
        "retry": 1,
        "action": {
            "type": "type_text",
            "text": "Nthree",
            "clear_first": True
        },
        "on_success": "sleep_ok",
        "on_failure": "sleep_ok",
        "timeout_ms": 8000
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 9. SLEEP + LOOP
    # ═══════════════════════════════════════════════════════════════════════
    nodes.append({
        "id": "sleep_ok",
        "retry": 0,
        "action": {"type": "sleep", "ms": 2000},
        "on_success": "check_game_alive",
        "on_failure": None,
        "timeout_ms": 5000
    })

    nodes.append({
        "id": "sleep_wait",
        "retry": 0,
        "action": {"type": "sleep", "ms": 3000},
        "on_success": "check_game_alive",
        "on_failure": None,
        "timeout_ms": 5000
    })

    # ═══════════════════════════════════════════════════════════════════════

    dag = {
        "entry_node": "start",
        "timeout_ms": 1800000,  # 30 min global
        "nodes": nodes
    }

    # Validate all targets exist
    node_ids = {n["id"] for n in nodes}
    for n in nodes:
        for key in ("on_success", "on_failure"):
            target = n.get(key)
            if target and target not in node_ids:
                raise ValueError(f"Node '{n['id']}' references missing target '{target}' in {key}")
        action = n.get("action", {})
        for key in ("on_true", "on_false"):
            target = action.get(key)
            if target and target not in node_ids:
                raise ValueError(f"Node '{n['id']}' action references missing target '{target}' in {key}")

    print(f"✅ DAG built: {len(nodes)} nodes, all targets valid")
    print("Nodes:", [n['id'] for n in nodes])
    return dag


async def deploy(dag):
    conn = await asyncpg.connect(DB_DSN)
    try:
        row = await conn.fetchrow(
            "UPDATE script_versions SET dag=$1 WHERE id=$2 RETURNING id",
            json.dumps(dag), SCRIPT_VERSION_ID
        )
        if row:
            print(f"✅ Deployed to script_versions.id={row['id']}")
        else:
            print("❌ No row updated — check SCRIPT_VERSION_ID")
    finally:
        await conn.close()


if __name__ == "__main__":
    dag = build_dag()
    print(json.dumps(dag, indent=2, ensure_ascii=False)[:500], "...")
    asyncio.run(deploy(dag))
