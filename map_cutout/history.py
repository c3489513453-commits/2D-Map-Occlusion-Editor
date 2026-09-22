from __future__ import annotations

from typing import Protocol


class Command(Protocol):
    def execute(self): ...
    def undo(self) -> None: ...


class History:
    def __init__(self, limit: int = 50):
        self.limit = limit
        self._undo: list[Command] = []
        self._redo: list[Command] = []

    def execute(self, command: Command):
        result = command.execute()
        self._undo.append(command)
        self._undo = self._undo[-self.limit:]
        self._redo.clear()
        return result

    def undo(self) -> bool:
        if not self._undo:
            return False
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        command = self._redo.pop()
        command.execute()
        self._undo.append(command)
        return True


class HistoryManager:
    def __init__(self, limit: int = 50):
        self.limit = limit
        self._histories: dict[str, History] = {}

    def for_map(self, map_id: str) -> History:
        return self._histories.setdefault(map_id, History(self.limit))

    def clear(self) -> None:
        self._histories.clear()

