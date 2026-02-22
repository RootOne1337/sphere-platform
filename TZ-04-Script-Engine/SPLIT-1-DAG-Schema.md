# SPLIT-1 — DAG JSON Schema + Валидация

**ТЗ-родитель:** TZ-04-Script-Engine  
**Ветка:** `stage/4-scripts`  
**Задача:** `SPHERE-021`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-04 SPLIT-2, SPLIT-3, SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-09 n8n и TZ-10 Visual Builder работают с копией DAG-схемы; при merge унифицировать

> [!CAUTION]
> **MERGE-3: DAG JSON CONTRACT — ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ**
>
> Этот файл определяет **каноническую** DAG JSON Schema. Все потребители ОБЯЗАНЫ использовать **ТОЛЬКО эту схему**:
>
> | Потребитель | Файл | Действие при merge |
> |------------|------|-------------------|
> | TZ-07 Android Agent | `DagRunner.kt` (SPLIT-3) | Десериализация через `kotlinx.serialization` с **идентичными полями** |
> | TZ-09 n8n | `ExecuteScript-Node.ts` (SPLIT-3) | Генерация DAG JSON через node params |
> | TZ-10 Frontend | `ScriptBuilder.tsx` (SPLIT-5) | Visual builder → JSON export |
>
> **Контрольные поля (НАРУШЕНИЕ = RUNTIME CRASH):**
>
> - `node.id` — string UUID, не int
> - `node.action.type` — exact Literal из `NodeAction` union
> - `node.next` — array of string IDs (не single string!)
> - `dag.nodes` — array, не dict/map
>
> **Тест-контракт при merge:**
>
> ```python
> # tests/test_dag_contract.py
> def test_dag_schema_matches_android():
>     """Если этот тест падает — DagRunner.kt рассинхронился."""
>     sample = load_fixture("dag_sample.json")
>     dag = DagGraph.model_validate_json(sample)
>     assert dag.nodes[0].action.type in VALID_ACTION_TYPES
>     assert isinstance(dag.nodes[0].next, list)
> ```

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-4` — НЕ в `sphere-platform`.
> Ветка `stage/4-scripts` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-4
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/4-scripts
pwd                          # ОБЯЗАНА содержать: sphere-stage-4
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-4 stage/4-scripts
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/4-scripts` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/4-scripts` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `backend/api/v1/scripts/` | `backend/main.py` 🔴 |
| `backend/api/v1/tasks/` | `backend/core/` 🔴 |
| `backend/services/script_*` | `backend/database/` 🔴 |
| `backend/schemas/dag*`, `backend/schemas/script*` | `backend/models/` (только TZ-00 создаёт!) 🔴 |
| `backend/services/task_*`, `backend/services/batch_*` | `backend/models/base_model.py` 🔴 |
| `tests/test_script*`, `tests/test_task*` | `docker-compose*.yml` 🔴 |

---

## Цель Сплита

Строгая JSON Schema для DAG-сценариев с валидацией через Pydantic. Все действия типизированы, циклические зависимости и недостижимые узлы запрещены.

---

## Шаг 1 — Node Types

```python
# backend/schemas/dag.py
from pydantic import BaseModel, model_validator, Field
from typing import Annotated, Literal, Union
from uuid import UUID

# ─────── Node Actions ───────
class TapAction(BaseModel):
    type: Literal["tap"]
    x: int = Field(ge=0, le=3840)
    y: int = Field(ge=0, le=2160)

class SwipeAction(BaseModel):
    type: Literal["swipe"]
    x1: int; y1: int; x2: int; y2: int
    duration_ms: int = Field(default=300, ge=50, le=10000)

class TypeTextAction(BaseModel):
    type: Literal["type_text"]
    text: str = Field(max_length=1000)
    clear_first: bool = False

class SleepAction(BaseModel):
    type: Literal["sleep"]
    ms: int = Field(ge=10, le=300_000)

class FindElementAction(BaseModel):
    type: Literal["find_element"]
    selector: str = Field(max_length=500, description="XPath or resource-id or text")
    strategy: Literal["xpath", "id", "text", "desc"] = "text"
    timeout_ms: int = Field(default=10_000, ge=100, le=120_000)
    fail_if_not_found: bool = True

class KeyEventAction(BaseModel):
    type: Literal["key_event"]
    keycode: int = Field(ge=0, le=400)

class ScriptAction(BaseModel):
    type: Literal["lua"]
    code: str = Field(max_length=50_000)

class ScreenshotAction(BaseModel):
    type: Literal["screenshot"]
    save_as: str | None = Field(None, pattern=r'^[\w\-]+$')

class ConditionAction(BaseModel):
    type: Literal["condition"]
    check: Literal["element_exists", "text_contains", "battery_above"]
    params: dict
    on_true: str   # next node id
    on_false: str  # next node id

class StartAction(BaseModel):
    type: Literal["start"]

class EndAction(BaseModel):
    type: Literal["end"]
    status: Literal["success", "failure"] = "success"

# Discriminated union всех типов
Action = Annotated[
    Union[
        TapAction, SwipeAction, TypeTextAction, SleepAction,
        FindElementAction, KeyEventAction, ScriptAction, ScreenshotAction,
        ConditionAction, StartAction, EndAction,
    ],
    Field(discriminator="type"),
]
```

---

## Шаг 2 — DAG Node & Graph

```python
class DAGNode(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z_][\w-]{0,63}$')
    action: Action
    on_success: str | None = None   # ID следующего узла
    on_failure: str | None = None   # ID при ошибке
    retry: int = Field(default=0, ge=0, le=5)
    timeout_ms: int = Field(default=30_000, ge=100, le=3_600_000)

class DAGScript(BaseModel):
    version: Literal["1.0"] = "1.0"
    name: str = Field(max_length=255)
    description: str | None = Field(None, max_length=2000)
    nodes: list[DAGNode] = Field(min_length=2, max_length=500)
    entry_node: str
    
    @model_validator(mode="after")
    def validate_dag(self) -> "DAGScript":
        node_ids = {n.id for n in self.nodes}
        
        # 1. Entry node должен существовать
        if self.entry_node not in node_ids:
            raise ValueError(f"entry_node '{self.entry_node}' not found in nodes")
        
        # 2. Все on_success/on_failure ссылки должны существовать
        for node in self.nodes:
            for ref_attr in ("on_success", "on_failure"):
                ref = getattr(node, ref_attr, None)
                if ref and ref not in node_ids:
                    raise ValueError(f"Node '{node.id}' references unknown node '{ref}'")
            
            # ConditionAction ссылки
            if isinstance(node.action, ConditionAction):
                for ref in (node.action.on_true, node.action.on_false):
                    if ref not in node_ids:
                        raise ValueError(f"Condition node '{node.id}' refs unknown '{ref}'")
        
        # 3. Проверить что нет бесконечных циклов (DFS)
        self._check_no_infinite_loops(node_ids)
        
        # 4. Все узлы достижимы от entry_node
        reachable = self._get_reachable(node_ids)
        unreachable = node_ids - reachable
        if unreachable:
            raise ValueError(f"Unreachable nodes detected: {unreachable}")
        
        return self
    
    def _build_adj(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for node in self.nodes:
            for attr in ("on_success", "on_failure"):
                ref = getattr(node, attr, None)
                if ref:
                    adj[node.id].append(ref)
            if isinstance(node.action, ConditionAction):
                adj[node.id] += [node.action.on_true, node.action.on_false]
        return adj
    
    def _get_reachable(self, all_ids: set) -> set:
        adj = self._build_adj()
        visited, stack = set(), [self.entry_node]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            stack.extend(adj.get(n, []))
        return visited
    
    def _check_no_infinite_loops(self, all_ids: set):
        """DFS для обнаружения циклов."""
        adj = self._build_adj()
        visited, rec_stack = set(), set()
        
        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for nb in adj.get(node, []):
                if nb not in visited:
                    if dfs(nb):
                        return True
                elif nb in rec_stack:
                    raise ValueError(f"Cycle detected at node '{nb}'")
            rec_stack.discard(node)
            return False
        
        for n in all_ids:
            if n not in visited:
                dfs(n)
```

---

## Шаг 3 — Lua Code Safety Check

```python
# backend/services/lua_safety.py

BLOCKED_LUA_PATTERNS = [
    r'\bos\s*\.\s*execute\b',
    r'\bio\s*\.\s*open\b',
    r'\bloadfile\b',
    r'\bdofile\b',
    r'\brequire\s*\(',
    r'\bload\s*\(',
]

def check_lua_safety(code: str) -> list[str]:
    """Проверить Lua код на опасные конструкции. Returns список нарушений."""
    violations = []
    for pattern in BLOCKED_LUA_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            violations.append(f"Blocked pattern: {pattern}")
    
    if len(code) > 50_000:
        violations.append("Lua code exceeds 50KB limit")
    
    return violations
```

---

## Критерии готовности

- [ ] DAG с циклом → `ValueError: Cycle detected`
- [ ] Недостижимый узел → `ValueError: Unreachable nodes`
- [ ] Ссылка на несуществующий узел → `ValueError: references unknown node`
- [ ] `os.execute()` в Lua коде → отклонено как небезопасное
- [ ] 500 узлов в DAG: валидация < 100ms
- [ ] ConditionAction с on_true/on_false корректно строит граф
