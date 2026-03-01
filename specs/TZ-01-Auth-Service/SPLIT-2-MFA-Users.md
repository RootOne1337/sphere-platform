# SPLIT-2 — MFA (TOTP) + User Management

**ТЗ-родитель:** TZ-01-Auth-Service  
**Ветка:** `stage/1-auth`  
**Задача:** `SPHERE-007`  
**Исполнитель:** Backend  
**Оценка:** 1 рабочий день  
**Блокирует:** —

---

## Цель Сплита

TOTP-MFA (Google Authenticator совместимый), управление пользователями и организациями.

---

## Шаг 1 — TOTP MFA

```python
# backend/services/mfa_service.py
import pyotp
import qrcode
import io
import base64

class MFAService:
    
    def generate_totp_secret(self) -> str:
        return pyotp.random_base32()
    
    def get_totp_uri(self, secret: str, email: str) -> str:
        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=email,
            issuer_name="Sphere Platform",
        )
    
    def generate_qr_code(self, totp_uri: str) -> str:
        """Возвращает base64-encoded PNG QR-код."""
        img = qrcode.make(totp_uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    
    def verify_totp(self, secret: str, code: str) -> bool:
        """Проверяет TOTP код. Допуск ±30 секунд (1 окно)."""
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
```

```python
# backend/api/v1/auth.py — MFA endpoints
@router.post("/mfa/setup")
async def mfa_setup(
    current_user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache),
):
    """Шаг 1: Сгенерировать секрет и QR-код."""
    secret = mfa_service.generate_totp_secret()
    uri = mfa_service.get_totp_uri(secret, current_user.email)
    qr_base64 = mfa_service.generate_qr_code(uri)
    
    # Временно сохранить pending секрет в Redis (5 минут для завершения setup)
    await cache.redis.setex(f"mfa:pending:{current_user.id}", 300, secret)
    
    return {"qr_code": qr_base64, "secret": secret}

@router.post("/mfa/verify-setup")
async def mfa_verify_setup(
    code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache),
):
    """Шаг 2: Подтвердить что QR-код отсканирован корректно."""
    pending_secret = await cache.redis.get(f"mfa:pending:{current_user.id}")
    if not pending_secret:
        raise HTTPException(400, "MFA setup session expired")
    pending_secret = pending_secret.decode() if isinstance(pending_secret, bytes) else pending_secret
    
    if not mfa_service.verify_totp(pending_secret, code):
        raise HTTPException(400, "Invalid TOTP code")
    
    # Сохранить секрет в БД
    current_user.mfa_secret = pending_secret
    current_user.mfa_enabled = True
    await cache.redis.delete(f"mfa:pending:{current_user.id}")
    
    return {"message": "MFA enabled successfully"}

@router.post("/login/mfa")
async def login_with_mfa(
    body: MFALoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache),
):
    """Второй шаг логина если MFA включён."""
    # Получить pending auth state из Redis
    state = await cache.redis.get(f"mfa:auth:{body.state_token}")
    if not state:
        raise HTTPException(401, "MFA session expired")
    
    user_data = json.loads(state)
    user = await get_user_by_id(user_data["user_id"], db)
    
    if not mfa_service.verify_totp(user.mfa_secret, body.code):
        raise HTTPException(401, "Invalid MFA code")
    
    # Очистить state и выдать токены
    await cache.redis.delete(f"mfa:auth:{body.state_token}")
    return await _issue_tokens(user, response, db, cache)
```

---

## Шаг 2 — User Management API

```python
# backend/api/v1/users.py

@router.get("/users", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=100),
    current_user: User = Depends(require_roles(["org_admin", "org_owner"])),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(User)
        .where(User.org_id == current_user.org_id)
        .order_by(User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    users = (await db.execute(stmt)).scalars().all()
    return paginate(users, page, per_page)

@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    current_user: User = Depends(require_roles(["org_admin", "org_owner"])),
    db: AsyncSession = Depends(get_db),
    audit_svc: AuditLogService = Depends(get_audit_service),
):
    # Проверить что email уникален
    existing = await get_user_by_email(body.email, db)
    if existing:
        raise HTTPException(409, "User with this email already exists")
    
    user = User(
        org_id=current_user.org_id,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()
    
    # Audit log
    await audit_svc.log(
        action="user.create",
        resource_type="user",
        resource_id=str(user.id),
        org_id=current_user.org_id,
        user_id=current_user.id,
        status="success",
    )
    return user

@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    body: UpdateRoleRequest,
    current_user: User = Depends(require_roles(["org_owner"])),
    db: AsyncSession = Depends(get_db),
    audit_svc: AuditLogService = Depends(get_audit_service),
):
    """Только org_owner может менять роли."""
    user = await get_user_by_id(user_id, db)
    if not user or user.org_id != current_user.org_id:
        raise HTTPException(404)
    
    # Нельзя понизить последнего org_owner
    if user.role == "org_owner" and body.role != "org_owner":
        owners_count = await count_org_owners(current_user.org_id, db)
        if owners_count <= 1:
            raise HTTPException(400, "Cannot remove last org_owner")
    
    old_role = user.role
    user.role = body.role
    await audit_svc.log(
        action="user.role_change",
        resource_type="user",
        resource_id=str(user.id),
        org_id=current_user.org_id,
        user_id=current_user.id,
        old_values={"role": old_role},
        new_values={"role": body.role},
        status="success",
    )
```

---

## Критерии готовности

- [ ] MFA setup flow: generate QR → scan → verify code → enabled
- [ ] Login с MFA: password ok → state token → /login/mfa → tokens
- [ ] Неверный TOTP → 401
- [ ] Управление пользователями через API (CRUD)
- [ ] Нельзя удалить последнего org_owner
