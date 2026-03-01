# SPLIT-1 — n8n Setup + Sphere Platform Credentials Node

**ТЗ-родитель:** TZ-09-n8n-Integration  
**Ветка:** `stage/9-n8n`  
**Задача:** `SPHERE-046`  
**Исполнитель:** Backend/Node.js  
**Оценка:** 1 день  
**Блокирует:** TZ-09 SPLIT-2, SPLIT-3, SPLIT-4

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-9` — НЕ в `sphere-platform`.
> Ветка `stage/9-n8n` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-9
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/9-n8n
pwd                          # ОБЯЗАНА содержать: sphere-stage-9
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-9 stage/9-n8n
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/9-n8n` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/9-n8n` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `n8n-nodes/nodes/` | `backend/main.py` 🔴 |
| `n8n-nodes/package.json` | `backend/core/` 🔴 |
| `backend/api/v1/n8n/` | `backend/websocket/` (TZ-03) 🔴 |
| `backend/services/n8n_*` | `backend/api/v1/scripts/` (TZ-04) 🔴 |
| `tests/test_n8n*` | `docker-compose*.yml` 🔴 |

---

## Цель Сплита

Создать npm-пакет custom n8n nodes `n8n-nodes-sphereplatform` с типом Credentials `SpherePlatformApi` и настроить Docker-окружение для n8n с подключением к бэкенду.

---

## Шаг 1 — Структура пакета

```
n8n-nodes-sphereplatform/
├── nodes/
│   ├── SphereDevicePool/
│   │   ├── SphereDevicePool.node.ts
│   │   └── SphereDevicePool.node.json
│   ├── SphereExecuteScript/
│   │   ├── SphereExecuteScript.node.ts
│   │   └── SphereExecuteScript.node.json
│   └── SphereEventTrigger/
│       ├── SphereEventTrigger.node.ts
│       └── SphereEventTrigger.node.json
├── credentials/
│   └── SpherePlatformApi.credentials.ts
├── package.json
└── tsconfig.json
```

```json
// package.json
{
  "name": "n8n-nodes-sphereplatform",
  "version": "1.0.0",
  "n8n": {
    "n8nNodesApiVersion": 1,
    "credentials": ["dist/credentials/SpherePlatformApi.credentials.js"],
    "nodes": [
      "dist/nodes/SphereDevicePool/SphereDevicePool.node.js",
      "dist/nodes/SphereExecuteScript/SphereExecuteScript.node.js",
      "dist/nodes/SphereEventTrigger/SphereEventTrigger.node.js"
    ]
  },
  "devDependencies": {
    "n8n-workflow": "^1.24.0",
    "typescript": "^5.3.3"
  }
}
```

---

## Шаг 2 — SpherePlatformApi Credentials

```typescript
// credentials/SpherePlatformApi.credentials.ts
import { ICredentialType, INodeProperties } from 'n8n-workflow';

export class SpherePlatformApi implements ICredentialType {
    name = 'spherePlatformApi';
    displayName = 'Sphere Platform API';
    documentationUrl = 'https://docs.sphere.local';
    
    properties: INodeProperties[] = [
        {
            displayName: 'Server URL',
            name: 'serverUrl',
            type: 'string',
            default: 'http://backend:8000',
            required: true,
            placeholder: 'https://api.sphere.local',
        },
        {
            displayName: 'API Key',
            name: 'apiKey',
            type: 'string',
            typeOptions: { password: true },
            default: '',
            required: true,
            description: 'API key в формате sphr_prod_<hex32>',
        },
        {
            displayName: 'Organization ID',
            name: 'orgId',
            type: 'string',
            default: '',
            required: true,
        },
    ];
}
```

---

## Шаг 3 — BaseNode helper

```typescript
// nodes/BaseNode.ts
import { IExecuteFunctions, NodeApiError } from 'n8n-workflow';

export async function sphereApiRequest(
    this: IExecuteFunctions,
    method: string,
    path: string,
    body?: object,
    qs?: Record<string, string>,
): Promise<any> {
    const creds = await this.getCredentials('spherePlatformApi');
    
    const options = {
        method,
        url: `${creds.serverUrl}/api/v1${path}`,
        headers: {
            'X-API-Key': creds.apiKey as string,
            'X-Org-ID': creds.orgId as string,
            'Content-Type': 'application/json',
        },
        body,
        qs,
        json: true,
    };
    
    try {
        return await this.helpers.request(options);
    } catch (error) {
        throw new NodeApiError(this.getNode(), error);
    }
}
```

---

## Шаг 4 — Docker Compose для n8n

```yaml
# docker-compose.yml (добавить сервис n8n)
services:
  n8n:
    image: n8nio/n8n:1.32.0
    restart: unless-stopped
    environment:
      - N8N_HOST=n8n
      - N8N_PORT=5678
      - N8N_PROTOCOL=http
      - N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}
      - DB_TYPE=postgresdb
      - DB_POSTGRESDB_HOST=postgres
      - DB_POSTGRESDB_PORT=5432
      - DB_POSTGRESDB_DATABASE=n8n
      - DB_POSTGRESDB_USER=n8n
      - DB_POSTGRESDB_PASSWORD=${N8N_DB_PASSWORD}
      # Подключение custom nodes
      - N8N_CUSTOM_EXTENSIONS=/home/node/.n8n/custom
      - NODE_PATH=/home/node/.n8n/custom/node_modules
    volumes:
      - n8n_data:/home/node/.n8n
      - ./n8n-nodes-sphereplatform:/home/node/.n8n/custom/node_modules/n8n-nodes-sphereplatform
    ports:
      - "5678:5678"
    depends_on:
      - postgres
    networks:
      - internal

volumes:
  n8n_data:
```

---

## Критерии готовности

- [ ] `npm run build` компилирует TypeScript без ошибок
- [ ] n8n запускается и видит credentials type `Sphere Platform API`
- [ ] `sphereApiRequest` добавляет X-API-Key и X-Org-ID заголовки
- [ ] NodeApiError оборачивает ошибки API (user-friendly сообщение в n8n)
- [ ] custom nodes том монтируется корректно в Docker
- [ ] Credentials с password type — значение скрыто в UI
