# -*- coding: utf-8 -*-
"""
CLI entry point для нагрузочного тестирования Sphere Platform.

Запуск:
    python -m tests.load --config tests/load/config/scenario_quick.yml
    python -m tests.load --config tests/load/config/scenario_scalability.yml
    python -m tests.load --scenario mixed --target 512 --hold 180
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.core.orchestrator import Orchestrator, TestConfig
from tests.load.core.virtual_agent import AgentBehavior
from tests.load.core.agent_pool import AgentPool
from tests.load.protocols.rest_client import RestClient
from tests.load.scenarios.mixed_workload import MixedWorkloadScenario


def _setup_logging(level: str = "INFO") -> None:
    """Настройка логирования."""
    log_format = (
        "%(asctime)s | %(levelname)-7s | %(name)-25s | %(message)s"
    )
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Suppress noisy libs
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sphere Platform Load Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # YAML-конфиг с шагами:
  python -m tests.load --config tests/load/config/scenario_quick.yml

  # Быстрый mixed-сценарий:
  python -m tests.load --scenario mixed --target 256 --hold 120

  # Полный тест масштабируемости:
  python -m tests.load --config tests/load/config/scenario_scalability.yml --log DEBUG
        """,
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        help="Путь к YAML-конфигу сценария",
    )
    parser.add_argument(
        "--scenario", "-s",
        type=str,
        choices=["orchestrator", "mixed"],
        default="orchestrator",
        help="Режим: orchestrator (шаги из YAML) или mixed (комбинированный)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="Базовый HTTP URL сервера",
    )
    parser.add_argument(
        "--ws-url",
        type=str,
        default="ws://localhost:8000",
        help="WebSocket URL сервера",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="",
        help="API-ключ (X-API-Key)",
    )
    parser.add_argument(
        "--target", "-t",
        type=int,
        default=128,
        help="Целевое число агентов (для --scenario mixed)",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=120.0,
        help="Время удержания нагрузки, сек (для --scenario mixed)",
    )
    parser.add_argument(
        "--ramp",
        type=float,
        default=60.0,
        help="Время ramp-up, сек",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="reports",
        help="Директория для отчётов",
    )
    parser.add_argument(
        "--log",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Уровень логирования",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed для детерминированной генерации идентичностей",
    )
    parser.add_argument(
        "--no-vpn",
        action="store_true",
        help="Отключить VPN enrollment",
    )
    parser.add_argument(
        "--no-reconnect-storm",
        action="store_true",
        help="Пропустить reconnect storm в mixed-сценарии",
    )

    return parser.parse_args()


async def _run_orchestrator(args: argparse.Namespace) -> bool:
    """Запуск через Orchestrator (YAML config с шагами)."""
    if not args.config:
        print("ОШИБКА: --config обязателен для --scenario orchestrator")
        sys.exit(1)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ОШИБКА: Конфиг не найден: {config_path}")
        sys.exit(1)

    config = TestConfig.from_yaml(config_path)

    # Переопределения из CLI
    if args.base_url != "http://localhost:8000":
        config.base_url = args.base_url
    if args.ws_url != "ws://localhost:8000":
        config.ws_url = args.ws_url
    if args.api_key:
        config.api_key = args.api_key
    if args.report_dir != "reports":
        config.report_dir = args.report_dir

    orchestrator = Orchestrator(config)
    return await orchestrator.run()


async def _run_mixed(args: argparse.Namespace) -> bool:
    """Запуск комбинированного сценария без YAML."""
    metrics = MetricsCollector()
    factory = IdentityFactory(org_id="load-test", seed=args.seed)
    behavior = AgentBehavior(
        enable_vpn=not args.no_vpn,
    )

    pool = AgentPool(
        identity_factory=factory,
        behavior=behavior,
        metrics=metrics,
        base_url=args.base_url,
        ws_url=args.ws_url,
    )

    rest = RestClient(
        base_url=args.base_url,
        metrics=metrics,
        api_key=args.api_key,
    )

    scenario = MixedWorkloadScenario(
        pool=pool,
        rest_client=rest,
        identity_factory=factory,
        metrics=metrics,
    )

    try:
        results = await scenario.run(
            target_agents=args.target,
            hold_sec=args.hold,
            ramp_up_sec=args.ramp,
            enable_reconnect_storm=not args.no_reconnect_storm,
        )

        # Сохраняем отчёт
        import json
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "mixed-report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nОтчёт: {report_path}")

        fa = results.get("final_fa", 0)
        return fa >= 90.0

    finally:
        await pool.stop_all()
        await rest.close()


async def _main() -> None:
    args = _parse_args()
    _setup_logging(args.log)

    logger = logging.getLogger("loadtest")
    logger.info("Sphere Platform Load Test")
    logger.info("  base_url: %s", args.base_url)
    logger.info("  ws_url:   %s", args.ws_url)
    logger.info("  scenario: %s", args.scenario)

    if args.scenario == "orchestrator" or args.config:
        passed = await _run_orchestrator(args)
    else:
        passed = await _run_mixed(args)

    if passed:
        logger.info("РЕЗУЛЬТАТ: PASS")
        sys.exit(0)
    else:
        logger.warning("РЕЗУЛЬТАТ: FAIL")
        sys.exit(1)


def main() -> None:
    """Точка входа."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
