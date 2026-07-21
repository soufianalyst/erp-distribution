"""Unified API response envelope: {"success": ..., "data": ..., "message": ...}."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str = "تمت العملية بنجاح."
