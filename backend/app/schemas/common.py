from typing import Generic, TypeVar

from pydantic import BaseModel


ItemT = TypeVar("ItemT")


class CursorPage(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    next_cursor: str | None
