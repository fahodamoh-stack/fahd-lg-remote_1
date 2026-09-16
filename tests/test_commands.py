import json
import queue
import socket
import threading
import time

import pytest

from main import (
    DEFAULT_CAPABILITIES,
    LGWebOSController,
    ProtocolError,
    RemoteController,
    TVConnection,
    TVDevice,
    UnsupportedFeature,
)


class MemorySettings:
    def __init__(self):
        self.keys = {}

    def get_client_key(self, device):
        return self.keys.get(device.identity)

    def set_client_key(self, device, value):
        self.keys[device.identity] = value


class ScriptedWebSocket:
    def __init__(self, script=None):
        self.incoming = queue.Queue()
        self.sent = []
        self.closed = False
        self.timeout = 1.0

        for message in script or []:
            self.incoming.put(message)

    def settimeout(self, timeout):
        self.timeout = timeout

    def send(self, raw):
        if self.closed:
            raise OSError("closed")

        self.sent.append(raw)

        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return

        request_id = obj.get("id")

        if obj.get("type") == "register":
            self.incoming.put(
                json.dumps(
                    {
                        "id": request_id,
                        "type": "registered",
                        "payload": {
                            "client-key": "unit-test-client-key"
                        },
                    }
                )
            )
            return

        uri = obj.get("uri")

        payload = {"returnValue": True}

        if uri == "ssap://audio/getVolume":
            payload["volume"] = 20

        if uri == "ssap://audio/getStatus":
            payload["mute"] = False

        if uri.endswith("getPointerInputSocket"):
            payload["socketPath"] = "ws://127.0.0.1:39999/pointer"

        self.incoming.put(
            json.dumps(
                {
                    "id": request_id,
                    "type": "response",
                    "payload": payload,
                }
            )
        )

    def recv(self):
        if self.closed:
            return ""

        try:
            return self.incoming.get(timeout=0.1)
        except queue.Empty:
            from websocket import WebSocketTimeoutException
            raise WebSocketTimeoutException()

    def close(self):
        self.closed = True

    def push(self, value):
        self.incoming.put(value)


class PointerSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def send(self, value):
        if self.closed:
            raise OSError("closed")
        self.sent.append(value)

    def close(self):
        self.closed = True


class WebSocketFactory:
    def __init__(self):
        self.control = ScriptedWebSocket()
        self.pointer = PointerSocket()
        self.urls = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        if "/pointer" in url:
            return self.pointer
        return self.control


def device_with_all_capabilities():
    capabilities = dict(DEFAULT_CAPABILITIES)
    capabilities.update(
        {
            "pointer": True,
            "keyboard": True,
            "volume": True,
            "channels": True,
            "apps": True,
            "media": True,
        }
    )

    return TVDevice(
        name="Test webOS TV",
        ip="127.0.0.1",
        port=3000,
        manufacturer="LG",
        protocol="lg-webos-ssap",
        capabilities=capabilities,
    )


def connected_controller():
    device = device_with_all_capabilities()
    settings = MemorySettings()
    factory = WebSocketFactory()

    connection = TVConnection(
        device,
        settings,
        timeout=0.5,
        websocket_factory=factory,
    )
    connection.connect()

    controller = LGWebOSController(device, connection)
    controller.device.capabilities.update(
        device_with_all_capabilities().capabilities
    )

    return controller, connection, factory, settings


@pytest.mark.parametrize(
    "command",
    ["UP", "DOWN", "LEFT", "RIGHT", "OK"],
)
def test_dpad_commands_generate_pointer_packets(command):
    controller, connection, factory, settings = connected_controller()

    controller.command(command)

    packet = factory.pointer.sent[-1]
    assert packet.startswith("type:button\n")
    assert "name:" in packet

    connection.close()


def test_command_ordering():
    controller, connection, factory, settings = connected_controller()

    controller.command("UP")
    controller.command("LEFT")
    controller.command("OK")

    packets = factory.pointer.sent[-3:]

    assert "name:UP" in packets[0]
    assert "name:LEFT" in packets[1]
    assert "name:ENTER" in packets[2]

    connection.close()


def test_long_press_first_command_is_immediate():
    class RecordingController:
        def __init__(self):
            self.events = []

        def command(self, value):
            self.events.append((value, time.monotonic()))

    controller = RecordingController()
    remote = RemoteController(
        controller,
        initial_delay=0.08,
        repeat_interval=0.04,
    )

    started = time.monotonic()
    remote.start_hold("UP")

    assert controller.events
    assert controller.events[0][0] == "UP"
    assert controller.events[0][1] - started < 0.04

    time.sleep(0.14)
    remote.stop_hold()

    assert len(controller.events) >= 2


def test_long_press_stops_after_release():
    class RecordingController:
        def __init__(self):
            self.events = []

        def command(self, value):
            self.events.append(value)

    controller = RecordingController()
    remote = RemoteController(
        controller,
        initial_delay=0.04,
        repeat_interval=0.025,
    )

    remote.start_hold("RIGHT")
    time.sleep(0.11)
    remote.stop_hold()

    count_after_release = len(controller.events)
    time.sleep(0.08)

    assert len(controller.events) == count_after_release


def test_volume_capability_check():
    controller, connection, factory, settings = connected_controller()
    controller.device.capabilities["volume"] = False

    with pytest.raises(UnsupportedFeature):
        controller.command("VOLUME_UP")

    connection.close()


def test_channel_capability_check():
    controller, connection, factory, settings = connected_controller()
    controller.device.capabilities["channels"] = False

    with pytest.raises(UnsupportedFeature):
        controller.command("CHANNEL_UP")

    connection.close()


def test_unknown_command_is_rejected():
    controller, connection, factory, settings = connected_controller()

    with pytest.raises(UnsupportedFeature):
        controller.command("SAMSUNG_MAGIC_COMMAND")

    connection.close()


def test_power_uses_ssap_turn_off():
    controller, connection, factory, settings = connected_controller()

    controller.command("POWER")

    decoded = [
        json.loads(item)
        for item in factory.control.sent
        if item.startswith("{")
    ]

    assert any(
        item.get("uri") == "ssap://system/turnOff"
        for item in decoded
    )

    connection.close()


def test_client_key_is_saved_after_pairing():
    controller, connection, factory, settings = connected_controller()

    assert settings.get_client_key(controller.device) == (
        "unit-test-client-key"
    )

    connection.close()


def test_pointer_uses_real_network_input_packet():
    controller, connection, factory, settings = connected_controller()

    controller.pointer_move(12, -7)

    assert factory.pointer.sent[-1] == (
        "type:move\n"
        "dx:12\n"
        "dy:-7\n"
        "down:0\n\n"
    )

    connection.close()


def test_keyboard_uses_ssap_insert_text():
    controller, connection, factory, settings = connected_controller()

    controller.text("FAHD")

    messages = [
        json.loads(item)
        for item in factory.control.sent
        if item.startswith("{")
    ]

    matches = [
        item
        for item in messages
        if item.get("uri")
        == "ssap://com.webos.service.ime/insertText"
    ]

    assert matches
    assert matches[-1]["payload"]["text"] == "FAHD"

    connection.close()


def test_malformed_response_is_ignored_then_valid_response_matches():
    device = device_with_all_capabilities()
    settings = MemorySettings()
    factory = WebSocketFactory()

    connection = TVConnection(
        device,
        settings,
        timeout=0.4,
        websocket_factory=factory,
    )
    connection.connect()

    factory.control.push("{ invalid json")

    result = connection.request(
        "ssap://audio/getVolume",
        timeout=0.3,
    )

    assert result["type"] == "response"
    connection.close()


def test_request_timeout():
    class TimeoutSocket(ScriptedWebSocket):
        def send(self, raw):
            obj = json.loads(raw)
            self.sent.append(raw)

            if obj.get("type") == "register":
                self.incoming.put(
                    json.dumps(
                        {
                            "id": obj["id"],
                            "type": "registered",
                            "payload": {
                                "client-key": "key"
                            },
                        }
                    )
                )

    socket_obj = TimeoutSocket()

    def factory(url, **kwargs):
        return socket_obj

    device = device_with_all_capabilities()
    settings = MemorySettings()

    connection = TVConnection(
        device,
        settings,
        timeout=0.1,
        websocket_factory=factory,
    )
    connection.connect()

    from main import ConnectionTimeout

    with pytest.raises(ConnectionTimeout):
        connection.request(
            "ssap://test/no-response",
            timeout=0.05,
        )

    connection.close()


def test_tv_error_response_raises_protocol_error():
    class ErrorSocket(ScriptedWebSocket):
        def send(self, raw):
            obj = json.loads(raw)
            self.sent.append(raw)

            if obj.get("type") == "register":
                self.incoming.put(
                    json.dumps(
                        {
                            "id": obj["id"],
                            "type": "registered",
                            "payload": {
                                "client-key": "key"
                            },
                        }
                    )
                )
                return

            self.incoming.put(
                json.dumps(
                    {
                        "id": obj["id"],
                        "type": "error",
                        "error": "401 denied",
                    }
                )
            )

    socket_obj = ErrorSocket()

    connection = TVConnection(
        device_with_all_capabilities(),
        MemorySettings(),
        timeout=0.2,
        websocket_factory=lambda url, **kwargs: socket_obj,
    )
    connection.connect()

    with pytest.raises(ProtocolError):
        connection.request("ssap://forbidden")

    connection.close()


def test_reconnect_creates_new_connection():
    created = []

    def factory(url, **kwargs):
        item = ScriptedWebSocket()
        created.append(item)
        return item

    connection = TVConnection(
        device_with_all_capabilities(),
        MemorySettings(),
        timeout=0.2,
        websocket_factory=factory,
    )

    connection.connect()
    connection.reconnect(attempts=1)

    assert len(created) == 2
    assert connection.connected is True

    connection.close()


class MockLGTVServer:
    """
    In-process protocol test server used to verify the complete logical flow:
    discovery result -> connect -> register -> command -> pointer ->
    keyboard -> disconnect -> reconnect.

    The control transport is presented through websocket-client's factory
    boundary so tests are deterministic and need no physical LAN or TV.
    """

    def __init__(self):
        self.client_key = "mock-lg-key"
        self.control_connections = 0
        self.control_messages = []
        self.pointer_messages = []

    def websocket_factory(self, url, **kwargs):
        if "/pointer" in url:
            server = self

            class ServerPointer:
                def settimeout(self, timeout):
                    self.timeout = timeout

                def send(self, message):
                    server.pointer_messages.append(message)

                def close(self):
                    self.closed = True

            return ServerPointer()

        self.control_connections += 1
        server = self

        class ServerControl(ScriptedWebSocket):
            def send(self, raw):
                obj = json.loads(raw)
                server.control_messages.append(obj)
                request_id = obj.get("id")

                if obj.get("type") == "register":
                    self.incoming.put(
                        json.dumps(
                            {
                                "id": request_id,
                                "type": "registered",
                                "payload": {
                                    "client-key": server.client_key
                                },
                            }
                        )
                    )
                    return

                uri = obj.get("uri", "")
                payload = {"returnValue": True}

                if uri.endswith("getPointerInputSocket"):
                    payload["socketPath"] = (
                        "ws://127.0.0.1:39999/pointer"
                    )
                elif uri == "ssap://audio/getVolume":
                    payload["volume"] = 30
                elif uri == "ssap://audio/getStatus":
                    payload["mute"] = False

                self.incoming.put(
                    json.dumps(
                        {
                            "id": request_id,
                            "type": "response",
                            "payload": payload,
                        }
                    )
                )

        return ServerControl()


def test_mock_tv_end_to_end_flow():
    server = MockLGTVServer()
    settings = MemorySettings()

    device = TVDevice(
        name="Mock Living Room TV",
        ip="127.0.0.1",
        port=3000,
        manufacturer="LG",
        protocol="lg-webos-ssap",
    )

    connection = TVConnection(
        device,
        settings,
        timeout=0.5,
        websocket_factory=server.websocket_factory,
    )
    controller = LGWebOSController(
        device,
        connection,
    )

    controller.connect()

    assert connection.registered is True
    assert settings.get_client_key(device) == "mock-lg-key"

    device.capabilities.update(
        {
            "pointer": True,
            "keyboard": True,
            "volume": True,
            "channels": True,
            "apps": True,
            "media": True,
        }
    )

    controller.command("VOLUME_UP")
    controller.pointer_move(5, 3)
    controller.text("FAHD")

    assert any(
        message.get("uri") == "ssap://audio/volumeUp"
        for message in server.control_messages
    )
    assert any(
        "type:move" in message
        for message in server.pointer_messages
    )
    assert any(
        message.get("uri")
        == "ssap://com.webos.service.ime/insertText"
        for message in server.control_messages
    )

    connection.close()
    connection.reconnect(attempts=1)

    assert connection.connected is True
    assert server.control_connections >= 2

    connection.close()