# SPLIT-2 — Script CRUD API (Версионирование и поиск)

**ТЗ-родитель:** TZ-04-Script-Engine  
**Ветка:** `stage/4-scripts`  
**Задача:** `SPHERE-022`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-04 SPLIT-3, SPLIT-4
**Интеграция при merge:** TZ-10 Script Builder работает с mock CRUD API

> [!NOTE]
> **MERGE-10: При merge `stage/4-scripts` + `stage/9-n8n`:**
>
> - n8n `ExecuteScript-Node.ts` генерирует DAG JSON → должен использовать каноническую схему из TZ-04 SPLIT-1
> - Заменить hardcoded node types на импорт из `VALID_ACTION_TYPES`

---

## Цель Сплита

CRUD для скриптов с полным версионированием. Каждое обновление создаёт новую версию, не перезаписывая предыдущие. Поиск по тегам и имени.

---

## Шаг 1 — Script Models

> ⚠️ **ВНИМАНИЕ АГЕНТУ: НЕ СОЗДАВАЙ КЛАССЫ МОДЕЛЕЙ!**
>
> Модели `Script` и `ScriptVersion` **уже определены** в **TZ-00 SPLIT-2 Шаг 4** (файлы `backend/models/script.py`).
> Дублирование класса вызовет `SAWarning: Table 'scripts' already exists` и конфликт при merge!
>
> **Используй только импорты:**
>
> ```python
> from backend.models.script import Script, ScriptVersion
> from backend.models.task import Task, TaskStatus
> ```
>
> **Структура моделей (справка, не копируй):**
>
> - `Script`: `org_id`, `name`, `description`, `tags`, `is_archived`, `current_version_id`, `versions`
> - `ScriptVersion`: `script_id`, `version_number`, `dag`, `dag_hash`, `changelog`, `created_by`
>
> ✅ **Твоя задача в этом сплите:** только `backend/services/script_service.py` + `backend/api/v1/scripts/router.py`

---

## Шаг 2 — Script Service

```python
# backend/services/script_service.py
class ScriptService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_script(
        self, org_id: uuid.UUID, user_id: uuid.UUID, data: CreateScriptRequest
    ) -> Script:
        # Валидация DAG
        try:
            dag_obj = DAGScript.model_validate(data.dag)
        except ValidationError as e:
            raise HTTPException(422, detail=e.errors())
        
        dag_dict = dag_obj.model_dump()
        dag_hash = hashlib.sha256(json.dumps(dag_dict, sort_keys=True).encode()).hexdigest()
        
        script = Script(org_id=org_id, name=data.name, description=data.description, tags=data.tags)
        self.db.add(script)
        await self.db.flush()  # Получить ID
        
        version = ScriptVersion(
            script_id=script.id,
            version_number=1,
            dag=dag_dict,
            dag_hash=dag_hash,
            changelog=data.changelog or "Initial version",
            created_by=user_id,
        )
        self.db.add(version)
        await self.db.flush()
        
        script.current_version_id = version.id
        return script
    
    async def update_script(
        self,
        script_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        data: UpdateScriptRequest,
    ) -> Script:
        script = await self._get_script(script_id, org_id)
        
        # Метаданные
        if data.name is not None:
            script.name = data.name
        if data.description is not None:
            script.description = data.description
        if data.tags is not None:
            script.tags = data.tags
        
        # Новая версия если DAG изменился
        if data.dag is not None:
            dag_obj = DAGScript.model_validate(data.dag)
            dag_dict = dag_obj.model_dump()
            dag_hash = hashlib.sha256(json.dumps(dag_dict, sort_keys=True).encode()).hexdigest()
            
            # Дедупликация: не создавать версию если DAG не изменился
            current_v = await self.db.get(ScriptVersion, script.current_version_id)
            if current_v and current_v.dag_hash == dag_hash:
                return script   # DAG идентичен, только метаданные обновились
            
            last_num = await self._get_latest_version_number(script_id)
            new_version = ScriptVersion(
                script_id=script_id,
                version_number=last_num + 1,
                dag=dag_dict,
                dag_hash=dag_hash,
                changelog=data.changelog or f"Version {last_num + 1}",
                created_by=user_id,
            )
            self.db.add(new_version)
            await self.db.flush()
            script.current_version_id = new_version.id
        
        return script
    
    async def search_scripts(
        self,
        org_id: uuid.UUID,
        query: str | None = None,
        tags: list[str] | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Script], int]:
        stmt = (
            select(Script)
            .where(Script.org_id == org_id, Script.is_archived.is_(False))
        )
        
        if query:
            stmt = stmt.where(
                or_(
                    Script.name.ilike(f"%{query}%"),
                    Script.description.ilike(f"%{query}%"),
                )
            )
        
        if tags:
            # PostgreSQL Array contains ALL specified tags
            stmt = stmt.where(Script.tags.contains(tags))
        
        count = (await self.db.execute(
            select(func.count()).select_from(stmt.subquery())
        )).scalar_one()
        
        items = (await self.db.execute(
            stmt.order_by(Script.updated_at.desc())
               .offset((page-1)*per_page).limit(per_page)
        )).scalars().all()
        
        return items, count
    
    async def rollback_to_version(
        self, script_id: uuid.UUID, version_id: uuid.UUID, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> Script:
        """Откатить скрипт к более ранней версии (создаёт новую версию с тем же DAG)."""
        script = await self._get_script(script_id, org_id)
        old_version = await self.db.get(ScriptVersion, version_id)
        
        if not old_version or old_version.script_id != script_id:
            raise HTTPException(404, "Version not found")
        
        last_num = await self._get_latest_version_number(script_id)
        rollback_version = ScriptVersion(
            script_id=script_id,
            version_number=last_num + 1,
            dag=old_version.dag,
            dag_hash=old_version.dag_hash,
            changelog=f"Rollback to version {old_version.version_number}",
            # ⚠️ ИСПРАВЛЕНО: было script.org_id (UUID орга, не юзера) — неверный тип
            # Rollback вызывается из роутера с current_user доступным через зависимости
            # В реальном сервисе передавать user_id как параметр rollback_to_version()
            created_by=user_id,  # user_id должен быть параметром метода
        )
        self.db.add(rollback_version)
        await self.db.flush()
        script.current_version_id = rollback_version.id
        return script
```

---

## Шаг 3 — Router

```python
# backend/api/v1/scripts.py
router = APIRouter(prefix="/scripts", tags=["scripts"])

@router.get("", response_model=PaginatedResponse[ScriptResponse])
async def list_scripts(query: str | None = None, tags: list[str] = Query(default=[]), ...): ...

@router.post("", response_model=ScriptResponse, status_code=201)
async def create_script(body: CreateScriptRequest, ...): ...

@router.get("/{script_id}", response_model=ScriptDetailResponse)
async def get_script(script_id: uuid.UUID, include_dag: bool = True, ...): ...

@router.put("/{script_id}", response_model=ScriptResponse)
async def update_script(script_id: uuid.UUID, body: UpdateScriptRequest, ...): ...

@router.delete("/{script_id}", status_code=204)
async def archive_script(script_id: uuid.UUID, ...): ...   # Soft delete (archived)

@router.get("/{script_id}/versions", response_model=list[ScriptVersionResponse])
async def list_versions(script_id: uuid.UUID, ...): ...

@router.post("/{script_id}/versions/{version_id}/rollback", response_model=ScriptResponse)
async def rollback(script_id: uuid.UUID, version_id: uuid.UUID, ...):
    # ⚠️ Передавать current_user.id в rollback_to_version как user_id
    return await svc.rollback_to_version(script_id, version_id, current_user.org_id, current_user.id)
```

---

## Критерии готовности

- [ ] Создание скрипта с невалидным DAG → 422 с детальными ошибками
- [ ] Обновление с тем же DAG hash → новая версия НЕ создаётся
- [ ] Поиск по тегам через PostgreSQL GIN-индекс < 10ms
- [ ] Rollback к версии N → создаёт версию N+1 с тем же DAG
- [ ] Архивированные скрипты не появляются в списке (is_archived=false фильтр)
- [ ] Версии хранятся неизменяемо (нет UPDATE для ScriptVersion)
