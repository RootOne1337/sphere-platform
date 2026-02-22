-- infrastructure/postgres/init.sql
-- Выполняется при первом старте PostgreSQL-контейнера.
-- Алембик создаёт таблицы. Этот файл только создаёт ДОПОЛНИТЕЛЬНЫЕ БД и настраивает роли.

-- БД n8n: Docker-образ создаёт только POSTGRES_DB=sphereplatform.
-- FIX: n8n требует базу «n8n» — без CREATE DATABASE n8n n8n упадёт с ошибкой «database "n8n" does not exist».
CREATE DATABASE n8n
    WITH OWNER = sphere
    ENCODING = 'UTF8'
    LC_COLLATE = 'C'
    LC_CTYPE = 'C'
    TEMPLATE = template0;

-- Расширение умолчания search_path для основной БД
\c sphereplatform
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- функции LIKE-поиска
CREATE EXTENSION IF NOT EXISTS "btree_gin"; -- композитные GIN-индексы
