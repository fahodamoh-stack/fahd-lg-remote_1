from __future__ import annotations

import abc
import json
import math
import os
import queue
import re
import socket
import ssl
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import websocket
import arabic_reshaper
from bidi.algorithm import get_display

try:
    import arabic_reshaper
except ImportError:
    arabic_reshaper = None

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    RoundedRectangle,
)
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import (
    FadeTransition,
    Screen,
    ScreenManager,
)
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


# ============================================================
# APP / FONT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
FONT_FILE = BASE_DIR / "fonts" / "NotoSansArabic-Regular.ttf"

FONT_NAME = "Roboto"

if FONT_FILE.is_file():
    try:
        LabelBase.register(
            name="FahdArabic",
            fn_regular=str(FONT_FILE),
        )
        FONT_NAME = "FahdArabic"
    except Exception:
        FONT_NAME = "Roboto"


def ar(value: str) -> str:
    """Shape Arabic into visual glyph order for the SDL2 renderer."""
    if not value:
        return value

    if not re.search(r"[\u0600-\u06ff]", value):
        return value

    try:
        shaped = arabic_reshaper.reshape(value)
        return get_display(shaped)
    except Exception:
        return value



# ============================================================
# COLORS
# ============================================================

BG = (0.020, 0.023, 0.028, 1)
SURFACE = (0.050, 0.055, 0.065, 1)
SURFACE_2 = (0.075, 0.082, 0.095, 1)
SURFACE_3 = (0.105, 0.115, 0.130, 1)

TEXT = (0.94, 0.95, 0.97, 1)
MUTED = (0.53, 0.57, 0.63, 1)

SILVER = (0.62, 0.66, 0.72, 1)
ACCENT = (0.72, 0.76, 0.82, 1)

GREEN = (0.20, 0.85, 0.52, 1)
RED = (0.90, 0.20, 0.25, 1)
YELLOW = (0.95, 0.76, 0.18, 1)
BLUE = (0.20, 0.47, 0.95, 1)


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_CAPABILITIES = {
    "pointer": False,
    "keyboard": False,
    "volume": False,
    "channels": False,
    "apps": False,
    "microphone": False,
    "media": False,
}

LG_ST = "urn:lge-com:service:webos-second-screen:1"
SSDP_ADDRESS = ("239.255.255.250", 1900)

UNSUPPORTED_MESSAGE = (
    "هذه الميزة غير مدعومة من هذا التلفزيون أو التطبيق المفتوح حاليًا."
)

KEYBOARD_UNSUPPORTED = (
    "إدخال النص غير مدعوم على هذا التلفزيون أو في التطبيق الحالي."
)


# ============================================================
# ERRORS
# ============================================================

class FahdError(Exception):
    """Expected application error."""


class ConnectionFailure(FahdError):
    """Network connection failed."""


class ConnectionTimeout(FahdError):
    """Network operation timed out."""


class ProtocolError(FahdError):
    """Invalid or rejected TV response."""


class UnsupportedFeature(FahdError):
    """Feature is unavailable."""


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, ConnectionTimeout):
        return "انتهت مهلة الاتصال."

    if isinstance(exc, UnsupportedFeature):
        return str(exc) or "هذه الميزة غير مدعومة."

    if isinstance(exc, ProtocolError):
        return "حدث خطأ في رد التلفزيون."

    if isinstance(exc, PermissionError):
        return "تم رفض الصلاحية المطلوبة."

    return "تعذر الاتصال بالتلفزيون."


def mask_ip(ip: str) -> str:
    parts = ip.split(".")

    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.xxx.{parts[3]}"

    return "unknown"


# ============================================================
# DEVICE
# ============================================================

@dataclass
class TVDevice:
    name: str
    ip: str
    port: int = 3001
    device_id: str = ""
    manufacturer: str = "LG"
    model: str = ""
    protocol: str = "lg-webos-ssap"

    capabilities: Dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_CAPABILITIES)
    )

    availability: bool = True
    location: str = ""

    def __post_init__(self) -> None:
        caps = dict(DEFAULT_CAPABILITIES)
        caps.update(self.capabilities or {})
        self.capabilities = caps

    @property
    def identity(self) -> str:
        if self.device_id:
            return self.device_id.lower()

        return (
            f"{self.ip}|"
            f"{self.manufacturer.lower()}|"
            f"{self.protocol}"
        )

    def supports(self, capability: str) -> bool:
        return bool(self.capabilities.get(capability, False))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TVDevice":
        allowed = {
            "name",
            "ip",
            "port",
            "device_id",
            "manufacturer",
            "model",
            "protocol",
            "capabilities",
            "availability",
            "location",
        }

        cleaned = {
            key: value
            for key, value in data.items()
            if key in allowed
        }

        if not cleaned.get("name") or not cleaned.get("ip"):
            raise ValueError("Invalid television")

        return cls(**cleaned)


# ============================================================
# SETTINGS
# ============================================================

class SettingsManager:
    DEFAULTS = {
        "version": 2,
        "pointer_sensitivity": 1.0,
        "pointer_acceleration": 0.10,
        "pointer_dead_zone": 0.7,
        "pointer_max_speed": 120.0,
        "auto_reconnect": True,
        "saved_tvs": [],
        "selected_tv": "",
        "client_keys": {},
    }

    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)
        self.file = self.directory / "settings.json"

        self._lock = threading.RLock()
        self.data = dict(self.DEFAULTS)

        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                if not self.file.exists():
                    return

                value = json.loads(
                    self.file.read_text(encoding="utf-8")
                )

                if not isinstance(value, dict):
                    return

                loaded = dict(self.DEFAULTS)
                loaded.update(value)

                if not isinstance(loaded.get("saved_tvs"), list):
                    loaded["saved_tvs"] = []

                if not isinstance(loaded.get("client_keys"), dict):
                    loaded["client_keys"] = {}

                self.data = loaded

            except (OSError, ValueError, TypeError):
                self.data = dict(self.DEFAULTS)

    def save(self) -> None:
        with self._lock:
            self.directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            temporary = self.file.with_suffix(".tmp")

            temporary.write_text(
                json.dumps(
                    self.data,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            os.replace(temporary, self.file)

    def get(self, name: str, default: Any = None) -> Any:
        with self._lock:
            return self.data.get(name, default)

    def set(self, name: str, value: Any) -> None:
        with self._lock:
            self.data[name] = value
            self.save()

    def saved_tvs(self) -> List[TVDevice]:
        result: List[TVDevice] = []

        for item in self.get("saved_tvs", []):
            try:
                result.append(TVDevice.from_dict(item))
            except (TypeError, ValueError):
                continue

        return result

    def save_tv(self, device: TVDevice) -> None:
        devices = {
            item.identity: item
            for item in self.saved_tvs()
        }

        devices[device.identity] = device

        self.data["saved_tvs"] = [
            item.to_dict()
            for item in devices.values()
        ]

        self.data["selected_tv"] = device.identity
        self.save()

    def forget_tv(self, identity: str) -> None:
        self.data["saved_tvs"] = [
            device.to_dict()
            for device in self.saved_tvs()
            if device.identity != identity
        ]

        keys = self.data.get("client_keys", {})

        if isinstance(keys, dict):
            keys.pop(identity, None)

        if self.data.get("selected_tv") == identity:
            self.data["selected_tv"] = ""

        self.save()

    def get_client_key(self, device: TVDevice) -> Optional[str]:
        keys = self.get("client_keys", {})

        if not isinstance(keys, dict):
            return None

        key = keys.get(device.identity)

        return str(key) if key else None

    def set_client_key(self, device: TVDevice, key: str) -> None:
        keys = dict(self.get("client_keys", {}))
        keys[device.identity] = key
        self.set("client_keys", keys)


# ============================================================
# DISCOVERY
# ============================================================

class TVDiscovery:
    def __init__(self) -> None:
        self.stop_event = threading.Event()

    @staticmethod
    def request_packet() -> bytes:
        return (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1900\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 2\r\n"
            f"ST: {LG_ST}\r\n"
            "\r\n"
        ).encode("ascii")

    @staticmethod
    def parse_ssdp(data: bytes) -> Dict[str, str]:
        text = data.decode(
            "utf-8",
            errors="replace",
        )

        lines = re.split(r"\r?\n", text.strip())

        if not lines or "200" not in lines[0]:
            raise ValueError("Malformed SSDP")

        result: Dict[str, str] = {}

        for line in lines[1:]:
            if ":" not in line:
                continue

            name, value = line.split(":", 1)
            result[name.strip().lower()] = value.strip()

        return result

    @staticmethod
    def make_device(
        headers: Dict[str, str],
        ip: str,
    ) -> Optional[TVDevice]:
        combined = " ".join(
            (
                headers.get("server", ""),
                headers.get("st", ""),
                headers.get("usn", ""),
            )
        ).lower()

        if not any(
            marker in combined
            for marker in (
                "webos",
                "lge",
                LG_ST.lower(),
            )
        ):
            return None

        usn = headers.get("usn", "")

        device_id = (
            usn.split("::", 1)[0]
            .replace("uuid:", "")
            .strip()
        )

        return TVDevice(
            name=headers.get(
                "friendlyname",
                "LG webOS TV",
            ),
            ip=ip,
            device_id=device_id,
            manufacturer=headers.get(
                "manufacturer",
                "LG",
            ),
            model=headers.get("modelname", ""),
            location=headers.get("location", ""),
        )

    @staticmethod
    def probe(ip: str, port: int) -> bool:
        try:
            with socket.create_connection(
                (ip, port),
                timeout=0.3,
            ):
                return True
        except OSError:
            return False

    def discover(self, timeout: float = 3.0) -> List[TVDevice]:
        self.stop_event.clear()

        devices: Dict[str, TVDevice] = {}

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        try:
            sock.settimeout(0.25)
            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )

            sock.sendto(
                self.request_packet(),
                SSDP_ADDRESS,
            )

            deadline = time.monotonic() + timeout

            while (
                not self.stop_event.is_set()
                and time.monotonic() < deadline
            ):
                try:
                    packet, source = sock.recvfrom(65535)

                except socket.timeout:
                    continue

                except OSError:
                    break

                try:
                    headers = self.parse_ssdp(packet)
                    device = self.make_device(
                        headers,
                        source[0],
                    )
                except ValueError:
                    continue

                if device is None:
                    continue

                if self.probe(device.ip, 3001):
                    device.port = 3001
                    device.availability = True

                elif self.probe(device.ip, 3000):
                    device.port = 3000
                    device.availability = True

                else:
                    device.availability = False

                devices[device.identity] = device

        finally:
            sock.close()

        return list(devices.values())

    def discover_async(
        self,
        callback: Callable[
            [List[TVDevice], Optional[Exception]],
            None,
        ],
    ) -> None:
        def run() -> None:
            try:
                callback(self.discover(), None)
            except Exception as exc:
                callback([], exc)

        threading.Thread(
            target=run,
            daemon=True,
            name="fahd-discovery",
        ).start()

    def stop(self) -> None:
        self.stop_event.set()


# ============================================================
# TV CONNECTION
# ============================================================

class TVConnection:
    def __init__(
        self,
        device: TVDevice,
        settings: SettingsManager,
        timeout: float = 8.0,
    ) -> None:
        self.device = device
        self.settings = settings
        self.timeout = timeout

        self.ws: Optional[Any] = None
        self.pointer_ws: Optional[Any] = None

        self.connected = False
        self.registered = False
        self.closing = False

        self.last_error = ""
        self.latency_ms: Optional[float] = None

        self._counter = 0
        self._counter_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pointer_lock = threading.Lock()

        self._pending: Dict[str, queue.Queue] = {}
        self._pending_lock = threading.Lock()

        self.disconnect_callback: Optional[
            Callable[[str], None]
        ] = None

    @property
    def url(self) -> str:
        protocol = (
            "wss"
            if self.device.port == 3001
            else "ws"
        )

        return (
            f"{protocol}://"
            f"{self.device.ip}:"
            f"{self.device.port}/"
        )

    def next_id(self) -> str:
        with self._counter_lock:
            self._counter += 1

            return (
                f"fahd_"
                f"{self._counter}_"
                f"{uuid.uuid4().hex[:5]}"
            )

    @staticmethod
    def manifest() -> Dict[str, Any]:
        permissions = [
            "LAUNCH",
            "LAUNCH_WEBAPP",
            "APP_TO_APP",
            "CLOSE",
            "CONTROL_AUDIO",
            "CONTROL_DISPLAY",
            "CONTROL_INPUT_JOYSTICK",
            "CONTROL_INPUT_MEDIA_PLAYBACK",
            "CONTROL_INPUT_TV",
            "CONTROL_POWER",
            "READ_APP_STATUS",
            "READ_CURRENT_CHANNEL",
            "READ_INPUT_DEVICE_LIST",
            "READ_NETWORK_STATE",
            "READ_RUNNING_APPS",
            "READ_TV_CHANNEL_LIST",
            "READ_POWER_STATE",
            "CONTROL_MOUSE_AND_KEYBOARD",
            "CONTROL_INPUT_TEXT",
        ]

        return {
            "manifestVersion": 1,
            "appVersion": "1.0",
            "permissions": permissions,
        }

    def connect(self) -> None:
        self.close()
        self.closing = False

        options: Dict[str, Any] = {
            "timeout": self.timeout,
            "origin": "http://localhost",
        }

        if self.url.startswith("wss://"):
            options["sslopt"] = {
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False,
            }

        started = time.monotonic()

        try:
            self.ws = websocket.create_connection(
                self.url,
                **options,
            )

            self.ws.settimeout(1.0)

        except (
            socket.timeout,
            TimeoutError,
            websocket.WebSocketTimeoutException,
        ) as exc:
            self.last_error = "timeout"
            raise ConnectionTimeout() from exc

        except Exception as exc:
            self.last_error = "connect"
            raise ConnectionFailure() from exc

        self.connected = True

        self.latency_ms = (
            time.monotonic() - started
        ) * 1000

        threading.Thread(
            target=self._reader,
            daemon=True,
            name="fahd-websocket",
        ).start()

        self.register()

    def _reader(self) -> None:
        while self.connected and not self.closing:
            current = self.ws

            if current is None:
                return

            try:
                raw = current.recv()

            except websocket.WebSocketTimeoutException:
                continue

            except Exception:
                if not self.closing:
                    self._disconnected("socket")
                return

            if not raw:
                if not self.closing:
                    self._disconnected("closed")
                return

            try:
                message = json.loads(raw)
            except (ValueError, TypeError):
                self.last_error = "malformed"
                continue

            if not isinstance(message, dict):
                continue

            request_id = str(message.get("id", ""))

            if not request_id:
                continue

            with self._pending_lock:
                waiter = self._pending.get(request_id)

            if waiter is not None:
                waiter.put(message)

    def _disconnected(self, reason: str) -> None:
        self.connected = False
        self.registered = False
        self.last_error = reason

        with self._pending_lock:
            waiters = list(self._pending.values())

        for waiter in waiters:
            try:
                waiter.put_nowait(
                    {
                        "type": "error",
                        "error": "connection closed",
                    }
                )
            except queue.Full:
                continue

        if self.disconnect_callback:
            self.disconnect_callback(reason)

    def send_json(self, message: Dict[str, Any]) -> None:
        if not self.connected or self.ws is None:
            raise ConnectionFailure()

        raw = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        try:
            with self._send_lock:
                self.ws.send(raw)

        except Exception as exc:
            self._disconnected("send")
            raise ConnectionFailure() from exc

    def wait_response(
        self,
        request_id: str,
        waiter: queue.Queue,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            try:
                result = waiter.get(
                    timeout=timeout or self.timeout
                )
            except queue.Empty as exc:
                raise ConnectionTimeout() from exc

        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        if not isinstance(result, dict):
            raise ProtocolError()

        if result.get("type") == "error":
            raise ProtocolError(
                str(result.get("error", "TV error"))
            )

        return result

    def request(
        self,
        uri: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        request_id = self.next_id()

        waiter: queue.Queue = queue.Queue(maxsize=2)

        with self._pending_lock:
            self._pending[request_id] = waiter

        self.send_json(
            {
                "id": request_id,
                "type": "request",
                "uri": uri,
                "payload": payload or {},
            }
        )

        return self.wait_response(
            request_id,
            waiter,
            timeout,
        )

    def register(self) -> None:
        request_id = self.next_id()
        waiter: queue.Queue = queue.Queue(maxsize=8)

        with self._pending_lock:
            self._pending[request_id] = waiter

        payload: Dict[str, Any] = {
            "pairingType": "PROMPT",
            "manifest": self.manifest(),
        }

        client_key = self.settings.get_client_key(
            self.device
        )

        if client_key:
            payload["client-key"] = client_key

        self.send_json(
            {
                "id": request_id,
                "type": "register",
                "payload": payload,
            }
        )

        deadline = time.monotonic() + self.timeout

        try:
            while True:
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    raise ConnectionTimeout()

                try:
                    response = waiter.get(timeout=remaining)
                except queue.Empty as exc:
                    raise ConnectionTimeout() from exc

                response_type = response.get("type")

                if response_type == "registered":
                    data = response.get("payload", {})

                    if isinstance(data, dict):
                        key = data.get("client-key")

                        if isinstance(key, str) and key:
                            self.settings.set_client_key(
                                self.device,
                                key,
                            )

                    self.registered = True
                    return

                if response_type == "error":
                    raise ProtocolError(
                        str(
                            response.get(
                                "error",
                                "Pairing rejected",
                            )
                        )
                    )

        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def open_pointer(self) -> None:
        result = self.request(
            "ssap://com.webos.service.networkinput/"
            "getPointerInputSocket"
        )

        payload = result.get("payload", {})

        if not isinstance(payload, dict):
            raise UnsupportedFeature(UNSUPPORTED_MESSAGE)

        path = payload.get("socketPath")

        if not isinstance(path, str) or not path:
            raise UnsupportedFeature(UNSUPPORTED_MESSAGE)

        options: Dict[str, Any] = {
            "timeout": self.timeout,
            "origin": "http://localhost",
        }

        if path.startswith("wss://"):
            options["sslopt"] = {
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False,
            }

        try:
            pointer = websocket.create_connection(
                path,
                **options,
            )
        except Exception as exc:
            raise UnsupportedFeature(
                UNSUPPORTED_MESSAGE
            ) from exc

        with self._pointer_lock:
            old = self.pointer_ws
            self.pointer_ws = pointer

        if old is not None:
            try:
                old.close()
            except Exception:
                return

    def pointer_packet(
        self,
        kind: str,
        **values: Any,
    ) -> None:
        lines = [f"type:{kind}"]

        for name, value in values.items():
            lines.append(f"{name}:{value}")

        packet = "\n".join(lines) + "\n\n"

        with self._pointer_lock:
            if self.pointer_ws is None:
                raise UnsupportedFeature(
                    UNSUPPORTED_MESSAGE
                )

            try:
                self.pointer_ws.send(packet)
            except Exception as exc:
                raise ConnectionFailure() from exc

    def close(self) -> None:
        self.closing = True
        self.connected = False
        self.registered = False

        pointer = self.pointer_ws
        control = self.ws

        self.pointer_ws = None
        self.ws = None

        for item in (pointer, control):
            if item is not None:
                try:
                    item.close()
                except Exception:
                    continue


# ============================================================
# TV CONTROLLERS
# ============================================================

class BaseTVController(abc.ABC):
    def __init__(
        self,
        device: TVDevice,
        connection: TVConnection,
    ) -> None:
        self.device = device
        self.connection = connection

    def require(self, capability: str) -> None:
        if not self.device.supports(capability):
            raise UnsupportedFeature(
                UNSUPPORTED_MESSAGE
            )

    @abc.abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def command(self, command: str) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def pointer_move(self, dx: int, dy: int) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def text(self, value: str) -> None:
        raise NotImplementedError


class LGWebOSController(BaseTVController):
    POINTER_BUTTONS = {
        "UP": "UP",
        "DOWN": "DOWN",
        "LEFT": "LEFT",
        "RIGHT": "RIGHT",
        "OK": "ENTER",
        "HOME": "HOME",
        "BACK": "BACK",
        "MENU": "MENU",
        "GUIDE": "GUIDE",
        "SETTINGS": "SETTINGS",
        "PLAY": "PLAY",
        "PAUSE": "PAUSE",
        "STOP": "STOP",
        "REWIND": "REWIND",
        "FAST_FORWARD": "FASTFORWARD",
        "RED": "RED",
        "GREEN": "GREEN",
        "YELLOW": "YELLOW",
        "BLUE": "BLUE",
    }

    APPS = {
        "NETFLIX": "netflix",
        "YOUTUBE": "youtube.leanback.v4",
        "PRIME": "amazon",
    }

    def connect(self) -> None:
        self.connection.connect()
        self.detect_capabilities()

    def detect_capabilities(self) -> None:
        caps = dict(DEFAULT_CAPABILITIES)

        try:
            self.connection.open_pointer()
            caps["pointer"] = True
        except FahdError:
            caps["pointer"] = False

        checks = {
            "volume": "ssap://audio/getVolume",
            "channels": "ssap://tv/getCurrentChannel",
            "apps": (
                "ssap://com.webos.applicationManager/listApps"
            ),
        }

        for capability, uri in checks.items():
            try:
                self.connection.request(
                    uri,
                    timeout=2.0,
                )
                caps[capability] = True
            except FahdError:
                caps[capability] = False

        try:
            self.connection.request(
                "ssap://com.webos.service.ime/getEditorInfo",
                timeout=2.0,
            )

            caps["keyboard"] = True

        except FahdError:
            caps["keyboard"] = False

        caps["media"] = caps["pointer"]
        caps["microphone"] = False

        self.device.capabilities = caps

    def pointer_move(self, dx: int, dy: int) -> None:
        self.require("pointer")

        self.connection.pointer_packet(
            "move",
            dx=int(dx),
            dy=int(dy),
            down=0,
        )

    def pointer_click(self) -> None:
        self.require("pointer")
        self.connection.pointer_packet("click")

    def pointer_button(self, name: str) -> None:
        self.require("pointer")

        mapped = self.POINTER_BUTTONS.get(name)

        if mapped is None:
            raise UnsupportedFeature(
                UNSUPPORTED_MESSAGE
            )

        self.connection.pointer_packet(
            "button",
            name=mapped,
        )

    def command(self, command: str) -> None:
        command = command.upper()

        if command in self.POINTER_BUTTONS:
            self.pointer_button(command)
            return

        if command == "POWER":
            self.connection.request(
                "ssap://system/turnOff"
            )
            return

        if command == "VOLUME_UP":
            self.require("volume")
            self.connection.request(
                "ssap://audio/volumeUp"
            )
            return

        if command == "VOLUME_DOWN":
            self.require("volume")
            self.connection.request(
                "ssap://audio/volumeDown"
            )
            return

        if command == "MUTE":
            self.require("volume")

            result = self.connection.request(
                "ssap://audio/getStatus"
            )

            payload = result.get("payload", {})

            muted = (
                bool(payload.get("mute", False))
                if isinstance(payload, dict)
                else False
            )

            self.connection.request(
                "ssap://audio/setMute",
                {"mute": not muted},
            )
            return

        if command == "CHANNEL_UP":
            self.require("channels")
            self.connection.request(
                "ssap://tv/channelUp"
            )
            return

        if command == "CHANNEL_DOWN":
            self.require("channels")
            self.connection.request(
                "ssap://tv/channelDown"
            )
            return

        if command in self.APPS:
            self.require("apps")

            self.connection.request(
                "ssap://system.launcher/launch",
                {"id": self.APPS[command]},
            )
            return

        if command.isdigit() and len(command) == 1:
            self.require("pointer")

            self.connection.pointer_packet(
                "button",
                name=command,
            )
            return

        raise UnsupportedFeature(
            UNSUPPORTED_MESSAGE
        )

    def text(self, value: str) -> None:
        self.require("keyboard")

        if not value:
            return

        self.connection.request(
            "ssap://com.webos.service.ime/insertText",
            {
                "text": value,
                "replace": 0,
            },
        )

    def backspace(self) -> None:
        self.require("keyboard")

        self.connection.request(
            "ssap://com.webos.service.ime/deleteCharacters",
            {"count": 1},
        )


# ============================================================
# POINTER
# ============================================================

class PointerController:
    def __init__(
        self,
        controller: LGWebOSController,
        sensitivity: float,
        acceleration: float,
        dead_zone: float,
        max_speed: float,
        interval: float = 0.03,
    ) -> None:
        self.controller = controller

        self.sensitivity = sensitivity
        self.acceleration = acceleration
        self.dead_zone = dead_zone
        self.max_speed = max_speed

        self.interval = max(
            0.02,
            min(interval, 0.04),
        )

        self.pending_dx = 0.0
        self.pending_dy = 0.0

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()

        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="fahd-pointer",
        )

        self._thread.start()

    def transform(
        self,
        dx: float,
        dy: float,
    ) -> Tuple[float, float]:
        magnitude = math.hypot(dx, dy)

        if magnitude <= self.dead_zone:
            return 0.0, 0.0

        dx *= self.sensitivity
        dy *= self.sensitivity

        magnitude = math.hypot(dx, dy)

        if magnitude and self.acceleration:
            factor = (
                1.0
                + self.acceleration
                * math.sqrt(magnitude)
            )

            dx *= factor
            dy *= factor

        magnitude = math.hypot(dx, dy)

        if magnitude > self.max_speed:
            scale = self.max_speed / magnitude
            dx *= scale
            dy *= scale

        return dx, dy

    def move(self, dx: float, dy: float) -> None:
        dx, dy = self.transform(dx, dy)

        if dx == 0 and dy == 0:
            return

        with self._lock:
            self.pending_dx += dx
            self.pending_dy += dy

        self._wake.set()

    def flush(self) -> None:
        with self._lock:
            dx = self.pending_dx
            dy = self.pending_dy

            self.pending_dx = 0.0
            self.pending_dy = 0.0

        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return

        try:
            self.controller.pointer_move(
                round(dx),
                round(dy),
            )
        except FahdError:
            return

    def click(self) -> None:
        self.controller.pointer_click()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.interval)
            self._wake.clear()

            self.flush()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()


# ============================================================
# REMOTE
# ============================================================

class RemoteController:
    def __init__(
        self,
        controller: LGWebOSController,
    ) -> None:
        self.controller = controller

        self._hold_lock = threading.Lock()
        self._hold_token = 0

    def send(self, command: str) -> None:
        self.controller.command(command)

    def start_hold(self, command: str) -> None:
        self.stop_hold()

        with self._hold_lock:
            self._hold_token += 1
            token = self._hold_token

        self.send(command)

        def repeat() -> None:
            if not self._wait(token, 0.38):
                return

            while self._active(token):
                try:
                    self.send(command)
                except FahdError:
                    return

                if not self._wait(token, 0.12):
                    return

        threading.Thread(
            target=repeat,
            daemon=True,
            name="fahd-repeat",
        ).start()

    def _active(self, token: int) -> bool:
        with self._hold_lock:
            return token == self._hold_token

    def _wait(self, token: int, duration: float) -> bool:
        end = time.monotonic() + duration

        while time.monotonic() < end:
            if not self._active(token):
                return False

            threading.Event().wait(0.015)

        return self._active(token)

    def stop_hold(self) -> None:
        with self._hold_lock:
            self._hold_token += 1


# ============================================================
# KEYBOARD
# ============================================================

class KeyboardController:
    def __init__(
        self,
        controller: LGWebOSController,
    ) -> None:
        self.controller = controller

        self.last_text = ""
        self.last_time = 0.0
        self.lock = threading.Lock()

    def send_text(self, value: str) -> None:
        if not self.controller.device.supports("keyboard"):
            raise UnsupportedFeature(
                KEYBOARD_UNSUPPORTED
            )

        now = time.monotonic()

        with self.lock:
            if (
                value == self.last_text
                and now - self.last_time < 0.08
            ):
                return

            self.last_text = value
            self.last_time = now

        self.controller.text(value)

    def backspace(self) -> None:
        if not self.controller.device.supports("keyboard"):
            raise UnsupportedFeature(
                KEYBOARD_UNSUPPORTED
            )

        self.controller.backspace()


# ============================================================
# BASIC UI
# ============================================================

class ArabicLabel(Label):
    def __init__(self, text: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("color", TEXT)
        kwargs.setdefault("font_size", "16sp")

        super().__init__(
            text=ar(text),
            **kwargs,
        )

    def set_text(self, value: str) -> None:
        self.text = ar(value)


class PremiumButton(Button):
    def __init__(
        self,
        text: str = "",
        *,
        accent: Optional[Tuple[float, float, float, float]] = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault(
            "background_color",
            (0, 0, 0, 0),
        )
        kwargs.setdefault("color", TEXT)
        kwargs.setdefault("font_size", "15sp")

        super().__init__(
            text=ar(text),
            **kwargs,
        )

        self.normal_color = accent or SURFACE_2

        with self.canvas.before:
            self.bg_color = Color(
                *self.normal_color
            )

            self.bg = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(18)],
            )

            self.border_color = Color(
                0.25,
                0.28,
                0.32,
                0.25,
            )

            self.outline_line = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    dp(18),
                ),
                width=1,
            )

        self.bind(
            pos=self._graphics,
            size=self._graphics,
            state=self._state,
        )

    def _graphics(self, *_args: Any) -> None:
        self.bg.pos = self.pos
        self.bg.size = self.size

        self.outline_line.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            dp(18),
        )

    def _state(self, *_args: Any) -> None:
        if self.state == "down":
            self.bg_color.rgba = SURFACE_3

            Animation.cancel_all(self)

            Animation(
                opacity=0.82,
                duration=0.06,
            ).start(self)
        else:
            self.bg_color.rgba = self.normal_color

            Animation(
                opacity=1,
                duration=0.10,
            ).start(self)


class CircleButton(Button):
    def __init__(
        self,
        text: str,
        color: Tuple[float, float, float, float] = SURFACE_2,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault(
            "background_color",
            (0, 0, 0, 0),
        )
        kwargs.setdefault("color", TEXT)

        super().__init__(
            text=ar(text),
            **kwargs,
        )

        self.base_color = color

        with self.canvas.before:
            self.circle_color = Color(*color)

            self.circle = Ellipse(
                pos=self.pos,
                size=self.size,
            )

            self.ring_color = Color(
                0.45,
                0.48,
                0.55,
                0.22,
            )

            self.ring = Line(
                ellipse=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                ),
                width=1,
            )

        self.bind(
            pos=self.update_circle,
            size=self.update_circle,
            state=self.update_state,
        )

    def update_circle(self, *_args: Any) -> None:
        size = min(
            self.width,
            self.height,
        )

        x = self.center_x - size / 2
        y = self.center_y - size / 2

        self.circle.pos = (x, y)
        self.circle.size = (size, size)

        self.ring.ellipse = (
            x,
            y,
            size,
            size,
        )

    def update_state(self, *_args: Any) -> None:
        if self.state == "down":
            self.circle_color.rgba = SURFACE_3
        else:
            self.circle_color.rgba = self.base_color


class GlassCard(BoxLayout):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("padding", dp(16))
        kwargs.setdefault("spacing", dp(8))

        super().__init__(**kwargs)

        with self.canvas.before:
            Color(*SURFACE)

            self.shape = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(24)],
            )

            Color(
                0.38,
                0.41,
                0.47,
                0.18,
            )

            self.outline = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    dp(24),
                ),
                width=1,
            )

        self.bind(
            pos=self.update_graphics,
            size=self.update_graphics,
        )

    def update_graphics(self, *_args: Any) -> None:
        self.shape.pos = self.pos
        self.shape.size = self.size

        self.outline.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            dp(24),
        )


# ============================================================
# TOUCHPAD
# ============================================================

class TouchPad(Widget):
    def __init__(
        self,
        pointer: PointerController,
        error_callback: Callable[[Exception], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.pointer = pointer
        self.error_callback = error_callback

        self.active_touch: Optional[Any] = None
        self.last_position: Optional[
            Tuple[float, float]
        ] = None

        self.start_position = (0.0, 0.0)
        self.start_time = 0.0
        self.distance = 0.0

        with self.canvas.before:
            Color(
                0.055,
                0.060,
                0.071,
                1,
            )

            self.background = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(30)],
            )

            Color(
                0.45,
                0.49,
                0.56,
                0.22,
            )

            self.outline_line = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    dp(30),
                ),
                width=1.1,
            )

        self.bind(
            pos=self.update_graphics,
            size=self.update_graphics,
        )

    def update_graphics(self, *_args: Any) -> None:
        self.background.pos = self.pos
        self.background.size = self.size

        self.outline_line.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            dp(30),
        )

    def on_touch_down(self, touch: Any) -> bool:
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        touch.grab(self)

        self.active_touch = touch
        self.last_position = touch.pos
        self.start_position = touch.pos

        self.start_time = time.monotonic()
        self.distance = 0.0

        return True

    def on_touch_move(self, touch: Any) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_move(touch)

        if self.last_position is None:
            self.last_position = touch.pos
            return True

        dx = touch.x - self.last_position[0]
        dy = touch.y - self.last_position[1]

        self.distance += math.hypot(dx, dy)

        self.last_position = touch.pos

        self.pointer.move(dx, dy)

        return True

    def on_touch_up(self, touch: Any) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_up(touch)

        elapsed = (
            time.monotonic()
            - self.start_time
        )

        if (
            self.distance <= dp(9)
            and elapsed <= 0.35
        ):
            try:
                self.pointer.click()
            except Exception as exc:
                self.error_callback(exc)

        touch.ungrab(self)

        self.active_touch = None
        self.last_position = None

        return True


# ============================================================
# HEADER / NAVIGATION
# ============================================================

class AppHeader(BoxLayout):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(62),
            spacing=dp(8),
            **kwargs,
        )

        logo = BoxLayout(
            orientation="vertical",
        )

        logo.add_widget(
            ArabicLabel(
                "فهد",
                font_size="25sp",
                bold=True,
                halign="left",
                valign="bottom",
            )
        )

        logo.add_widget(
            Label(
                text="FAHD SMART REMOTE",
                font_name="Roboto",
                font_size="9sp",
                color=MUTED,
                halign="left",
                valign="top",
            )
        )

        self.add_widget(logo)

        self.status = ArabicLabel(
            "غير متصل",
            font_size="12sp",
            color=MUTED,
            size_hint_x=0.40,
        )

        self.add_widget(self.status)

        settings = CircleButton(
            "⚙",
            size_hint=(None, None),
            size=(dp(46), dp(46)),
        )

        settings.bind(
            on_release=lambda _button:
            app_ref.change_screen("settings")
        )

        self.add_widget(settings)

    def update_status(self, connected: bool) -> None:
        if connected:
            self.status.set_text("● متصل")
            self.status.color = GREEN
        else:
            self.status.set_text("● غير متصل")
            self.status.color = MUTED


class BottomNavigation(BoxLayout):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(64),
            spacing=dp(6),
            padding=(dp(4), dp(7)),
            **kwargs,
        )

        for caption, screen in (
            ("الرئيسية", "home"),
            ("الريموت", "remote"),
            ("الإعدادات", "settings"),
        ):
            button = PremiumButton(
                caption,
                size_hint_y=1,
            )

            button.bind(
                on_release=lambda _button, destination=screen:
                app_ref.change_screen(destination)
            )

            self.add_widget(button)


# ============================================================
# HOME
# ============================================================

class HomeScreen(Screen):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.app_ref = app_ref

        root = BoxLayout(
            orientation="vertical",
            padding=(
                dp(18),
                dp(14),
                dp(18),
                dp(10),
            ),
            spacing=dp(14),
        )

        self.header = AppHeader(app_ref)
        root.add_widget(self.header)

        root.add_widget(
            ArabicLabel(
                "تحكم ذكي، ببساطة",
                font_size="23sp",
                bold=True,
                size_hint_y=None,
                height=dp(48),
            )
        )

        self.tv_card = GlassCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(155),
        )

        self.tv_name = ArabicLabel(
            "لا يوجد تلفزيون متصل",
            font_size="20sp",
            bold=True,
        )

        self.tv_info = ArabicLabel(
            "ابحث عن تلفزيون LG webOS على الشبكة",
            color=MUTED,
            font_size="13sp",
        )

        self.tv_state = ArabicLabel(
            "● غير متصل",
            color=MUTED,
            font_size="13sp",
        )

        self.tv_card.add_widget(self.tv_name)
        self.tv_card.add_widget(self.tv_info)
        self.tv_card.add_widget(self.tv_state)

        root.add_widget(self.tv_card)

        remote_button = PremiumButton(
            "فتح الريموت",
            size_hint_y=None,
            height=dp(58),
            accent=(
                0.15,
                0.17,
                0.21,
                1,
            ),
        )

        remote_button.bind(
            on_release=lambda _button:
            app_ref.open_remote()
        )

        root.add_widget(remote_button)

        scan_button = PremiumButton(
            "البحث عن تلفزيون",
            size_hint_y=None,
            height=dp(54),
        )

        scan_button.bind(
            on_release=lambda _button:
            app_ref.start_scan()
        )

        root.add_widget(scan_button)

        root.add_widget(
            ArabicLabel(
                "الأجهزة المحفوظة",
                color=MUTED,
                font_size="13sp",
                size_hint_y=None,
                height=dp(32),
            )
        )

        self.saved = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(7),
        )

        self.saved.bind(
            minimum_height=self.saved.setter("height")
        )

        scroll = ScrollView()
        scroll.add_widget(self.saved)

        root.add_widget(scroll)
        root.add_widget(BottomNavigation(app_ref))

        self.add_widget(root)

    def refresh(self) -> None:
        controller = self.app_ref.controller

        connected = (
            controller is not None
            and controller.connection.connected
        )

        self.header.update_status(connected)

        if controller is None:
            self.tv_name.set_text(
                "لا يوجد تلفزيون متصل"
            )

            self.tv_info.set_text(
                "ابحث عن تلفزيون LG webOS على الشبكة"
            )

            self.tv_state.set_text(
                "● غير متصل"
            )

            self.tv_state.color = MUTED

        else:
            device = controller.device

            self.tv_name.set_text(
                device.name
            )

            description = "LG webOS"

            if device.model:
                description += f" • {device.model}"

            self.tv_info.text = description

            if connected:
                self.tv_state.set_text("● متصل")
                self.tv_state.color = GREEN
            else:
                self.tv_state.set_text("● تم فصل الاتصال")
                self.tv_state.color = RED

        self.saved.clear_widgets()

        for device in self.app_ref.settings.saved_tvs():
            button = PremiumButton(
                f"{device.name}  •  {device.ip}",
                size_hint_y=None,
                height=dp(52),
            )

            button.bind(
                on_release=lambda _button, selected=device:
                self.app_ref.connect_device(selected)
            )

            self.saved.add_widget(button)


# ============================================================
# DISCOVERY SCREEN
# ============================================================

class DiscoveryScreen(Screen):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.app_ref = app_ref

        root = BoxLayout(
            orientation="vertical",
            padding=dp(18),
            spacing=dp(12),
        )

        root.add_widget(AppHeader(app_ref))

        root.add_widget(
            ArabicLabel(
                "البحث عن التلفزيون",
                font_size="26sp",
                bold=True,
                size_hint_y=None,
                height=dp(58),
            )
        )

        self.state = ArabicLabel(
            "جاري البحث...",
            color=MUTED,
            size_hint_y=None,
            height=dp(50),
        )

        root.add_widget(self.state)

        self.devices = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(9),
        )

        self.devices.bind(
            minimum_height=self.devices.setter("height")
        )

        scroll = ScrollView()
        scroll.add_widget(self.devices)

        root.add_widget(scroll)

        back = PremiumButton(
            "رجوع",
            size_hint_y=None,
            height=dp(52),
        )

        back.bind(
            on_release=lambda _button:
            app_ref.change_screen("home")
        )

        root.add_widget(back)

        self.add_widget(root)

    def set_state(self, value: str) -> None:
        self.state.set_text(value)

    def show_devices(
        self,
        devices: List[TVDevice],
    ) -> None:
        self.devices.clear_widgets()

        if not devices:
            self.set_state(
                "لم يتم العثور على أجهزة LG."
            )
            return

        self.set_state(
            "اختر التلفزيون الذي تريد الاتصال به"
        )

        for device in devices:
            text = device.name

            if device.model:
                text += f" • {device.model}"

            text += (
                " • Available"
                if device.availability
                else " • Offline"
            )

            button = PremiumButton(
                text,
                size_hint_y=None,
                height=dp(62),
            )

            button.disabled = not device.availability

            button.bind(
                on_release=lambda _button, chosen=device:
                self.app_ref.connect_device(chosen)
            )

            self.devices.add_widget(button)


# ============================================================
# D-PAD
# ============================================================

class DPad(GridLayout):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            cols=3,
            rows=3,
            spacing=dp(4),
            **kwargs,
        )

        cells = [
            None,
            ("↑", "UP"),
            None,
            ("←", "LEFT"),
            ("OK", "OK"),
            ("→", "RIGHT"),
            None,
            ("↓", "DOWN"),
            None,
        ]

        for item in cells:
            if item is None:
                self.add_widget(Widget())
                continue

            text, command = item

            button = CircleButton(
                text,
                font_size=(
                    "17sp"
                    if command == "OK"
                    else "25sp"
                ),
            )

            if command == "OK":
                button.bind(
                    on_release=lambda _button:
                    app_ref.send_command("OK")
                )
            else:
                button.bind(
                    on_press=lambda _button, cmd=command:
                    app_ref.start_hold(cmd)
                )

                button.bind(
                    on_release=lambda _button:
                    app_ref.stop_hold()
                )

            self.add_widget(button)


# ============================================================
# REMOTE SCREEN
# ============================================================

class RemoteScreen(Screen):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.app_ref = app_ref

        self.root_layout = BoxLayout(
            orientation="vertical",
            padding=(
                dp(14),
                dp(10),
                dp(14),
                dp(8),
            ),
            spacing=dp(8),
        )

        self.add_widget(self.root_layout)

    def on_pre_enter(self, *_args: Any) -> None:
        self.rebuild()

    def command_button(
        self,
        caption: str,
        command: str,
    ) -> PremiumButton:
        button = PremiumButton(caption)

        button.bind(
            on_release=lambda _button:
            self.app_ref.send_command(command)
        )

        return button

    def rebuild(self) -> None:
        self.root_layout.clear_widgets()

        controller = self.app_ref.controller

        header = AppHeader(self.app_ref)

        header.update_status(
            bool(
                controller
                and controller.connection.connected
            )
        )

        self.root_layout.add_widget(header)

        if controller is None:
            card = GlassCard(
                orientation="vertical",
            )

            card.add_widget(
                ArabicLabel(
                    "لا يوجد تلفزيون متصل",
                    font_size="21sp",
                    bold=True,
                )
            )

            card.add_widget(
                ArabicLabel(
                    "اتصل بتلفزيون LG لفتح أدوات الريموت.",
                    color=MUTED,
                )
            )

            scan = PremiumButton(
                "البحث عن تلفزيون",
                size_hint_y=None,
                height=dp(56),
            )

            scan.bind(
                on_release=lambda _button:
                self.app_ref.start_scan()
            )

            card.add_widget(scan)

            self.root_layout.add_widget(card)
            self.root_layout.add_widget(
                BottomNavigation(self.app_ref)
            )

            return

        top = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(58),
            spacing=dp(8),
        )

        title = ArabicLabel(
            controller.device.name,
            font_size="16sp",
            bold=True,
        )

        power = CircleButton(
            "⏻",
            color=(
                0.32,
                0.07,
                0.08,
                1,
            ),
            size_hint=(None, None),
            size=(dp(55), dp(55)),
            font_size="25sp",
        )

        power.bind(
            on_release=lambda _button:
            self.app_ref.send_command("POWER")
        )

        top.add_widget(title)
        top.add_widget(power)

        self.root_layout.add_widget(top)

        if controller.device.supports("pointer"):
            pointer = self.app_ref.pointer

            if pointer:
                touchpad_box = FloatLayout(
                    size_hint_y=0.28,
                )

                pad = TouchPad(
                    pointer,
                    self.app_ref.show_error,
                    size_hint=(1, 1),
                )

                hint = ArabicLabel(
                    "المس للتحريك • ضغطة للاختيار",
                    color=(
                        0.48,
                        0.51,
                        0.57,
                        0.65,
                    ),
                    font_size="11sp",
                    size_hint=(1, None),
                    height=dp(35),
                    pos_hint={
                        "center_x": 0.5,
                        "center_y": 0.5,
                    },
                )

                touchpad_box.add_widget(pad)
                touchpad_box.add_widget(hint)

                self.root_layout.add_widget(
                    touchpad_box
                )

            dpad = DPad(
                self.app_ref,
                size_hint_y=None,
                height=dp(168),
            )

            self.root_layout.add_widget(dpad)

        if (
            controller.device.supports("volume")
            or controller.device.supports("channels")
        ):
            rockers = GridLayout(
                cols=3,
                size_hint_y=None,
                height=dp(96),
                spacing=dp(7),
            )

            if controller.device.supports("volume"):
                volume = BoxLayout(
                    orientation="vertical",
                    spacing=dp(4),
                )

                volume.add_widget(
                    self.command_button(
                        "VOL +",
                        "VOLUME_UP",
                    )
                )

                volume.add_widget(
                    self.command_button(
                        "VOL −",
                        "VOLUME_DOWN",
                    )
                )

                rockers.add_widget(volume)
            else:
                rockers.add_widget(Widget())

            center = BoxLayout(
                orientation="vertical",
                spacing=dp(4),
            )

            center.add_widget(
                self.command_button(
                    "HOME",
                    "HOME",
                )
            )

            if controller.device.supports("volume"):
                center.add_widget(
                    self.command_button(
                        "MUTE",
                        "MUTE",
                    )
                )
            else:
                center.add_widget(Widget())

            rockers.add_widget(center)

            if controller.device.supports("channels"):
                channel = BoxLayout(
                    orientation="vertical",
                    spacing=dp(4),
                )

                channel.add_widget(
                    self.command_button(
                        "CH +",
                        "CHANNEL_UP",
                    )
                )

                channel.add_widget(
                    self.command_button(
                        "CH −",
                        "CHANNEL_DOWN",
                    )
                )

                rockers.add_widget(channel)
            else:
                rockers.add_widget(Widget())

            self.root_layout.add_widget(rockers)

        if controller.device.supports("media"):
            media = GridLayout(
                cols=5,
                size_hint_y=None,
                height=dp(48),
                spacing=dp(5),
            )

            for caption, command in (
                ("⏪", "REWIND"),
                ("▶", "PLAY"),
                ("Ⅱ", "PAUSE"),
                ("■", "STOP"),
                ("⏩", "FAST_FORWARD"),
            ):
                media.add_widget(
                    self.command_button(
                        caption,
                        command,
                    )
                )

            self.root_layout.add_widget(media)

        tools = GridLayout(
            cols=3,
            size_hint_y=None,
            height=dp(48),
            spacing=dp(5),
        )

        numbers = PremiumButton("123")
        numbers.bind(
            on_release=lambda _button:
            self.app_ref.open_numbers()
        )

        tools.add_widget(numbers)

        keyboard = PremiumButton("Keyboard")

        keyboard.disabled = (
            not controller.device.supports(
                "keyboard"
            )
        )

        keyboard.bind(
            on_release=lambda _button:
            self.app_ref.open_keyboard()
        )

        tools.add_widget(keyboard)

        back = self.command_button(
            "BACK",
            "BACK",
        )

        tools.add_widget(back)

        self.root_layout.add_widget(tools)

        if controller.device.supports("apps"):
            apps = GridLayout(
                cols=3,
                size_hint_y=None,
                height=dp(46),
                spacing=dp(5),
            )

            for caption, command in (
                ("Netflix", "NETFLIX"),
                ("Prime Video", "PRIME"),
                ("YouTube", "YOUTUBE"),
            ):
                apps.add_widget(
                    self.command_button(
                        caption,
                        command,
                    )
                )

            self.root_layout.add_widget(apps)


# ============================================================
# NUMBERS
# ============================================================

class NumberScreen(Screen):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=dp(18),
            spacing=dp(14),
        )

        root.add_widget(AppHeader(app_ref))

        root.add_widget(
            ArabicLabel(
                "لوحة الأرقام",
                font_size="25sp",
                bold=True,
                size_hint_y=None,
                height=dp(58),
            )
        )

        grid = GridLayout(
            cols=3,
            spacing=dp(10),
        )

        for number in (
            "1", "2", "3",
            "4", "5", "6",
            "7", "8", "9",
        ):
            button = CircleButton(
                number,
                font_size="23sp",
            )

            button.bind(
                on_release=lambda _button, value=number:
                app_ref.send_command(value)
            )

            grid.add_widget(button)

        grid.add_widget(Widget())

        zero = CircleButton(
            "0",
            font_size="23sp",
        )

        zero.bind(
            on_release=lambda _button:
            app_ref.send_command("0")
        )

        grid.add_widget(zero)
        grid.add_widget(Widget())

        root.add_widget(grid)

        close = PremiumButton(
            "رجوع للريموت",
            size_hint_y=None,
            height=dp(55),
        )

        close.bind(
            on_release=lambda _button:
            app_ref.change_screen("remote")
        )

        root.add_widget(close)

        self.add_widget(root)


# ============================================================
# SETTINGS
# ============================================================

class SettingsScreen(Screen):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.app_ref = app_ref

        root = BoxLayout(
            orientation="vertical",
            padding=dp(18),
            spacing=dp(10),
        )

        root.add_widget(AppHeader(app_ref))

        root.add_widget(
            ArabicLabel(
                "الإعدادات",
                font_size="27sp",
                bold=True,
                size_hint_y=None,
                height=dp(55),
            )
        )

        card = GlassCard(
            orientation="vertical",
        )

        self.sensitivity = self.slider(
            card,
            "حساسية المؤشر",
            0.2,
            3.0,
            float(
                app_ref.settings.get(
                    "pointer_sensitivity",
                    1.0,
                )
            ),
        )

        self.acceleration = self.slider(
            card,
            "تسارع المؤشر",
            0,
            1,
            float(
                app_ref.settings.get(
                    "pointer_acceleration",
                    0.10,
                )
            ),
        )

        self.dead_zone = self.slider(
            card,
            "منطقة تجاهل الحركة",
            0,
            8,
            float(
                app_ref.settings.get(
                    "pointer_dead_zone",
                    0.7,
                )
            ),
        )

        root.add_widget(card)

        save = PremiumButton(
            "حفظ الإعدادات",
            size_hint_y=None,
            height=dp(52),
        )

        save.bind(
            on_release=lambda _button:
            self.save_settings()
        )

        root.add_widget(save)

        diagnostics = PremiumButton(
            "Diagnostics",
            size_hint_y=None,
            height=dp(48),
        )

        diagnostics.bind(
            on_release=lambda _button:
            app_ref.show_diagnostics()
        )

        root.add_widget(diagnostics)

        forget = PremiumButton(
            "حذف التلفزيون المحفوظ",
            size_hint_y=None,
            height=dp(48),
        )

        forget.bind(
            on_release=lambda _button:
            app_ref.forget_current()
        )

        root.add_widget(forget)

        root.add_widget(BottomNavigation(app_ref))

        self.add_widget(root)

    @staticmethod
    def slider(
        parent: BoxLayout,
        title: str,
        minimum: float,
        maximum: float,
        value: float,
    ) -> Slider:
        parent.add_widget(
            ArabicLabel(
                title,
                color=MUTED,
                font_size="13sp",
                size_hint_y=None,
                height=dp(25),
            )
        )

        slider = Slider(
            min=minimum,
            max=maximum,
            value=value,
            size_hint_y=None,
            height=dp(44),
        )

        parent.add_widget(slider)

        return slider

    def save_settings(self) -> None:
        settings = self.app_ref.settings

        settings.set(
            "pointer_sensitivity",
            self.sensitivity.value,
        )

        settings.set(
            "pointer_acceleration",
            self.acceleration.value,
        )

        settings.set(
            "pointer_dead_zone",
            self.dead_zone.value,
        )

        pointer = self.app_ref.pointer

        if pointer:
            pointer.sensitivity = self.sensitivity.value
            pointer.acceleration = self.acceleration.value
            pointer.dead_zone = self.dead_zone.value

        self.app_ref.toast(
            "تم حفظ الإعدادات"
        )


# ============================================================
# DIAGNOSTICS
# ============================================================

class DiagnosticsScreen(Screen):
    def __init__(
        self,
        app_ref: "FahdApp",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.app_ref = app_ref

        root = BoxLayout(
            orientation="vertical",
            padding=dp(18),
            spacing=dp(12),
        )

        root.add_widget(AppHeader(app_ref))

        root.add_widget(
            ArabicLabel(
                "Diagnostics",
                font_size="25sp",
                bold=True,
                size_hint_y=None,
                height=dp(55),
            )
        )

        card = GlassCard(
            orientation="vertical",
        )

        self.info = Label(
            text="",
            font_name="Roboto",
            color=TEXT,
            font_size="14sp",
            halign="left",
            valign="top",
        )

        self.info.bind(
            size=lambda instance, size:
            setattr(instance, "text_size", size)
        )

        card.add_widget(self.info)
        root.add_widget(card)

        back = PremiumButton(
            "رجوع",
            size_hint_y=None,
            height=dp(52),
        )

        back.bind(
            on_release=lambda _button:
            app_ref.change_screen("settings")
        )

        root.add_widget(back)

        self.add_widget(root)

    def refresh(self) -> None:
        controller = self.app_ref.controller

        if controller is None:
            self.info.text = "Connection: disconnected"
            return

        connection = controller.connection
        device = controller.device

        capabilities = ", ".join(
            name
            for name, enabled
            in device.capabilities.items()
            if enabled
        ) or "none"

        latency = (
            f"{connection.latency_ms:.0f} ms"
            if connection.latency_ms is not None
            else "unknown"
        )

        self.info.text = (
            f"Protocol: {device.protocol}\n"
            f"TV: {device.name}\n"
            f"IP: {mask_ip(device.ip)}\n"
            f"Port: {device.port}\n"
            f"Connected: {connection.connected}\n"
            f"Registered: {connection.registered}\n"
            f"Latency: {latency}\n"
            f"Last error: {connection.last_error or 'none'}\n"
            f"Capabilities: {capabilities}"
        )


# ============================================================
# TOAST
# ============================================================

class Toast(FloatLayout):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            size_hint=(0.90, None),
            height=dp(60),
            opacity=0,
            **kwargs,
        )

        with self.canvas.before:
            Color(
                0.09,
                0.10,
                0.12,
                0.98,
            )

            self.bg = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(18)],
            )

        self.label = ArabicLabel(
            "",
            halign="center",
            valign="middle",
        )

        self.add_widget(self.label)

        self.bind(
            pos=self.update_graphics,
            size=self.update_graphics,
        )

    def update_graphics(self, *_args: Any) -> None:
        self.bg.pos = self.pos
        self.bg.size = self.size

        self.label.pos = self.pos
        self.label.size = self.size
        self.label.text_size = self.size

    def show(self, message: str) -> None:
        self.label.set_text(message)

        Animation.cancel_all(self)

        self.opacity = 1

        Clock.schedule_once(
            self.hide,
            2.2,
        )

    def hide(self, _dt: float) -> None:
        Animation(
            opacity=0,
            duration=0.25,
        ).start(self)


# ============================================================
# APP
# ============================================================

class FahdApp(App):
    title = "فهد — FAHD Smart Remote"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.settings: SettingsManager

        self.discovery = TVDiscovery()

        self.connection: Optional[TVConnection] = None
        self.controller: Optional[LGWebOSController] = None

        self.remote: Optional[RemoteController] = None
        self.pointer: Optional[PointerController] = None
        self.keyboard: Optional[KeyboardController] = None

        self.manager: Optional[ScreenManager] = None
        self.toast_widget: Optional[Toast] = None

        self.root_widget: Optional[FloatLayout] = None
        self.keyboard_field: Optional[TextInput] = None
        self.keyboard_previous = ""

        self.generation = 0
        self.closing = False

    def build(self) -> FloatLayout:
        Window.clearcolor = BG

        # Mobile preview while developing on Windows.
        if os.environ.get("ANDROID_ARGUMENT") is None:
            Window.minimum_width = 360
            Window.minimum_height = 640

        self.settings = SettingsManager(
            self.user_data_dir
        )

        manager = ScreenManager(
            transition=FadeTransition(
                duration=0.14
            )
        )

        manager.add_widget(
            HomeScreen(
                self,
                name="home",
            )
        )

        manager.add_widget(
            DiscoveryScreen(
                self,
                name="discovery",
            )
        )

        manager.add_widget(
            RemoteScreen(
                self,
                name="remote",
            )
        )

        manager.add_widget(
            NumberScreen(
                self,
                name="numbers",
            )
        )

        manager.add_widget(
            SettingsScreen(
                self,
                name="settings",
            )
        )

        manager.add_widget(
            DiagnosticsScreen(
                self,
                name="diagnostics",
            )
        )

        self.manager = manager

        root = FloatLayout()

        root.add_widget(manager)

        toast = Toast(
            pos_hint={
                "center_x": 0.5,
                "y": 0.03,
            }
        )

        root.add_widget(toast)

        self.toast_widget = toast
        self.root_widget = root

        Clock.schedule_once(
            lambda _dt: self.refresh_home(),
            0,
        )

        return root

    def on_start(self) -> None:
        """
        Saved devices are shown immediately. We deliberately do not create a
        network connection on Kivy's UI thread.
        """
        self.refresh_home()

    def ui(
        self,
        callback: Callable[..., None],
        *args: Any,
    ) -> None:
        Clock.schedule_once(
            lambda _dt: callback(*args),
            0,
        )

    def toast(self, message: str) -> None:
        if self.toast_widget:
            self.toast_widget.show(message)

    def show_error(self, exc: Exception) -> None:
        self.toast(
            friendly_error(exc)
        )

    def change_screen(self, name: str) -> None:
        if self.manager is None:
            return

        if name == "remote" and self.controller is None:
            self.open_remote()
            return

        self.manager.current = name

    def refresh_home(self) -> None:
        if self.manager is None:
            return

        screen = self.manager.get_screen("home")

        if isinstance(screen, HomeScreen):
            screen.refresh()

    # ========================================================
    # DISCOVERY
    # ========================================================

    def start_scan(self) -> None:
        if self.manager is None:
            return

        screen = self.manager.get_screen(
            "discovery"
        )

        if not isinstance(screen, DiscoveryScreen):
            return

        screen.devices.clear_widgets()
        screen.set_state(
            "جاري البحث عن أجهزة LG webOS..."
        )

        self.manager.current = "discovery"

        self.discovery.discover_async(
            lambda devices, error:
            self.ui(
                self.discovery_finished,
                devices,
                error,
            )
        )

    def discovery_finished(
        self,
        devices: List[TVDevice],
        error: Optional[Exception],
    ) -> None:
        if self.manager is None:
            return

        screen = self.manager.get_screen(
            "discovery"
        )

        if not isinstance(screen, DiscoveryScreen):
            return

        if error:
            screen.set_state(
                friendly_error(error)
            )
            return

        screen.show_devices(devices)

    # ========================================================
    # CONNECTION
    # ========================================================

    def connect_device(
        self,
        device: TVDevice,
    ) -> None:
        if device.protocol != "lg-webos-ssap":
            self.toast(
                "هذا التلفزيون غير مدعوم."
            )
            return

        self.generation += 1
        generation = self.generation

        if self.manager:
            screen = self.manager.get_screen(
                "discovery"
            )

            if isinstance(
                screen,
                DiscoveryScreen,
            ):
                screen.set_state(
                    "جاري الاتصال...\n"
                    "وافق على طلب الاتصال إذا ظهر على شاشة التلفزيون."
                )

            self.manager.current = "discovery"

        threading.Thread(
            target=self._connect_worker,
            args=(device, generation),
            daemon=True,
            name="fahd-connect",
        ).start()

    def _connect_worker(
        self,
        device: TVDevice,
        generation: int,
    ) -> None:
        connection = TVConnection(
            device,
            self.settings,
        )

        controller = LGWebOSController(
            device,
            connection,
        )

        connection.disconnect_callback = (
            lambda reason:
            self._connection_lost(
                generation,
                reason,
            )
        )

        try:
            controller.connect()

        except Exception as exc:
            connection.close()

            self.ui(
                self._connection_failed,
                generation,
                exc,
            )

            return

        self.ui(
            self._connection_success,
            generation,
            controller,
        )

    def _connection_success(
        self,
        generation: int,
        controller: LGWebOSController,
    ) -> None:
        if (
            generation != self.generation
            or self.closing
        ):
            controller.connection.close()
            return

        self.disconnect()

        self.controller = controller
        self.connection = controller.connection

        self.remote = RemoteController(
            controller
        )

        self.pointer = PointerController(
            controller,
            sensitivity=float(
                self.settings.get(
                    "pointer_sensitivity",
                    1.0,
                )
            ),
            acceleration=float(
                self.settings.get(
                    "pointer_acceleration",
                    0.10,
                )
            ),
            dead_zone=float(
                self.settings.get(
                    "pointer_dead_zone",
                    0.7,
                )
            ),
            max_speed=float(
                self.settings.get(
                    "pointer_max_speed",
                    120,
                )
            ),
        )

        self.keyboard = KeyboardController(
            controller
        )

        self.settings.save_tv(
            controller.device
        )

        self.refresh_home()

        if self.manager:
            self.manager.current = "home"

        self.toast(
            "تم الاتصال بالتلفزيون."
        )

    def _connection_failed(
        self,
        generation: int,
        exc: Exception,
    ) -> None:
        if generation != self.generation:
            return

        if self.manager:
            screen = self.manager.get_screen(
                "discovery"
            )

            if isinstance(
                screen,
                DiscoveryScreen,
            ):
                screen.set_state(
                    friendly_error(exc)
                )

        self.show_error(exc)

    def _connection_lost(
        self,
        generation: int,
        _reason: str,
    ) -> None:
        if (
            generation != self.generation
            or self.closing
        ):
            return

        self.ui(
            self._connection_lost_ui
        )

    def _connection_lost_ui(self) -> None:
        self.refresh_home()

        self.toast(
            "تم فصل الاتصال بالتلفزيون."
        )

    def disconnect(self) -> None:
        if self.remote:
            self.remote.stop_hold()

        if self.pointer:
            self.pointer.close()

        if self.connection:
            self.connection.close()

        self.remote = None
        self.pointer = None
        self.keyboard = None

        self.connection = None
        self.controller = None

    # ========================================================
    # REMOTE COMMANDS
    # ========================================================

    def open_remote(self) -> None:
        if self.controller is None:
            self.toast(
                "اتصل بالتلفزيون أولًا."
            )
            return

        if self.manager:
            self.manager.current = "remote"

    def send_command(
        self,
        command: str,
    ) -> None:
        remote = self.remote

        if remote is None:
            self.toast(
                "التلفزيون غير متصل."
            )
            return

        def worker() -> None:
            try:
                remote.send(command)

            except Exception as exc:
                self.ui(
                    self.show_error,
                    exc,
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"fahd-{command.lower()}",
        ).start()

    def start_hold(self, command: str) -> None:
        remote = self.remote

        if remote is None:
            return

        def worker() -> None:
            try:
                remote.start_hold(command)

            except Exception as exc:
                self.ui(
                    self.show_error,
                    exc,
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="fahd-hold",
        ).start()

    def stop_hold(self) -> None:
        if self.remote:
            self.remote.stop_hold()

    # ========================================================
    # NUMBERS
    # ========================================================

    def open_numbers(self) -> None:
        if (
            self.controller is None
            or not self.controller.device.supports(
                "pointer"
            )
        ):
            self.toast(
                UNSUPPORTED_MESSAGE
            )
            return

        if self.manager:
            self.manager.current = "numbers"

    # ========================================================
    # KEYBOARD
    # ========================================================

    def open_keyboard(self) -> None:
        if (
            self.keyboard is None
            or self.controller is None
            or not self.controller.device.supports(
                "keyboard"
            )
        ):
            self.toast(
                KEYBOARD_UNSUPPORTED
            )
            return

        if self.root_widget is None:
            return

        if self.keyboard_field is not None:
            try:
                self.root_widget.remove_widget(
                    self.keyboard_field
                )
            except Exception:
                return

        field = TextInput(
            multiline=False,
            font_name=FONT_NAME,
            opacity=0.01,
            size_hint=(None, None),
            size=(dp(2), dp(2)),
            pos=(-100, -100),
        )

        field.bind(
            text=self._keyboard_text_changed
        )

        field.bind(
            on_text_validate=lambda _field:
            self.send_command("OK")
        )

        self.keyboard_previous = ""
        self.keyboard_field = field

        self.root_widget.add_widget(field)
        field.focus = True

        self.toast(
            "اكتب الآن باستخدام لوحة مفاتيح الهاتف."
        )

    def _keyboard_text_changed(
        self,
        _field: TextInput,
        value: str,
    ) -> None:
        previous = self.keyboard_previous
        self.keyboard_previous = value

        if len(value) > len(previous):
            added = value[len(previous):]
            self._send_keyboard_text(added)

        elif len(value) < len(previous):
            self._send_backspace()

    def _send_keyboard_text(
        self,
        value: str,
    ) -> None:
        keyboard = self.keyboard

        if keyboard is None or not value:
            return

        def worker() -> None:
            try:
                keyboard.send_text(value)

            except Exception as exc:
                self.ui(
                    self.show_error,
                    exc,
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="fahd-keyboard",
        ).start()

    def _send_backspace(self) -> None:
        keyboard = self.keyboard

        if keyboard is None:
            return

        def worker() -> None:
            try:
                keyboard.backspace()

            except Exception as exc:
                self.ui(
                    self.show_error,
                    exc,
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="fahd-backspace",
        ).start()

    # ========================================================
    # SETTINGS / DIAGNOSTICS
    # ========================================================

    def show_diagnostics(self) -> None:
        if self.manager is None:
            return

        screen = self.manager.get_screen(
            "diagnostics"
        )

        if isinstance(
            screen,
            DiagnosticsScreen,
        ):
            screen.refresh()

        self.manager.current = "diagnostics"

    def forget_current(self) -> None:
        if self.controller is None:
            self.toast(
                "لا يوجد تلفزيون متصل."
            )
            return

        identity = self.controller.device.identity

        self.disconnect()

        self.settings.forget_tv(identity)

        self.refresh_home()

        self.toast(
            "تم حذف التلفزيون."
        )

    # ========================================================
    # CLEANUP
    # ========================================================

    def on_stop(self) -> None:
        self.closing = True
        self.generation += 1

        self.discovery.stop()
        self.disconnect()


if __name__ == "__main__":
    FahdApp().run()