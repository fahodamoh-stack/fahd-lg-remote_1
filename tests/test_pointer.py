import time

import pytest

from main import (
    DEFAULT_CAPABILITIES,
    PointerController,
    TVDevice,
    UnsupportedFeature,
)


class RecordingPointerTV:
    def __init__(self, pointer=True):
        capabilities = dict(DEFAULT_CAPABILITIES)
        capabilities["pointer"] = pointer
        self.device = TVDevice(
            name="Test LG",
            ip="127.0.0.1",
            capabilities=capabilities,
        )
        self.moves = []
        self.clicks = 0
        self.downs = 0
        self.ups = 0
        self.scrolls = []

    def pointer_move(self, dx, dy):
        self.moves.append((dx, dy))

    def pointer_click(self):
        self.clicks += 1

    def pointer_down(self):
        self.downs += 1

    def pointer_up(self):
        self.ups += 1

    def scroll(self, dx, dy):
        if not self.device.supports("pointer"):
            raise UnsupportedFeature()
        self.scrolls.append((dx, dy))


class ManualClock:
    def __init__(self):
        self.value = 1.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def make_pointer(**kwargs):
    tv = RecordingPointerTV()
    clock = kwargs.pop("clock", ManualClock())
    pointer = PointerController(
        tv,
        interval=0.03,
        clock=clock,
        **kwargs,
    )
    return tv, pointer, clock


def test_relative_dx_dy_are_sent():
    tv, pointer, clock = make_pointer(
        sensitivity=1.0,
        acceleration=0.0,
        dead_zone=0.0,
    )

    pointer.add_motion(7, -4)
    assert pointer.flush(now=clock()) is True
    assert tv.moves == [(7, -4)]

    pointer.close()


def test_sensitivity():
    tv, pointer, clock = make_pointer(
        sensitivity=2.0,
        acceleration=0.0,
        dead_zone=0.0,
    )

    dx, dy = pointer.transform(4, 3)
    assert dx == pytest.approx(8.0)
    assert dy == pytest.approx(6.0)

    pointer.close()


def test_acceleration_increases_motion():
    tv, pointer, clock = make_pointer(
        sensitivity=1.0,
        acceleration=0.4,
        dead_zone=0.0,
        max_speed=1000.0,
    )

    normal_x, _ = pointer.transform(10, 0)
    assert normal_x > 10

    pointer.close()


def test_deadzone_discards_small_motion():
    tv, pointer, clock = make_pointer(
        sensitivity=1.0,
        acceleration=0.0,
        dead_zone=5.0,
    )

    assert pointer.transform(2, 2) == (0.0, 0.0)
    pointer.add_motion(2, 2)
    assert pointer.pending() == (0.0, 0.0)
    assert pointer.flush(now=clock()) is False
    assert tv.moves == []

    pointer.close()


def test_max_speed_clamps_vector():
    tv, pointer, clock = make_pointer(
        sensitivity=5.0,
        acceleration=1.0,
        dead_zone=0.0,
        max_speed=20.0,
    )

    dx, dy = pointer.transform(100, 100)
    assert (dx ** 2 + dy ** 2) ** 0.5 <= 20.0001

    pointer.close()


def test_throttling():
    tv, pointer, clock = make_pointer(
        sensitivity=1.0,
        acceleration=0.0,
        dead_zone=0.0,
    )

    pointer.add_motion(5, 0)
    assert pointer.flush(now=1.0) is True

    pointer.add_motion(4, 0)
    assert pointer.flush(now=1.01) is False
    assert tv.moves == [(5, 0)]

    assert pointer.flush(now=1.04) is True
    assert tv.moves == [(5, 0), (4, 0)]

    pointer.close()


def test_coalescing_combines_pending_motion():
    tv, pointer, clock = make_pointer(
        sensitivity=1.0,
        acceleration=0.0,
        dead_zone=0.0,
    )

    pointer.add_motion(2, 3)
    pointer.add_motion(4, -1)

    dx, dy = pointer.pending()
    assert dx == pytest.approx(6)
    assert dy == pytest.approx(2)

    pointer.flush(now=clock())
    assert tv.moves == [(6, 2)]

    pointer.close()


def test_click_sends_real_pointer_click_method():
    tv, pointer, clock = make_pointer()

    pointer.click()

    assert tv.clicks == 1
    pointer.close()


def test_long_press_starts_drag():
    tv, pointer, clock = make_pointer()

    pointer.long_press()

    assert pointer.dragging is True
    assert tv.downs == 1

    pointer.end_drag()

    assert pointer.dragging is False
    assert tv.ups == 1
    pointer.close()


def test_drag_sends_down_motion_up_order():
    events = []

    class DragTV(RecordingPointerTV):
        def pointer_down(self):
            events.append("down")

        def pointer_move(self, dx, dy):
            events.append(("move", dx, dy))

        def pointer_up(self):
            events.append("up")

    tv = DragTV()
    clock = ManualClock()
    pointer = PointerController(
        tv,
        sensitivity=1.0,
        acceleration=0.0,
        dead_zone=0.0,
        interval=0.03,
        clock=clock,
    )

    pointer.start_drag()
    pointer.add_motion(8, 2)
    pointer.flush(now=clock())
    pointer.end_drag()

    assert events == [
        "down",
        ("move", 8, 2),
        "up",
    ]

    pointer.close()


def test_scroll_supported():
    tv, pointer, clock = make_pointer()

    pointer.scroll(0, -12)

    assert tv.scrolls == [(0, -12)]
    pointer.close()


def test_scroll_rejected_without_pointer_capability():
    tv = RecordingPointerTV(pointer=False)
    pointer = PointerController(tv)

    with pytest.raises(UnsupportedFeature):
        pointer.scroll(0, 10)

    pointer.close()


def test_worker_coalesces_instead_of_packet_per_pixel():
    tv = RecordingPointerTV()
    pointer = PointerController(
        tv,
        sensitivity=1.0,
        acceleration=0.0,
        dead_zone=0.0,
        interval=0.04,
    )

    for _ in range(100):
        pointer.add_motion(1, 0)

    time.sleep(0.12)
    pointer.close()

    assert len(tv.moves) < 100
    assert sum(dx for dx, _ in tv.moves) > 0