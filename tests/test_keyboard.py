import pytest

from main import (
    DEFAULT_CAPABILITIES,
    KeyboardController,
    TVDevice,
    UnsupportedFeature,
)


class ManualClock:
    def __init__(self):
        self.value = 1.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class RecordingKeyboardTV:
    def __init__(self, supported=True):
        capabilities = dict(DEFAULT_CAPABILITIES)
        capabilities["keyboard"] = supported

        self.device = TVDevice(
            name="LG Keyboard Test",
            ip="127.0.0.1",
            capabilities=capabilities,
        )
        self.text_values = []
        self.keys = []

    def text(self, value):
        self.text_values.append(value)

    def keyboard_key(self, value):
        self.keys.append(value)


def test_text_input_reaches_controller():
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(tv)

    assert keyboard.send_text("فهد") is True
    assert tv.text_values == ["فهد"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("enter", "ENTER"),
        ("backspace", "BACKSPACE"),
        ("delete", "DELETE"),
        ("left", "LEFT"),
        ("right", "RIGHT"),
        ("up", "UP"),
        ("down", "DOWN"),
        ("escape", "ESCAPE"),
    ],
)
def test_special_keys(source, expected):
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(tv)

    assert keyboard.send_key(source) is True
    assert tv.keys == [expected]


def test_space_is_special_key():
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(tv)

    keyboard.send_key("space")

    assert tv.keys == ["SPACE"]


def test_single_character_key_becomes_text():
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(tv)

    keyboard.send_key("A")

    assert tv.text_values == ["A"]
    assert tv.keys == []


def test_duplicate_text_is_suppressed():
    clock = ManualClock()
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(
        tv,
        duplicate_window=0.1,
        clock=clock,
    )

    assert keyboard.send_text("hello") is True
    assert keyboard.send_text("hello") is False

    assert tv.text_values == ["hello"]


def test_duplicate_allowed_after_window():
    clock = ManualClock()
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(
        tv,
        duplicate_window=0.1,
        clock=clock,
    )

    keyboard.send_text("x")
    clock.advance(0.2)
    keyboard.send_text("x")

    assert tv.text_values == ["x", "x"]


def test_different_text_is_not_suppressed():
    clock = ManualClock()
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(
        tv,
        clock=clock,
    )

    keyboard.send_text("a")
    keyboard.send_text("b")

    assert tv.text_values == ["a", "b"]


def test_duplicate_special_key_is_suppressed():
    clock = ManualClock()
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(
        tv,
        duplicate_window=0.1,
        clock=clock,
    )

    assert keyboard.send_key("left") is True
    assert keyboard.send_key("left") is False

    assert tv.keys == ["LEFT"]


def test_empty_text_is_not_sent():
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(tv)

    assert keyboard.send_text("") is False
    assert tv.text_values == []


def test_unsupported_text_input_raises():
    tv = RecordingKeyboardTV(supported=False)
    keyboard = KeyboardController(tv)

    with pytest.raises(UnsupportedFeature):
        keyboard.send_text("hello")

    assert tv.text_values == []


def test_unknown_multi_character_key_rejected():
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(tv)

    with pytest.raises(UnsupportedFeature):
        keyboard.send_key("not-a-real-key")


def test_text_and_key_events_are_distinct():
    clock = ManualClock()
    tv = RecordingKeyboardTV()
    keyboard = KeyboardController(
        tv,
        duplicate_window=0.1,
        clock=clock,
    )

    keyboard.send_text("x")
    keyboard.send_key("left")

    assert tv.text_values == ["x"]
    assert tv.keys == ["LEFT"]