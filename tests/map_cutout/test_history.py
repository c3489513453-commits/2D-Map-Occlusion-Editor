from dataclasses import dataclass

from map_cutout.history import History, HistoryManager


@dataclass
class Counter:
    value: int = 0


class Increment:
    def __init__(self, counter):
        self.counter = counter

    def execute(self):
        self.counter.value += 1
        return self.counter.value

    def undo(self):
        self.counter.value -= 1


def test_history_keeps_only_latest_fifty_commands():
    history = History(limit=50)
    state = Counter()
    for _ in range(55):
        history.execute(Increment(state))
    for _ in range(50):
        history.undo()
    assert state.value == 5
    assert history.undo() is False


def test_undo_and_redo_restore_state_and_new_action_clears_redo():
    history = History()
    state = Counter()
    assert history.execute(Increment(state)) == 1
    assert history.undo() is True
    assert history.redo() is True
    assert state.value == 1
    history.undo()
    history.execute(Increment(state))
    assert history.redo() is False


def test_histories_are_isolated_per_map():
    manager = HistoryManager(limit=50)
    counter_a, counter_b = Counter(), Counter()
    manager.for_map("a").execute(Increment(counter_a))
    manager.for_map("b").execute(Increment(counter_b))
    manager.for_map("a").undo()
    assert counter_a.value == 0
    assert counter_b.value == 1

