"""Bounded secret-bearing request parsing without FastAPI input echo."""
from __future__ import annotations

from copy import deepcopy
from typing import TypeVar

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


async def read_profile_request(request: Request, model: type[T], *, max_bytes: int = 98304) -> T:
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > max_bytes:
                raise HTTPException(413, "vpn_profile_body_too_large")
            body.extend(chunk)
        return model.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "invalid_vpn_profile_request") from None
    finally:
        body.clear()


def profile_request_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(node):
        if isinstance(node, list):
            return [inline(item) for item in node]
        if isinstance(node, dict):
            if "$ref" in node:
                reference = node["$ref"]
                if not reference.startswith("#/$defs/"):
                    raise ValueError("Non-local profile schema reference")
                node = {**deepcopy(definitions[reference.removeprefix("#/$defs/")]),
                        **{k: v for k, v in node.items() if k != "$ref"}}
            return {key: inline(value) for key, value in node.items()}
        return node

    return {"required": True, "content": {"application/json": {"schema": inline(schema)}}}
