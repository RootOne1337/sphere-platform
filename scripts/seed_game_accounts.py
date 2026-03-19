#!/usr/bin/env python3
"""
scripts/seed_game_accounts.py

Засевает тестовые игровые аккаунты Black Russia в базу через API.
Генерирует уникальные мужские русские ники на английском: Имя_Фамилия
(формат игры — без цифр, без спецсимволов, только латиница с _).

Использование:
    python scripts/seed_game_accounts.py                        # 25 аккаунтов
    python scripts/seed_game_accounts.py --count 100            # 100 аккаунтов
    python scripts/seed_game_accounts.py --api-url http://...   # кастомный URL
    python scripts/seed_game_accounts.py --purge                # удалить все + создать

Требования:
    — httpx (pip install httpx)
    — Запущенный backend с DEV_SKIP_AUTH=true
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import random
import string
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("❌  httpx не установлен. Выполните: pip install httpx")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# Русские мужские имена — транслитерация на английский
# 150+ уникальных имён для максимальной вариативности
# ═══════════════════════════════════════════════════════════════════════════════

MALE_FIRST_NAMES: list[str] = [
    # Классические
    "Aleksandr", "Aleksey", "Andrey", "Anton", "Artem", "Artyom",
    "Boris", "Bogdan", "Bronislav",
    "Vadim", "Valentin", "Valeriy", "Vasiliy", "Viktor", "Vitaliy",
    "Vladimir", "Vladislav", "Vyacheslav",
    "Gavriil", "Gennadiy", "Georgiy", "German", "Gleb", "Grigoriy",
    "Daniil", "David", "Denis", "Dmitriy", "Dominik",
    "Evgeniy", "Egor", "Efim", "Elisey",
    "Zakhar", "Zinovy",
    "Ivan", "Igor", "Ilya", "Innokentiy",
    "Kirill", "Klim", "Kondrat", "Konstantin", "Kuzma",
    "Lavrentiy", "Lazar", "Leonid", "Lev", "Luka",
    "Makar", "Maksim", "Mark", "Matvey", "Mikhail", "Marat", "Miroslav",
    "Nikita", "Nikolay", "Nikifor",
    "Oleg", "Osip",
    "Pavel", "Petr", "Platon", "Prokhor",
    "Radmir", "Ratmir", "Renat", "Robert", "Rodion", "Roman", "Rostislav", "Ruslan", "Ruben",
    "Savva", "Saveliy", "Semyon", "Sergey", "Stanislav", "Stepan", "Svyatoslav",
    "Taras", "Timofey", "Timur", "Trofim", "Tikhon",
    "Fedor", "Feliks", "Filipp",
    "Eduard", "Emil", "Ernest", "Erik",
    "Yuriy", "Yakov", "Yaroslav",
    # Дополнительные
    "Adrian", "Albert", "Anatoliy", "Apollon", "Arkadiy", "Arseny",
    "Veniamin", "Vikenty", "Vsevolod",
    "Demyan", "Danila", "Dorofey",
    "Ermolai", "Erast",
    "Ignat", "Ippolit", "Iosif",
    "Kazimir", "Karp", "Korneliy",
    "Leonty",
    "Mefodiy", "Mitrofan", "Modest",
    "Nestor", "Naum", "Nazar",
    "Panfil", "Potap", "Prokopiy",
    "Rafail", "Spartak",
    "Terenty",
    "Faddey", "Foma",
    "Hariton",
    "Yulian",
    # Современные популярные
    "Amir", "Arsen", "Damir", "Daniyar", "Eldar",
    "Kamil", "Leon", "Milan", "Miron", "Rafael",
    "Samir", "Sultan", "Tamerlan", "Farid", "Shamil",
]

MALE_LAST_NAMES: list[str] = [
    # Топ-100+ русских фамилий (транслитерация)
    "Ivanov", "Petrov", "Sidorov", "Smirnov", "Kuznetsov",
    "Popov", "Vasiliev", "Sokolov", "Mikhaylov", "Novikov",
    "Fyodorov", "Morozov", "Volkov", "Alekseev", "Lebedev",
    "Semenov", "Egorov", "Pavlov", "Kozlov", "Stepanov",
    "Nikolaev", "Orlov", "Andreev", "Makarov", "Nikitin",
    "Zakharov", "Zaitsev", "Solovyov", "Borisov", "Yakovlev",
    "Grigoriev", "Romanov", "Vorobyov", "Sergeev", "Kuzmin",
    "Frolov", "Aleksandrov", "Dmitriev", "Korolev", "Gusev",
    "Kiselev", "Ilyin", "Maksimov", "Polyakov", "Sorokin",
    "Vinogradov", "Kovalev", "Belov", "Medvedev", "Antonov",
    "Tarasov", "Zhukov", "Baranov", "Filippov", "Komarov",
    "Davydov", "Belyakov", "Gerasimov", "Bogdanov", "Osipov",
    "Naumov", "Fadeev", "Kulikov", "Maslov", "Denisov",
    "Kazakov", "Tikhonov", "Shcherbakov", "Kalinin", "Burov",
    "Lobanov", "Lukin", "Kornilov", "Matveev", "Tkachev",
    "Belyaev", "Sizov", "Fomin", "Lobachev", "Komissarov",
    "Avdeev", "Ignatov", "Nesterov", "Markov", "Vlasov",
    "Klimov", "Ponomarev", "Kirillov", "Safronov", "Savchenko",
    "Chernov", "Abramov", "Gladkov", "Kolesnikov", "Krylov",
    "Shestakov", "Eliseev", "Loginov", "Gromov", "Yefimov",
    # Дополнительные
    "Zubarev", "Biryukov", "Drozdov", "Zotov", "Kalashnikov",
    "Kudryavtsev", "Laptev", "Myasnikov", "Panfilov", "Ryzhov",
    "Suslov", "Terentyev", "Usov", "Kharitonov", "Tsvetkov",
    "Sharov", "Yakushev", "Shmelev",
    "Bolshakov", "Gorbunov", "Dementyev", "Ermakov", "Zhdanov",
    "Zinchenko", "Karpov", "Litvinov", "Murashov", "Noskov",
    "Prokhorov", "Rybakov", "Starkov", "Trofimov", "Ushakov",
    "Chistov", "Shapovalov", "Shirokov",
]


def generate_password() -> str:
    """Генерирует безопасный пароль 12 символов (буквы + цифры)."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=12))


def generate_unique_nicks(count: int) -> list[str]:
    """
    Генерирует count уникальных ников формата Имя_Фамилия.
    Гарантия уникальности через перемешивание всех комбинаций.
    Общий пул: ~150 имён × ~130 фамилий = ~19 500 уникальных комбинаций.
    """
    all_combos = [
        f"{first}_{last}"
        for first, last in itertools.product(MALE_FIRST_NAMES, MALE_LAST_NAMES)
    ]
    random.shuffle(all_combos)

    if count > len(all_combos):
        print(f"⚠️  Запрошено {count}, но максимум уникальных комбинаций: {len(all_combos)}")
        count = len(all_combos)

    return all_combos[:count]


# ─── Серверы ──────────────────────────────────────────────────────────────────

def load_servers() -> list[dict]:
    """Загружает список серверов из servers.json (id + name)."""
    servers_path = Path(__file__).parent.parent / "backend" / "core" / "servers.json"
    if not servers_path.exists():
        return [{"id": 1, "name": "RED"}, {"id": 2, "name": "GREEN"}, {"id": 3, "name": "BLUE"}]
    with open(servers_path, encoding="utf-8") as f:
        return json.load(f)


# ─── Основная логика ─────────────────────────────────────────────────────────

async def purge_all(client: httpx.AsyncClient) -> int:
    """Удаляет все существующие аккаунты через API."""
    deleted = 0
    while True:
        r = await client.get("/game-accounts", params={"page": 1, "per_page": 100})
        if r.status_code != 200:
            break
        data = r.json()
        items = data.get("items", [])
        if not items:
            break
        for acc in items:
            dr = await client.delete(f"/game-accounts/{acc['id']}")
            if dr.status_code in (200, 204):
                deleted += 1
    return deleted


async def seed_accounts(api_url: str, count: int, do_purge: bool = False) -> None:
    """Создаёт указанное количество тестовых аккаунтов через API."""
    servers = load_servers()
    nicks = generate_unique_nicks(count)
    created = 0
    failed = 0

    async with httpx.AsyncClient(base_url=api_url, timeout=15.0) as client:
        # Проверяем что backend жив
        try:
            r = await client.get("/game-accounts/servers")
            r.raise_for_status()
            srv_count = len(r.json().get("servers", []))
            print(f"✅  Backend доступен. Серверов: {srv_count}")
        except Exception as e:
            print(f"❌  Backend недоступен ({api_url}): {e}")
            sys.exit(1)

        # Удаляем старые если --purge
        if do_purge:
            print("🗑️  Удаляю все существующие аккаунты...")
            deleted = await purge_all(client)
            print(f"   Удалено: {deleted}")
            print()

        print(f"🎮  Создаю {count} аккаунтов (формат: Имя_Фамилия, мужские русские ники)...")
        print()

        for i, nick in enumerate(nicks):
            server = random.choice(servers)
            password = generate_password()

            # Акк — заготовка: ник + пароль + сервер
            # Статус pending_registration — ещё не зарегистрирован в игре
            # Остальные данные (level, balance, ...) заполнятся автоматикой после реги
            payload = {
                "game": "com.br.top",
                "login": nick,
                "password": password,
                "server_name": server["name"],
                "nickname": nick,
                "gender": "male",
                "meta": {
                    "source": "seed_game_accounts",
                    "server_id": server["id"],
                },
            }

            try:
                r = await client.post("/game-accounts", json=payload)
                if r.status_code == 201:
                    created += 1
                    acc_id = r.json().get("id", "?")
                    srv_label = f"#{server['id']} {server['name']}"
                    print(f"  [{i + 1}/{count}] ✅  {nick} @ {srv_label} → {acc_id}")
                else:
                    failed += 1
                    print(f"  [{i + 1}/{count}] ❌  {r.status_code}: {r.text[:150]}")
            except Exception as e:
                failed += 1
                print(f"  [{i + 1}/{count}] ❌  Ошибка: {e}")

    print()
    print(f"═══ Результат ════════════════════════════════")
    print(f"  Создано: {created}")
    print(f"  Ошибок:  {failed}")
    print(f"  Пул ников: ~{len(MALE_FIRST_NAMES) * len(MALE_LAST_NAMES)} комбинаций")
    print(f"═══════════════════════════════════════════════")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Засев тестовых аккаунтов Black Russia")
    p.add_argument("--count", type=int, default=25, help="Количество аккаунтов (по умолчанию — 25)")
    p.add_argument("--api-url", default="http://localhost:8000/api/v1", help="URL API backend-а")
    p.add_argument("--purge", action="store_true", help="Удалить все существующие аккаунты перед засевом")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(f"🎮  Seed Game Accounts: {args.count} аккаунтов → {args.api_url}")
    if args.purge:
        print("   ⚠️  Режим --purge: старые аккаунты будут удалены!")
    print()
    asyncio.run(seed_accounts(args.api_url, args.count, args.purge))
