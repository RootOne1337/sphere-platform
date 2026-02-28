"""Тест viewer WS: проверяет что DEV_SKIP_AUTH bypass работает для стрим-эндпоинта."""
import asyncio
import json

import websockets


async def test_viewer():
    device_id = "31687d4e-5057-40f3-b2c9-b53949928623"
    uri = f"ws://127.0.0.1:8000/ws/stream/{device_id}"
    try:
        async with websockets.connect(uri) as ws:
            # Отправляем пустой токен — должно пройти при DEV_SKIP_AUTH
            await ws.send(json.dumps({"token": ""}))
            # Ждём ответ (если viewer зарегистрирован — бинарные данные или ничего)
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"OK: получено сообщение, тип={type(msg).__name__}, len={len(msg)}")
    except websockets.exceptions.ConnectionClosed as e:
        print(f"WS закрыт: code={e.code} reason={e.reason}")
    except asyncio.TimeoutError:
        print("OK: WS открыт, timeout на recv (ожидается — агент не стримит)")
    except Exception as e:
        print(f"ОШИБКА: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(test_viewer())
