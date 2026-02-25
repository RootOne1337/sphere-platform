#!/usr/bin/env python3
"""
generate_device_config.py — генератор sphere-agent-config.json для массового деплоя.

Использование:
  # Один конфиг для LDPlayer клона
  python generate_device_config.py \
    --env development \
    --workstation-id ws-PC-FARM-01 \
    --instance-index 42 \
    --location msk-office-1

  # Batch: 30 конфигов для одной воркстанции
  python generate_device_config.py \
    --env development \
    --workstation-id ws-PC-FARM-01 \
    --count 30 \
    --start-index 0 \
    --location msk-office-1 \
    --output-dir ./output

  # Для физического устройства
  python generate_device_config.py \
    --env production \
    --location fra-dc-2 \
    --template physical-device
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Корень agent-config относительно скрипта
CONFIG_ROOT = Path(__file__).resolve().parent.parent


def load_environment(env_name: str) -> dict:
    """Загрузить конфигурацию окружения."""
    env_file = CONFIG_ROOT / "environments" / f"{env_name}.json"
    if not env_file.exists():
        print(f"Ошибка: окружение '{env_name}' не найдено ({env_file})", file=sys.stderr)
        sys.exit(1)
    with open(env_file, encoding="utf-8") as f:
        return json.load(f)


def load_schema() -> dict:
    """Загрузить JSON Schema для валидации."""
    schema_file = CONFIG_ROOT / "schema.json"
    if not schema_file.exists():
        return {}
    with open(schema_file, encoding="utf-8") as f:
        return json.load(f)


def validate_config(config: dict, schema: dict) -> list[str]:
    """Базовая валидация конфига по обязательным полям схемы (без jsonschema зависимости)."""
    errors: list[str] = []
    required = schema.get("required", [])
    for field in required:
        if field not in config or config[field] is None:
            errors.append(f"Обязательное поле '{field}' отсутствует или null")
    # Проверка формата enrollment_api_key
    key = config.get("enrollment_api_key", "")
    if key and not key.startswith("sphr_"):
        errors.append(f"enrollment_api_key должен начинаться с 'sphr_', получено: {key[:10]}...")
    return errors


def generate_single_config(
    env_config: dict,
    workstation_id: str | None = None,
    instance_index: int | None = None,
    location: str | None = None,
    ldplayer_name: str | None = None,
) -> dict:
    """Сгенерировать конфиг для одного устройства на основе окружения."""
    config = {
        "config_version": env_config["config_version"],
        "server_url": env_config["server_url"],
        "ws_path": env_config.get("ws_path", "/ws/android"),
        "enrollment_api_key": env_config["enrollment_api_key"],
        "device_id": None,
        "workstation_id": workstation_id,
        "instance_index": instance_index,
        "location": location or env_config.get("location"),
        "environment": env_config.get("environment", "production"),
        "config_poll_interval_seconds": env_config.get("config_poll_interval_seconds", 86400),
        "features": env_config.get("features", {
            "telemetry_enabled": True,
            "streaming_enabled": True,
            "ota_enabled": True,
            "auto_register": True,
        }),
        "meta": {},
    }
    if ldplayer_name:
        config["meta"]["ldplayer_name"] = ldplayer_name
    if workstation_id and instance_index is not None:
        config["meta"]["clone_source"] = "auto-generated"
    return config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Генератор sphere-agent-config.json для массового деплоя агентов.",
    )
    parser.add_argument(
        "--env", required=True, choices=["production", "staging", "development"],
        help="Целевое окружение",
    )
    parser.add_argument("--workstation-id", help="ID воркстанции (PC-хоста)")
    parser.add_argument("--instance-index", type=int, help="Индекс LDPlayer инстанса (0-based)")
    parser.add_argument("--location", help="Код локации (msk-office-1)")
    parser.add_argument("--ldplayer-name", help="Имя LDPlayer инстанса")
    parser.add_argument(
        "--count", type=int, default=1,
        help="Количество конфигов (batch-генерация)",
    )
    parser.add_argument(
        "--start-index", type=int, default=0,
        help="Начальный instance_index для batch-генерации",
    )
    parser.add_argument(
        "--output-dir", default="./output",
        help="Директория для сохранения сгенерированных конфигов",
    )
    parser.add_argument(
        "--output-file",
        help="Имя файла (для одного конфига). По умолчанию: sphere-agent-config.json",
    )
    args = parser.parse_args()

    # Загружаем окружение и схему
    env_config = load_environment(args.env)
    schema = load_schema()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    for i in range(args.count):
        idx = args.start_index + i if args.workstation_id else args.instance_index
        name = args.ldplayer_name
        if args.count > 1:
            name = name or f"Farm-{idx:03d}"

        config = generate_single_config(
            env_config=env_config,
            workstation_id=args.workstation_id,
            instance_index=idx,
            location=args.location,
            ldplayer_name=name,
        )

        # Валидация
        errors = validate_config(config, schema)
        if errors:
            print(f"Ошибки валидации конфига #{i}:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)

        # Имя файла
        if args.count == 1:
            filename = args.output_file or "sphere-agent-config.json"
        else:
            filename = f"sphere-agent-config-{idx:03d}.json"

        filepath = output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        generated += 1

    print(f"Сгенерировано конфигов: {generated}")
    print(f"Директория: {output_dir.resolve()}")
    if args.count == 1:
        print(f"\nДеплой: adb push {output_dir / 'sphere-agent-config.json'} /sdcard/sphere-agent-config.json")
    else:
        print(f"\nBatch деплой через PC-Agent: скрипты читают конфиги из {output_dir}/")


if __name__ == "__main__":
    main()
