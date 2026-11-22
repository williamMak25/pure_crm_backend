from typing import Any

import msgspec


class BaseStruct(msgspec.Struct):
    def to_dict(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in self.__struct_fields__ if getattr(self, f, None) != msgspec.UNSET}


class CamelizedBaseStruct(BaseStruct, rename="camel"):
    """Request and response bodies use camelCase to match the SvelteKit frontend."""


class Message(CamelizedBaseStruct):
    message: str


class Paginated[T](CamelizedBaseStruct):
    """The frontend's `Paginated<T>`."""

    items: list[T]
    total: int
    page: int
    page_size: int
