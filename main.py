import json
import os
import socket
import ssl
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import websocket

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle, Line, Ellipse
from kivy.metrics import dp, sp
from kivy.properties import (
    BooleanProperty,
    ColorProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager, FadeTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


APP_TITLE = "FAHD REMOTE"
APP_ID = "fahd.remote"

SSDP_ADDRESS = "239.255.255.250"
SSDP_PORT = 1900

REGISTER_PAYLOAD = {
    "forcePairing": False,
    "pairingType": "PROMPT",
    "manifest": {
        "manifestVersion": 1,
        "appVersion": "1.0",
        "signed": {
            "created": "20140509",
            "appId": "com.lge.test",
            "vendorId": "com.lge",
            "localizedAppNames": {
                "": "FAHD REMOTE"
            },
            "localizedVendorNames": {
                "": "Fahd LG Remote"
            },
            "permissions": [
                "TEST_SECURE",
                "CONTROL_INPUT_TEXT",
                "CONTROL_MOUSE_AND_KEYBOARD",
                "READ_INSTALLED_APPS",
                "READ_LGE_SDX",
                "READ_NOTIFICATIONS",
                "SEARCH",
                "WRITE_SETTINGS",
                "WRITE_NOTIFICATION_ALERT",
                "CONTROL_POWER",
                "READ_CURRENT_CHANNEL",
                "READ_RUNNING_APPS",
                "READ_UPDATE_INFO",
                "UPDATE_FROM_REMOTE_APP",
                "READ_LGE_TV_INPUT_EVENTS",
                "READ_TV_CURRENT_TIME"
            ],
            "serial": "2f930e2d2cfe083771f68e4fe7bb07"
        },
        "permissions": [
            "LAUNCH",
            "LAUNCH_WEBAPP",
            "APP_TO_APP",
            "CLOSE",
            "TEST_OPEN",
            "TEST_PROTECTED",
            "CONTROL_AUDIO",
            "CONTROL_DISPLAY",
            "CONTROL_INPUT_JOYSTICK",
            "CONTROL_INPUT_MEDIA_RECORDING",
            "CONTROL_INPUT_MEDIA_PLAYBACK",
            "CONTROL_INPUT_TV",
            "CONTROL_POWER",
            "READ_APP_STATUS",
            "READ_CURRENT_CHANNEL",
            "READ_INPUT_DEVICE_LIST",
            "READ_NETWORK_STATE",
            "READ_RUNNING_APPS",
            "READ_TV_CHANNEL_LIST",
            "WRITE_NOTIFICATION_TOAST",
            "READ_POWER_STATE",
            "READ_COUNTRY_INFO",
            "READ_SETTINGS",
            "CONTROL_TV_SCREEN",
            "CONTROL_TV_STANBY",
            "CONTROL_FAVORITE_GROUP",
            "CONTROL_USER_INFO",
            "CHECK_BLUETOOTH_DEVICE",
            "CONTROL_BLUETOOTH",
            "CONTROL_TIMER_INFO",
            "STB_INTERNAL_CONNECTION",
            "CONTROL_RECORDING",
            "READ_RECORDING_STATE",
            "WRITE_RECORDING_LIST",
            "READ_RECORDING_LIST",
            "READ_RECORDING_SCHEDULE",
            "WRITE_RECORDING_SCHEDULE",
            "READ_STORAGE_DEVICE_LIST",
            "READ_TV_PROGRAM_INFO",
            "CONTROL_BOX_CHANNEL",
            "READ_TV_ACR_AUTH_TOKEN",
            "READ_TV_CONTENT_STATE",
            "READ_TV_CURRENT_TIME",
            "ADD_LAUNCHER_CHANNEL",
            "SET_CHANNEL_SKIP",
            "RELEASE_CHANNEL_SKIP",
            "CONTROL_CHANNEL_BLOCK",
            "DELETE_SELECT_CHANNEL",
            "CONTROL_CHANNEL_GROUP",
            "SCAN_TV_CHANNELS",
            "CONTROL_TV_POWER",
            "CONTROL_WOL"
        ],
        "signatures": [
            {
                "signatureVersion": 1,
                "signature": (
                    "eyJhbGciOiJSUzI1NiIsImtpZCI6InRlc3QifQ."
                    "eyJwZXJtaXNzaW9ucyI6W119.signature"
                )
            }
        ]
    }
}


class Design:
    DARK = {
        "background": [0.027, 0.035, 0.051, 1],
        "surface": [0.055, 0.067, 0.09, 1],
        "elevated": [0.082, 0.098, 0.133, 1],
        "soft": [0.106, 0.125, 0.161, 1],
        "text": [0.925, 0.941, 0.961, 1],
        "secondary": [0.655, 0.678, 0.722, 1],
        "muted": [0.451, 0.482, 0.533, 1],
        "border": [0.145, 0.169, 0.208, 1],
        "accent": [0.557, 0.655, 0.78, 1],
        "green": [0.333, 0.788, 0.541, 1],
        "red": [0.725, 0.29, 0.333, 1],
    }

    LIGHT = {
        "background": [0.945, 0.953, 0.965, 1],
        "surface": [0.985, 0.989, 0.996, 1],
        "elevated": [1, 1, 1, 1],
        "soft": [0.91, 0.925, 0.945, 1],
        "text": [0.075, 0.09, 0.12, 1],
        "secondary": [0.28, 0.32, 0.38, 1],
        "muted": [0.46, 0.49, 0.55, 1],
        "border": [0.82, 0.84, 0.88, 1],
        "accent": [0.31, 0.46, 0.66, 1],
        "green": [0.18, 0.62, 0.38, 1],
        "red": [0.67, 0.22, 0.28, 1],
    }

    MICRO = 0.12
    FAST = 0.18
    NORMAL = 0.28
    SCREEN = 0.32
    RADIUS = dp(18)
    SMALL_RADIUS = dp(12)


class SettingsStore:
    def __init__(self, filename):
        self.filename = filename
        self.lock = threading.RLock()
        self.data = {
            "name": "",
            "theme": "dark",
            "last_tv": "",
            "last_tv_name": "",
            "client_keys": {},
        }
        self.load()

    def load(self):
        with self.lock:
            try:
                if os.path.isfile(self.filename):
                    with open(self.filename, "r", encoding="utf-8") as handle:
                        loaded = json.load(handle)
                    if isinstance(loaded, dict):
                        for key in self.data:
                            if key in loaded:
                                self.data[key] = loaded[key]
                if not isinstance(self.data.get("client_keys"), dict):
                    self.data["client_keys"] = {}
            except (OSError, ValueError, TypeError):
                pass

    def save(self):
        with self.lock:
            folder = os.path.dirname(self.filename)
            if folder:
                os.makedirs(folder, exist_ok=True)
            temp = self.filename + ".tmp"
            try:
                with open(temp, "w", encoding="utf-8") as handle:
                    json.dump(self.data, handle, indent=2)
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
                os.replace(temp, self.filename)
            except OSError:
                try:
                    if os.path.exists(temp):
                        os.remove(temp)
                except OSError:
                    pass

    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)

    def set(self, key, value):
        with self.lock:
            self.data[key] = value
        self.save()

    def client_key(self, host):
        with self.lock:
            return self.data.get("client_keys", {}).get(host)

    def set_client_key(self, host, key):
        with self.lock:
            keys = self.data.setdefault("client_keys", {})
            keys[host] = key
        self.save()


class WebOSTV:
    def __init__(self, store, state_callback=None):
        self.store = store
        self.state_callback = state_callback
        self.host = None
        self.ws = None
        self.pointer_ws = None

        self.main_lock = threading.RLock()
        self.pointer_lock = threading.RLock()
        self.lifecycle_lock = threading.RLock()

        self.connected = False
        self.stop_event = threading.Event()
        self.request_counter = 0

    def _state(self, value, message=""):
        callback = self.state_callback
        if callback:
            Clock.schedule_once(
                lambda _dt: callback(value, message), 0
            )

    def _next_id(self):
        self.request_counter += 1
        return "fahd-{}".format(self.request_counter)

    def _create_websocket(self, url, timeout=8):
        options = {
            "timeout": timeout,
            "enable_multithread": True,
        }
        if url.startswith("wss://"):
            options["sslopt"] = {
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False,
            }
        return websocket.create_connection(url, **options)

    def connect(self, host):
        with self.lifecycle_lock:
            self.disconnect(notify=False)
            self.stop_event.clear()
            self.host = host
            self._state("connecting", "Connecting to LG webOS TV")

            errors = []

            for url in (
                "wss://{}:3001/".format(host),
                "ws://{}:3000/".format(host),
            ):
                try:
                    ws = self._create_websocket(url, timeout=8)
                    self.ws = ws
                    self._register()
                    self.connected = True
                    self._connect_pointer()
                    self._state("connected", "Connected")
                    return True
                except Exception as exc:
                    errors.append(str(exc))
                    self._close_main()

            self.connected = False
            message = errors[-1] if errors else "Unable to connect"
            self._state("error", message)
            return False

    def _register(self):
        if not self.ws:
            raise RuntimeError("WebSocket is not connected")

        payload = json.loads(json.dumps(REGISTER_PAYLOAD))
        key = self.store.client_key(self.host)
        if key:
            payload["client-key"] = key

        message = {
            "id": "register_0",
            "type": "register",
            "payload": payload,
        }

        with self.main_lock:
            self.ws.settimeout(45)
            self.ws.send(json.dumps(message))

            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                raw = self.ws.recv()
                if not raw:
                    continue
                response = json.loads(raw)
                response_type = response.get("type")

                if response_type == "registered":
                    client_key = response.get("payload", {}).get(
                        "client-key"
                    )
                    if client_key:
                        self.store.set_client_key(
                            self.host, client_key
                        )
                    self.ws.settimeout(8)
                    return

                if response_type == "error":
                    raise RuntimeError(
                        response.get("error", "LG registration failed")
                    )

            raise TimeoutError("LG pairing timed out")

    def request(self, uri, payload=None, timeout=8):
        if not self.connected or not self.ws:
            raise RuntimeError("TV is not connected")

        request_id = self._next_id()
        message = {
            "id": request_id,
            "type": "request",
            "uri": uri,
            "payload": payload or {},
        }

        with self.main_lock:
            self.ws.settimeout(timeout)
            self.ws.send(json.dumps(message))
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                raw = self.ws.recv()
                if not raw:
                    continue

                response = json.loads(raw)
                if response.get("id") != request_id:
                    continue

                if response.get("type") == "error":
                    raise RuntimeError(
                        response.get("error", "LG request failed")
                    )

                return response.get("payload", {})

        raise TimeoutError("LG request timed out")

    def _connect_pointer(self):
        result = self.request(
            "ssap://com.webos.service.networkinput/"
            "getPointerInputSocket"
        )
        socket_path = result.get("socketPath")
        if not socket_path:
            raise RuntimeError("TV did not return pointer socket")

        with self.pointer_lock:
            self._close_pointer()
            self.pointer_ws = self._create_websocket(
                socket_path, timeout=6
            )

    def _pointer_send(self, message):
        if not self.connected:
            raise RuntimeError("TV is not connected")

        with self.pointer_lock:
            if not self.pointer_ws:
                self._connect_pointer()

            try:
                self.pointer_ws.send(message)
            except Exception:
                self._close_pointer()
                self._connect_pointer()
                self.pointer_ws.send(message)

    def move_pointer(self, dx, dy):
        dx = int(max(-500, min(500, dx)))
        dy = int(max(-500, min(500, dy)))
        message = (
            "type:move\n"
            "dx:{}\n"
            "dy:{}\n"
            "down:0\n\n"
        ).format(dx, dy)
        self._pointer_send(message)

    def click(self):
        self._pointer_send("type:click\n\n")

    def button(self, key):
        safe_keys = {
            "UP", "DOWN", "LEFT", "RIGHT", "ENTER",
            "BACK", "HOME", "PLAY", "MUTE",
        }
        if key not in safe_keys:
            raise ValueError("Unsupported pointer button")
        self._pointer_send(
            "type:button\nname:{}\n\n".format(key)
        )

    def volume_up(self):
        return self.request("ssap://audio/volumeUp")

    def volume_down(self):
        return self.request("ssap://audio/volumeDown")

    def get_audio_status(self):
        return self.request("ssap://audio/getStatus")

    def set_mute(self, muted):
        return self.request(
            "ssap://audio/setMute",
            {"mute": bool(muted)}
        )

    def toggle_mute(self):
        status = self.get_audio_status()
        muted = bool(status.get("mute", False))
        return self.set_mute(not muted)

    def power_off(self):
        return self.request("ssap://system/turnOff")

    def _close_pointer(self):
        ws = self.pointer_ws
        self.pointer_ws = None
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    def _close_main(self):
        ws = self.ws
        self.ws = None
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    def disconnect(self, notify=True):
        self.stop_event.set()
        self.connected = False

        with self.pointer_lock:
            self._close_pointer()

        with self.main_lock:
            self._close_main()

        if notify:
            self._state("disconnected", "Disconnected")


class SSDPDiscovery:
    SEARCH_TARGETS = (
        "urn:lge-com:service:webos-second-screen:1",
        "urn:schemas-upnp-org:device:MediaRenderer:1",
    )

    def __init__(self):
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    @staticmethod
    def _parse_headers(data):
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            return {}

        headers = {}
        lines = text.replace("\r\n", "\n").split("\n")
        for line in lines[1:]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        return headers

    @staticmethod
    def _host_from_location(location, fallback):
        try:
            parsed = urlparse(location)
            if parsed.hostname:
                return parsed.hostname
        except Exception:
            pass
        return fallback

    @staticmethod
    def _friendly_name(location, host):
        if not location:
            return "LG webOS TV"
        try:
            request = Request(
                location,
                headers={"User-Agent": "FAHD-REMOTE/1.0"}
            )
            with urlopen(request, timeout=1.5) as response:
                body = response.read(65536).decode(
                    "utf-8", errors="ignore"
                )

            lower = body.lower()
            start_tag = "<friendlyname>"
            end_tag = "</friendlyname>"
            start = lower.find(start_tag)
            end = lower.find(end_tag)

            if start != -1 and end > start:
                start += len(start_tag)
                value = body[start:end].strip()
                if value:
                    return value
        except Exception:
            pass
        return "LG webOS TV ({})".format(host)

    def discover(self, result_callback, done_callback, timeout=4.0):
        self.stop_event.clear()
        seen = set()

        try:
            sock = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(0.25)

            for target in self.SEARCH_TARGETS:
                message = (
                    "M-SEARCH * HTTP/1.1\r\n"
                    "HOST:239.255.255.250:1900\r\n"
                    'MAN:"ssdp:discover"\r\n'
                    "MX:2\r\n"
                    "ST:{}\r\n"
                    "\r\n"
                ).format(target)

                try:
                    sock.sendto(
                        message.encode("ascii"),
                        (SSDP_ADDRESS, SSDP_PORT),
                    )
                except OSError:
                    continue

            deadline = time.monotonic() + timeout

            while (
                time.monotonic() < deadline
                and not self.stop_event.is_set()
            ):
                try:
                    data, address = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break

                headers = self._parse_headers(data)
                server = headers.get("server", "").lower()
                location = headers.get("location", "")
                text = data.decode("utf-8", errors="ignore").lower()

                looks_like_lg = (
                    "webos" in server
                    or "lge" in server
                    or "webos" in text
                    or "lge" in text
                )
                if not looks_like_lg:
                    continue

                host = self._host_from_location(
                    location, address[0]
                )
                if host in seen:
                    continue

                seen.add(host)
                friendly_name = self._friendly_name(
                    location, host
                )

                Clock.schedule_once(
                    lambda _dt, h=host, n=friendly_name:
                    result_callback(h, n),
                    0,
                )

        finally:
            try:
                sock.close()
            except Exception:
                pass
            Clock.schedule_once(lambda _dt: done_callback(), 0)


class ThemeManager:
    def __init__(self, store):
        self.store = store
        self.mode = store.get("theme", "dark")
        if self.mode not in ("dark", "light"):
            self.mode = "dark"
        self.listeners = []

    @property
    def palette(self):
        return (
            Design.LIGHT
            if self.mode == "light"
            else Design.DARK
        )

    def bind(self, widget):
        if widget not in self.listeners:
            self.listeners.append(widget)

    def unbind(self, widget):
        if widget in self.listeners:
            self.listeners.remove(widget)

    def toggle(self):
        self.mode = "light" if self.mode == "dark" else "dark"
        self.store.set("theme", self.mode)
        self.refresh(animated=True)

    def refresh(self, animated=False):
        for widget in self.listeners[:]:
            try:
                widget.apply_theme(
                    self.palette,
                    animated=animated
                )
            except Exception:
                try:
                    self.listeners.remove(widget)
                except ValueError:
                    pass


class ThemedWidget:
    def register_theme(self):
        app = App.get_running_app()
        if app and getattr(app, "theme", None):
            app.theme.bind(self)
            self.apply_theme(app.theme.palette, animated=False)

    def apply_theme(self, palette, animated=False):
        pass


class Surface(BoxLayout, ThemedWidget):
    bg_color = ColorProperty([0.055, 0.067, 0.09, 1])
    border_color = ColorProperty([0.145, 0.169, 0.208, 1])
    radius = NumericProperty(dp(18))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            self._bg_instruction = Color(rgba=self.bg_color)
            self._bg_rect = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self.radius],
            )
            self._border_instruction = Color(
                rgba=self.border_color
            )
            self._border_line = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    self.radius,
                ),
                width=1,
            )

        self.bind(
            pos=self._update_canvas,
            size=self._update_canvas,
            radius=self._update_canvas,
            bg_color=self._update_colors,
            border_color=self._update_colors,
        )
        Clock.schedule_once(
            lambda _dt: self.register_theme(), 0
        )

    def _update_canvas(self, *_args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._bg_rect.radius = [self.radius]
        self._border_line.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            self.radius,
        )

    def _update_colors(self, *_args):
        self._bg_instruction.rgba = self.bg_color
        self._border_instruction.rgba = self.border_color

    def apply_theme(self, palette, animated=False):
        if animated:
            Animation.cancel_all(self, "bg_color", "border_color")
            animation = Animation(
                bg_color=palette["surface"],
                border_color=palette["border"],
                duration=Design.NORMAL,
                t="out_quad",
            )
            animation.start(self)
        else:
            self.bg_color = palette["surface"]
            self.border_color = palette["border"]


class AppLabel(Label, ThemedWidget):
    role = StringProperty("text")

    def __init__(self, **kwargs):
        kwargs.setdefault("font_size", sp(15))
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        self.bind(size=self._sync_text)
        Clock.schedule_once(
            lambda _dt: self.register_theme(), 0
        )

    def _sync_text(self, *_args):
        self.text_size = self.size

    def apply_theme(self, palette, animated=False):
        target = palette.get(self.role, palette["text"])
        if animated:
            Animation.cancel_all(self, "color")
            Animation(
                color=target,
                duration=Design.NORMAL,
                t="out_quad",
            ).start(self)
        else:
            self.color = target


class PremiumButton(Button, ThemedWidget):
    accent = BooleanProperty(False)
    danger = BooleanProperty(False)
    selected = BooleanProperty(False)
    bg_color = ColorProperty([0.106, 0.125, 0.161, 1])
    border_color = ColorProperty([0.145, 0.169, 0.208, 1])
    text_color = ColorProperty([0.925, 0.941, 0.961, 1])

    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("font_size", sp(13))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(52))
        super().__init__(**kwargs)

        self.background_color = [0, 0, 0, 0]
        self.color = self.text_color

        with self.canvas.before:
            self._button_bg_color = Color(rgba=self.bg_color)
            self._button_bg = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[Design.SMALL_RADIUS],
            )
            self._button_border_color = Color(
                rgba=self.border_color
            )
            self._button_border = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    Design.SMALL_RADIUS,
                ),
                width=1,
            )

        self.bind(
            pos=self._canvas_update,
            size=self._canvas_update,
            bg_color=self._color_update,
            border_color=self._color_update,
            text_color=self._color_update,
        )

        Clock.schedule_once(
            lambda _dt: self.register_theme(), 0
        )

    def _canvas_update(self, *_args):
        self._button_bg.pos = self.pos
        self._button_bg.size = self.size
        self._button_border.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            Design.SMALL_RADIUS,
        )

    def _color_update(self, *_args):
        self._button_bg_color.rgba = self.bg_color
        self._button_border_color.rgba = self.border_color
        self.color = self.text_color

    def apply_theme(self, palette, animated=False):
        if self.danger:
            bg = [
                palette["red"][0] * 0.42,
                palette["red"][1] * 0.42,
                palette["red"][2] * 0.42,
                1,
            ]
            border = palette["red"]
        elif self.accent or self.selected:
            bg = [
                palette["accent"][0] * 0.34,
                palette["accent"][1] * 0.34,
                palette["accent"][2] * 0.34,
                1,
            ]
            border = palette["accent"]
        else:
            bg = palette["soft"]
            border = palette["border"]

        if animated:
            Animation.cancel_all(
                self,
                "bg_color",
                "border_color",
                "text_color",
            )
            animation = Animation(
                bg_color=bg,
                border_color=border,
                text_color=palette["text"],
                duration=Design.NORMAL,
                t="out_quad",
            )
            animation.start(self)
        else:
            self.bg_color = bg
            self.border_color = border
            self.text_color = palette["text"]

    def on_touch_down(self, touch):
        handled = super().on_touch_down(touch)
        if handled and self.collide_point(*touch.pos):
            app = App.get_running_app()
            if app and app.theme:
                palette = app.theme.palette
                target = palette["elevated"]
                if self.danger:
                    target = palette["red"]
                elif self.accent:
                    target = [
                        palette["accent"][0] * 0.55,
                        palette["accent"][1] * 0.55,
                        palette["accent"][2] * 0.55,
                        1,
                    ]
                Animation.cancel_all(self, "bg_color")
                Animation(
                    bg_color=target,
                    duration=Design.MICRO,
                    t="out_quad",
                ).start(self)
        return handled

    def on_touch_up(self, touch):
        handled = super().on_touch_up(touch)
        app = App.get_running_app()
        if app and app.theme:
            self.apply_theme(app.theme.palette, animated=True)
        return handled


class PremiumInput(TextInput, ThemedWidget):
    field_bg = ColorProperty([0.055, 0.067, 0.09, 1])
    field_border = ColorProperty([0.145, 0.169, 0.208, 1])

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("font_size", sp(16))
        kwargs.setdefault("padding", [dp(16), dp(14), dp(16), dp(12)])
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(54))
        super().__init__(**kwargs)

        self.background_normal = ""
        self.background_active = ""
        self.background_color = [0, 0, 0, 0]

        with self.canvas.before:
            self._field_color = Color(rgba=self.field_bg)
            self._field_rect = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[Design.SMALL_RADIUS],
            )
            self._field_border_color = Color(
                rgba=self.field_border
            )
            self._field_border_line = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    Design.SMALL_RADIUS,
                ),
                width=1,
            )

        self.bind(
            pos=self._update_field,
            size=self._update_field,
            field_bg=self._update_field_colors,
            field_border=self._update_field_colors,
            focus=self._focus_changed,
        )
        Clock.schedule_once(
            lambda _dt: self.register_theme(), 0
        )

    def _update_field(self, *_args):
        self._field_rect.pos = self.pos
        self._field_rect.size = self.size
        self._field_border_line.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            Design.SMALL_RADIUS,
        )

    def _update_field_colors(self, *_args):
        self._field_color.rgba = self.field_bg
        self._field_border_color.rgba = self.field_border

    def _focus_changed(self, *_args):
        app = App.get_running_app()
        if not app or not app.theme:
            return
        palette = app.theme.palette
        target = (
            palette["accent"]
            if self.focus
            else palette["border"]
        )
        Animation.cancel_all(self, "field_border")
        Animation(
            field_border=target,
            duration=Design.FAST,
            t="out_quad",
        ).start(self)

    def apply_theme(self, palette, animated=False):
        self.foreground_color = palette["text"]
        self.hint_text_color = palette["muted"]
        self.cursor_color = palette["accent"]
        target_border = (
            palette["accent"]
            if self.focus
            else palette["border"]
        )

        if animated:
            Animation.cancel_all(
                self, "field_bg", "field_border"
            )
            Animation(
                field_bg=palette["surface"],
                field_border=target_border,
                duration=Design.NORMAL,
                t="out_quad",
            ).start(self)
        else:
            self.field_bg = palette["surface"]
            self.field_border = target_border


class ConnectionIndicator(Widget, ThemedWidget):
    state = StringProperty("disconnected")
    dot_color = ColorProperty([0.45, 0.48, 0.53, 1])
    pulse_alpha = NumericProperty(0)

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(18), dp(18)))
        super().__init__(**kwargs)

        with self.canvas:
            self._pulse_color = Color(1, 1, 1, 0)
            self._pulse = Ellipse()
            self._dot_canvas_color = Color(rgba=self.dot_color)
            self._dot = Ellipse()

        self.bind(
            pos=self._draw,
            size=self._draw,
            dot_color=self._draw,
            pulse_alpha=self._draw,
            state=self._state_changed,
        )

        Clock.schedule_once(
            lambda _dt: self.register_theme(), 0
        )

    def _draw(self, *_args):
        outer = min(self.width, self.height)
        inner = dp(8)

        self._pulse.pos = (
            self.center_x - outer / 2,
            self.center_y - outer / 2,
        )
        self._pulse.size = (outer, outer)

        self._dot.pos = (
            self.center_x - inner / 2,
            self.center_y - inner / 2,
        )
        self._dot.size = (inner, inner)

        self._dot_canvas_color.rgba = self.dot_color
        self._pulse_color.rgba = [
            self.dot_color[0],
            self.dot_color[1],
            self.dot_color[2],
            self.pulse_alpha,
        ]

    def _state_changed(self, *_args):
        Animation.cancel_all(self)
        app = App.get_running_app()
        if app and app.theme:
            self.apply_theme(app.theme.palette, animated=True)

    def apply_theme(self, palette, animated=False):
        state_colors = {
            "disconnected": palette["muted"],
            "searching": palette["accent"],
            "connecting": palette["accent"],
            "connected": palette["green"],
            "error": palette["red"],
        }
        target = state_colors.get(
            self.state, palette["muted"]
        )

        if animated:
            Animation(
                dot_color=target,
                duration=Design.FAST,
                t="out_quad",
            ).start(self)
        else:
            self.dot_color = target

        if self.state in ("searching", "connecting"):
            sequence = (
                Animation(
                    pulse_alpha=0.22,
                    duration=0.55,
                    t="in_out_quad",
                )
                + Animation(
                    pulse_alpha=0.02,
                    duration=0.55,
                    t="in_out_quad",
                )
            )
            sequence.repeat = True
            sequence.start(self)
        elif self.state == "connected":
            sequence = (
                Animation(
                    pulse_alpha=0.18,
                    duration=0.22,
                    t="out_quad",
                )
                + Animation(
                    pulse_alpha=0.05,
                    duration=0.3,
                    t="out_quad",
                )
            )
            sequence.start(self)
        else:
            self.pulse_alpha = 0


class LoadingIndicator(Widget, ThemedWidget):
    active = BooleanProperty(False)
    angle = NumericProperty(0)
    indicator_color = ColorProperty([0.557, 0.655, 0.78, 1])

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(28), dp(28)))
        super().__init__(**kwargs)

        with self.canvas:
            self._loading_color = Color(
                rgba=self.indicator_color
            )
            self._loading_line = Line(width=dp(2))

        self.bind(
            pos=self._redraw,
            size=self._redraw,
            angle=self._redraw,
            indicator_color=self._redraw,
            active=self._active_changed,
        )

        Clock.schedule_once(
            lambda _dt: self.register_theme(), 0
        )

    def _redraw(self, *_args):
        self._loading_color.rgba = self.indicator_color
        radius = max(1, min(self.width, self.height) / 2 - dp(3))
        self._loading_line.circle = (
            self.center_x,
            self.center_y,
            radius,
            self.angle,
            self.angle + 260,
        )

    def _active_changed(self, *_args):
        Animation.cancel_all(self, "angle")
        if self.active:
            self.angle = 0
            animation = Animation(
                angle=360,
                duration=0.85,
                t="linear",
            )
            animation.repeat = True
            animation.start(self)
        else:
            self.angle = 0

    def apply_theme(self, palette, animated=False):
        self.indicator_color = palette["accent"]


class Toast(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.label = None
        self._dismiss_event = None

    def show(self, text, error=False):
        if self._dismiss_event:
            self._dismiss_event.cancel()
            self._dismiss_event = None

        if self.label:
            self.remove_widget(self.label)

        app = App.get_running_app()
        palette = app.theme.palette

        label = Label(
            text=text,
            color=palette["text"],
            font_size=sp(13),
            size_hint=(0.88, None),
            height=dp(46),
            pos_hint={"center_x": 0.5},
            y=dp(20),
            opacity=0,
        )

        with label.canvas.before:
            color_instruction = Color(
                rgba=(
                    palette["red"]
                    if error
                    else palette["elevated"]
                )
            )
            rect = RoundedRectangle(
                pos=label.pos,
                size=label.size,
                radius=[dp(13)],
            )

        def update(*_args):
            color_instruction.rgba = (
                palette["red"]
                if error
                else palette["elevated"]
            )
            rect.pos = label.pos
            rect.size = label.size

        label.bind(pos=update, size=update)
        self.label = label
        self.add_widget(label)

        animation = (
            Animation(
                opacity=1,
                duration=Design.FAST,
                t="out_quad",
            )
            + Animation(duration=1.8)
            + Animation(
                opacity=0,
                duration=Design.FAST,
                t="out_quad",
            )
        )
        animation.bind(
            on_complete=lambda *_args: self._remove_label(label)
        )
        animation.start(label)

    def _remove_label(self, label):
        if self.label is label:
            try:
                self.remove_widget(label)
            except Exception:
                pass
            self.label = None

    def on_touch_down(self, touch):
        return False

    def on_touch_move(self, touch):
        return False

    def on_touch_up(self, touch):
        return False


class AppScreen(Screen, ThemedWidget):
    bg_color = ColorProperty([0.027, 0.035, 0.051, 1])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        with self.canvas.before:
            self._screen_color = Color(rgba=self.bg_color)
            self._screen_rect = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[0],
            )

        self.bind(
            pos=self._screen_canvas,
            size=self._screen_canvas,
            bg_color=self._screen_canvas,
        )

        Clock.schedule_once(
            lambda _dt: self.register_theme(), 0
        )

    def _screen_canvas(self, *_args):
        self._screen_color.rgba = self.bg_color
        self._screen_rect.pos = self.pos
        self._screen_rect.size = self.size

    def apply_theme(self, palette, animated=False):
        if animated:
            Animation.cancel_all(self, "bg_color")
            Animation(
                bg_color=palette["background"],
                duration=Design.NORMAL,
                t="out_quad",
            ).start(self)
        else:
            self.bg_color = palette["background"]


class SplashScreen(AppScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = AnchorLayout()
        content = BoxLayout(
            orientation="vertical",
            size_hint=(0.86, None),
            height=dp(160),
            spacing=dp(10),
        )

        self.logo = AppLabel(
            text="FAHD REMOTE",
            font_size=sp(30),
            bold=True,
            halign="center",
            opacity=0,
        )
        self.subtitle = AppLabel(
            text="Preparing your remote...",
            role="secondary",
            font_size=sp(14),
            halign="center",
            opacity=0,
        )

        content.add_widget(self.logo)
        content.add_widget(self.subtitle)
        root.add_widget(content)
        self.add_widget(root)

    def on_enter(self, *_args):
        self.logo.opacity = 0
        self.subtitle.opacity = 0

        first = Animation(
            opacity=1,
            duration=0.3,
            t="out_cubic",
        )
        second = Animation(
            opacity=1,
            duration=0.25,
            t="out_quad",
        )

        first.start(self.logo)
        Clock.schedule_once(
            lambda _dt: second.start(self.subtitle),
            0.18,
        )
        Clock.schedule_once(self._finish, 0.9)

    def _finish(self, _dt):
        app = App.get_running_app()
        if app.store.get("name", "").strip():
            app.go("home")
        else:
            app.go("welcome")


class WelcomeScreen(AppScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        outer = AnchorLayout(
            anchor_x="center",
            anchor_y="center",
            padding=dp(24),
        )

        card = Surface(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(350),
            padding=dp(24),
            spacing=dp(14),
        )

        card.add_widget(
            AppLabel(
                text="FAHD REMOTE",
                font_size=sp(13),
                bold=True,
                role="accent",
                size_hint_y=None,
                height=dp(28),
            )
        )
        card.add_widget(
            AppLabel(
                text="Welcome",
                font_size=sp(30),
                bold=True,
                size_hint_y=None,
                height=dp(56),
            )
        )
        card.add_widget(
            AppLabel(
                text="A calm, fast remote for your LG webOS TV.",
                role="secondary",
                font_size=sp(15),
                size_hint_y=None,
                height=dp(48),
            )
        )

        self.name_input = PremiumInput(
            hint_text="Your name",
            size_hint_y=None,
            height=dp(54),
        )
        self.name_input.bind(
            on_text_validate=lambda *_args: self.continue_app()
        )
        card.add_widget(self.name_input)

        button = PremiumButton(
            text="CONTINUE",
            accent=True,
        )
        button.bind(
            on_release=lambda *_args: self.continue_app()
        )
        card.add_widget(button)

        outer.add_widget(card)
        self.add_widget(outer)

    def on_pre_enter(self, *_args):
        app = App.get_running_app()
        self.name_input.text = app.store.get("name", "")

    def continue_app(self):
        value = self.name_input.text.strip()
        if not value:
            App.get_running_app().toast(
                "Please enter your name.",
                error=True,
            )
            self.name_input.focus = True
            return

        app = App.get_running_app()
        app.store.set("name", value)
        self.name_input.focus = False
        app.go("home")


class NavigationBar(Surface):
    def __init__(self, active="home", **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(66))
        kwargs.setdefault("padding", dp(7))
        kwargs.setdefault("spacing", dp(7))
        super().__init__(**kwargs)

        for text, screen in (
            ("HOME", "home"),
            ("REMOTE", "remote"),
            ("SETTINGS", "settings"),
        ):
            button = PremiumButton(
                text=text,
                size_hint_y=1,
                height=dp(52),
                selected=(screen == active),
            )
            button.bind(
                on_release=lambda _btn, target=screen:
                App.get_running_app().go(target)
            )
            self.add_widget(button)


class HomeScreen(AppScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=[dp(18), dp(20), dp(18), dp(14)],
            spacing=dp(14),
        )

        header = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(92),
        )
        header.add_widget(
            AppLabel(
                text="FAHD / LG",
                role="accent",
                font_size=sp(12),
                bold=True,
            )
        )
        self.hello = AppLabel(
            text="Hello",
            font_size=sp(27),
            bold=True,
        )
        header.add_widget(self.hello)
        root.add_widget(header)

        connection = Surface(
            orientation="vertical",
            size_hint_y=None,
            height=dp(190),
            padding=dp(18),
            spacing=dp(9),
        )

        connection.add_widget(
            AppLabel(
                text="LG webOS TV",
                font_size=sp(18),
                bold=True,
                size_hint_y=None,
                height=dp(34),
            )
        )

        status_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(32),
            spacing=dp(7),
        )
        self.indicator = ConnectionIndicator()
        status_row.add_widget(self.indicator)

        self.status_label = AppLabel(
            text="Disconnected",
            role="secondary",
            font_size=sp(14),
        )
        status_row.add_widget(self.status_label)
        connection.add_widget(status_row)

        self.tv_label = AppLabel(
            text="No TV selected",
            role="muted",
            font_size=sp(12),
            size_hint_y=None,
            height=dp(28),
        )
        connection.add_widget(self.tv_label)

        self.search_button = PremiumButton(
            text="SEARCH FOR TV",
            accent=True,
        )
        self.search_button.bind(
            on_release=lambda *_args:
            App.get_running_app().go("discovery")
        )
        connection.add_widget(self.search_button)

        root.add_widget(connection)

        quick_title = AppLabel(
            text="Quick Access",
            font_size=sp(15),
            bold=True,
            size_hint_y=None,
            height=dp(34),
        )
        root.add_widget(quick_title)

        quick = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(72),
            spacing=dp(10),
        )

        remote = PremiumButton(text="REMOTE")
        remote.bind(
            on_release=lambda *_args:
            App.get_running_app().go("remote")
        )
        settings = PremiumButton(text="SETTINGS")
        settings.bind(
            on_release=lambda *_args:
            App.get_running_app().go("settings")
        )

        quick.add_widget(remote)
        quick.add_widget(settings)
        root.add_widget(quick)

        root.add_widget(Widget())
        root.add_widget(NavigationBar(active="home"))
        self.add_widget(root)

    def on_pre_enter(self, *_args):
        app = App.get_running_app()
        person = app.store.get("name", "").strip()
        self.hello.text = (
            "Hello, {}".format(person)
            if person
            else "Hello"
        )

        tv_name = app.store.get("last_tv_name", "")
        host = app.store.get("last_tv", "")
        if tv_name or host:
            self.tv_label.text = tv_name or host
        else:
            self.tv_label.text = "No TV selected"

        self.update_connection(
            app.connection_state,
            app.connection_message,
        )

    def update_connection(self, state, message=""):
        self.indicator.state = state

        labels = {
            "disconnected": "Disconnected",
            "searching": "Searching",
            "connecting": "Connecting",
            "connected": "Connected",
            "error": "Connection error",
        }
        self.status_label.text = labels.get(
            state, "Disconnected"
        )

        self.search_button.text = (
            "CHANGE TV"
            if state == "connected"
            else "SEARCH FOR TV"
        )


class DiscoveryScreen(AppScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result_hosts = set()

        root = BoxLayout(
            orientation="vertical",
            padding=[dp(18), dp(20), dp(18), dp(16)],
            spacing=dp(12),
        )

        top = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(54),
            spacing=dp(8),
        )

        back = PremiumButton(
            text="BACK",
            size_hint_x=None,
            width=dp(82),
        )
        back.bind(
            on_release=lambda *_args:
            App.get_running_app().go("home")
        )

        title = AppLabel(
            text="Find your TV",
            font_size=sp(23),
            bold=True,
        )

        top.add_widget(back)
        top.add_widget(title)
        root.add_widget(top)

        self.info = AppLabel(
            text="Search your Wi-Fi network for LG webOS TVs.",
            role="secondary",
            size_hint_y=None,
            height=dp(45),
        )
        root.add_widget(self.info)

        action_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(54),
            spacing=dp(10),
        )

        self.search = PremiumButton(
            text="SEARCH FOR TV",
            accent=True,
        )
        self.search.bind(
            on_release=lambda *_args: self.start_search()
        )

        self.loader = LoadingIndicator()
        holder = AnchorLayout(
            size_hint_x=None,
            width=dp(45),
        )
        holder.add_widget(self.loader)

        action_row.add_widget(self.search)
        action_row.add_widget(holder)
        root.add_widget(action_row)

        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(3),
        )

        self.results = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(10),
            padding=[0, dp(4)],
        )
        self.results.bind(
            minimum_height=self.results.setter("height")
        )

        scroll.add_widget(self.results)
        root.add_widget(scroll)

        self.add_widget(root)

    def on_enter(self, *_args):
        if not self.results.children:
            self.start_search()

    def start_search(self):
        app = App.get_running_app()
        if app.discovery_running:
            return

        self.result_hosts.clear()
        self.results.clear_widgets()
        self.loader.active = True
        self.search.disabled = True
        self.search.text = "SEARCHING..."
        self.info.text = "Searching for LG webOS TVs..."
        app.start_discovery(
            self.add_result,
            self.discovery_finished,
        )

    def add_result(self, host, friendly_name):
        if host in self.result_hosts:
            return

        self.result_hosts.add(host)

        card = Surface(
            orientation="vertical",
            size_hint_y=None,
            height=dp(118),
            padding=dp(14),
            spacing=dp(6),
            opacity=0,
        )

        card.add_widget(
            AppLabel(
                text=friendly_name,
                font_size=sp(16),
                bold=True,
                size_hint_y=None,
                height=dp(30),
            )
        )
        card.add_widget(
            AppLabel(
                text=host,
                role="secondary",
                font_size=sp(12),
                size_hint_y=None,
                height=dp(24),
            )
        )

        connect = PremiumButton(
            text="CONNECT",
            accent=True,
            size_hint_y=None,
            height=dp(42),
        )
        connect.bind(
            on_release=lambda _btn, h=host, n=friendly_name:
            self.connect_tv(h, n)
        )

        card.add_widget(connect)
        self.results.add_widget(card)

        Animation(
            opacity=1,
            duration=Design.NORMAL,
            t="out_cubic",
        ).start(card)

    def discovery_finished(self):
        self.loader.active = False
        self.search.disabled = False
        self.search.text = "SEARCH AGAIN"

        if not self.result_hosts:
            self.info.text = (
                "No LG webOS TV found. Make sure the phone "
                "and TV use the same Wi-Fi network."
            )
        else:
            self.info.text = "Select your LG webOS TV."

    def connect_tv(self, host, friendly_name):
        app = App.get_running_app()
        app.store.set("last_tv", host)
        app.store.set("last_tv_name", friendly_name)
        app.connect_tv(host)


class TouchPad(Surface):
    touched = BooleanProperty(False)

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(190))
        super().__init__(**kwargs)

        self.last_pos = None
        self.total_movement = 0.0
        self.touch_uid = None

        self.hint = AppLabel(
            text="TOUCHPAD",
            role="muted",
            halign="center",
            font_size=sp(12),
        )
        self.add_widget(self.hint)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        if self.touch_uid is not None:
            return True

        self.touch_uid = touch.uid
        touch.grab(self)
        self.last_pos = touch.pos
        self.total_movement = 0.0
        self.touched = True

        app = App.get_running_app()
        if app:
            palette = app.theme.palette
            Animation.cancel_all(self, "border_color")
            Animation(
                border_color=palette["accent"],
                duration=Design.MICRO,
                t="out_quad",
            ).start(self)

        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_move(touch)

        if touch.uid != self.touch_uid or not self.last_pos:
            return True

        dx = touch.x - self.last_pos[0]
        dy = touch.y - self.last_pos[1]
        self.last_pos = touch.pos

        self.total_movement += abs(dx) + abs(dy)

        if abs(dx) >= 0.5 or abs(dy) >= 0.5:
            app = App.get_running_app()
            app.pointer_move(dx * 2.2, -dy * 2.2)

        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)

        if touch.uid == self.touch_uid:
            touch.ungrab(self)

            if self.total_movement < dp(12):
                App.get_running_app().pointer_click()

            self.touch_uid = None
            self.last_pos = None
            self.total_movement = 0.0
            self.touched = False

            app = App.get_running_app()
            self.apply_theme(
                app.theme.palette,
                animated=True,
            )

        return True


class RepeatButton(PremiumButton):
    remote_key = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._hold_event = None
        self._repeat_event = None
        self._active_touch = None

    def on_touch_down(self, touch):
        if (
            self.disabled
            or not self.collide_point(*touch.pos)
            or self._active_touch is not None
        ):
            return super().on_touch_down(touch)

        self._active_touch = touch.uid
        App.get_running_app().remote_button(self.remote_key)

        self._cancel_repeat()
        self._hold_event = Clock.schedule_once(
            self._start_repeat,
            0.38,
        )

        return super().on_touch_down(touch)

    def _start_repeat(self, _dt):
        self._hold_event = None
        if self._active_touch is None:
            return

        self._repeat_event = Clock.schedule_interval(
            self._repeat,
            0.12,
        )

    def _repeat(self, _dt):
        if self._active_touch is None:
            self._cancel_repeat()
            return False

        App.get_running_app().remote_button(
            self.remote_key
        )
        return True

    def on_touch_up(self, touch):
        if touch.uid == self._active_touch:
            self._active_touch = None
            self._cancel_repeat()
        return super().on_touch_up(touch)

    def _cancel_repeat(self):
        if self._hold_event:
            self._hold_event.cancel()
            self._hold_event = None

        if self._repeat_event:
            self._repeat_event.cancel()
            self._repeat_event = None

    def on_parent(self, _instance, parent):
        if parent is None:
            self._active_touch = None
            self._cancel_repeat()
class RemoteScreen(AppScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=[dp(16), dp(18), dp(16), dp(12)],
            spacing=dp(10),
        )

        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(54),
            spacing=dp(10),
        )

        title = AppLabel(
            text="Remote",
            font_size=sp(25),
            bold=True,
        )

        self.status = AppLabel(
            text="Disconnected",
            role="secondary",
            font_size=sp(12),
            halign="right",
            size_hint_x=0.55,
        )

        self.connection_dot = ConnectionIndicator()

        dot_holder = AnchorLayout(
            size_hint_x=None,
            width=dp(24),
        )
        dot_holder.add_widget(self.connection_dot)

        header.add_widget(title)
        header.add_widget(self.status)
        header.add_widget(dot_holder)

        root.add_widget(header)

        power_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            spacing=dp(10),
        )

        self.power_button = PremiumButton(
            text="POWER",
            danger=True,
            size_hint_x=0.34,
        )
        self.power_button.bind(
            on_release=lambda *_args:
            App.get_running_app().power_off()
        )

        self.tv_name = AppLabel(
            text="LG webOS TV",
            role="secondary",
            halign="right",
        )

        power_row.add_widget(self.power_button)
        power_row.add_widget(self.tv_name)

        root.add_widget(power_row)

        self.touchpad = TouchPad()
        root.add_widget(self.touchpad)

        dpad_holder = AnchorLayout(
            size_hint_y=None,
            height=dp(218),
        )

        dpad = FloatLayout(
            size_hint=(None, None),
            size=(dp(218), dp(205)),
        )

        button_size = dp(64)

        self.btn_up = RepeatButton(
            text="UP",
            remote_key="UP",
            size_hint=(None, None),
            size=(button_size, button_size),
            pos_hint={"center_x": 0.5, "top": 1},
        )

        self.btn_down = RepeatButton(
            text="DOWN",
            remote_key="DOWN",
            size_hint=(None, None),
            size=(button_size, button_size),
            pos_hint={"center_x": 0.5, "y": 0},
        )

        self.btn_left = RepeatButton(
            text="LEFT",
            remote_key="LEFT",
            size_hint=(None, None),
            size=(button_size, button_size),
            pos_hint={"x": 0, "center_y": 0.5},
        )

        self.btn_right = RepeatButton(
            text="RIGHT",
            remote_key="RIGHT",
            size_hint=(None, None),
            size=(button_size, button_size),
            pos_hint={"right": 1, "center_y": 0.5},
        )

        self.btn_ok = PremiumButton(
            text="OK",
            accent=True,
            size_hint=(None, None),
            size=(dp(72), dp(72)),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )
        self.btn_ok.bind(
            on_release=lambda *_args:
            App.get_running_app().remote_button("ENTER")
        )

        dpad.add_widget(self.btn_up)
        dpad.add_widget(self.btn_down)
        dpad.add_widget(self.btn_left)
        dpad.add_widget(self.btn_right)
        dpad.add_widget(self.btn_ok)

        dpad_holder.add_widget(dpad)
        root.add_widget(dpad_holder)

        media_grid = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(116),
            spacing=dp(8),
        )

        first_row = BoxLayout(
            orientation="horizontal",
            spacing=dp(8),
        )

        volume_down = PremiumButton(text="VOL -")
        volume_up = PremiumButton(text="VOL +")
        mute = PremiumButton(text="MUTE")

        volume_down.bind(
            on_release=lambda *_args:
            App.get_running_app().volume_down()
        )
        volume_up.bind(
            on_release=lambda *_args:
            App.get_running_app().volume_up()
        )
        mute.bind(
            on_release=lambda *_args:
            App.get_running_app().toggle_mute()
        )

        first_row.add_widget(volume_down)
        first_row.add_widget(volume_up)
        first_row.add_widget(mute)

        second_row = BoxLayout(
            orientation="horizontal",
            spacing=dp(8),
        )

        back = PremiumButton(text="BACK")
        home = PremiumButton(text="HOME")
        play = PremiumButton(text="PLAY")

        back.bind(
            on_release=lambda *_args:
            App.get_running_app().remote_button("BACK")
        )
        home.bind(
            on_release=lambda *_args:
            App.get_running_app().remote_button("HOME")
        )
        play.bind(
            on_release=lambda *_args:
            App.get_running_app().remote_button("PLAY")
        )

        second_row.add_widget(back)
        second_row.add_widget(home)
        second_row.add_widget(play)

        media_grid.add_widget(first_row)
        media_grid.add_widget(second_row)

        root.add_widget(media_grid)
        root.add_widget(NavigationBar(active="remote"))

        self.add_widget(root)

    def on_pre_enter(self, *_args):
        app = App.get_running_app()

        self.tv_name.text = (
            app.store.get("last_tv_name", "")
            or app.store.get("last_tv", "")
            or "LG webOS TV"
        )

        self.update_connection(
            app.connection_state,
            app.connection_message,
        )

    def update_connection(self, state, message=""):
        self.connection_dot.state = state

        state_text = {
            "disconnected": "Disconnected",
            "searching": "Searching",
            "connecting": "Connecting",
            "connected": "Connected",
            "error": "Connection error",
        }

        self.status.text = state_text.get(
            state,
            "Disconnected",
        )


class SettingsScreen(AppScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=[dp(18), dp(20), dp(18), dp(14)],
            spacing=dp(12),
        )

        root.add_widget(
            AppLabel(
                text="Settings",
                font_size=sp(26),
                bold=True,
                size_hint_y=None,
                height=dp(55),
            )
        )

        profile = Surface(
            orientation="vertical",
            size_hint_y=None,
            height=dp(166),
            padding=dp(16),
            spacing=dp(10),
        )

        profile.add_widget(
            AppLabel(
                text="Profile",
                font_size=sp(16),
                bold=True,
                size_hint_y=None,
                height=dp(30),
            )
        )

        self.profile_input = PremiumInput(
            hint_text="Your name",
        )
        profile.add_widget(self.profile_input)

        save_profile = PremiumButton(
            text="SAVE NAME",
            accent=True,
        )
        save_profile.bind(
            on_release=lambda *_args: self.save_name()
        )

        profile.add_widget(save_profile)
        root.add_widget(profile)

        appearance = Surface(
            orientation="vertical",
            size_hint_y=None,
            height=dp(130),
            padding=dp(16),
            spacing=dp(10),
        )

        appearance.add_widget(
            AppLabel(
                text="Appearance",
                font_size=sp(16),
                bold=True,
                size_hint_y=None,
                height=dp(30),
            )
        )

        self.theme_button = PremiumButton(
            text="SWITCH THEME",
        )
        self.theme_button.bind(
            on_release=lambda *_args: self.toggle_theme()
        )

        appearance.add_widget(self.theme_button)
        root.add_widget(appearance)

        television = Surface(
            orientation="vertical",
            size_hint_y=None,
            height=dp(165),
            padding=dp(16),
            spacing=dp(9),
        )

        television.add_widget(
            AppLabel(
                text="Television",
                font_size=sp(16),
                bold=True,
                size_hint_y=None,
                height=dp(30),
            )
        )

        self.selected_tv = AppLabel(
            text="No TV selected",
            role="secondary",
            font_size=sp(13),
            size_hint_y=None,
            height=dp(28),
        )
        television.add_widget(self.selected_tv)

        actions = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(50),
            spacing=dp(8),
        )

        change = PremiumButton(text="CHANGE TV")
        reconnect = PremiumButton(
            text="RECONNECT",
            accent=True,
        )

        change.bind(
            on_release=lambda *_args:
            App.get_running_app().go("discovery")
        )

        reconnect.bind(
            on_release=lambda *_args:
            App.get_running_app().reconnect()
        )

        actions.add_widget(change)
        actions.add_widget(reconnect)
        television.add_widget(actions)

        root.add_widget(television)

        root.add_widget(Widget())
        root.add_widget(NavigationBar(active="settings"))

        self.add_widget(root)

    def on_pre_enter(self, *_args):
        app = App.get_running_app()

        self.profile_input.text = app.store.get("name", "")

        tv_name = app.store.get("last_tv_name", "")
        host = app.store.get("last_tv", "")

        if tv_name and host:
            self.selected_tv.text = "{}\n{}".format(
                tv_name,
                host,
            )
        elif host:
            self.selected_tv.text = host
        else:
            self.selected_tv.text = "No TV selected"

        self._update_theme_text()

    def _update_theme_text(self):
        app = App.get_running_app()

        if app.theme.mode == "dark":
            self.theme_button.text = "USE LIGHT THEME"
        else:
            self.theme_button.text = "USE DARK THEME"

    def save_name(self):
        value = self.profile_input.text.strip()

        if not value:
            App.get_running_app().toast(
                "Please enter your name.",
                error=True,
            )
            return

        app = App.get_running_app()
        app.store.set("name", value)

        self.profile_input.focus = False
        app.toast("Name saved.")

    def toggle_theme(self):
        app = App.get_running_app()
        app.theme.toggle()
        self._update_theme_text()


class FahdRemoteApp(App):
    title = "Fahd LG Remote"

    connection_state = StringProperty("disconnected")
    connection_message = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.store = None
        self.theme = None
        self.tv = None
        self.discovery = None

        self.executor = None

        self.discovery_running = False

        self.manager = None
        self.toast_layer = None

        self._shutting_down = False
        self._connection_generation = 0

        self._pointer_lock = threading.Lock()
        self._pending_dx = 0.0
        self._pending_dy = 0.0
        self._pointer_flush_scheduled = False

    def build(self):
        Window.clearcolor = Design.DARK["background"]

        try:
            Window.softinput_mode = "below_target"
        except Exception:
            pass

        config_file = os.path.join(
            self.user_data_dir,
            "settings.json",
        )

        self.store = SettingsStore(config_file)
        self.theme = ThemeManager(self.store)

        self.executor = ThreadPoolExecutor(
            max_workers=3,
            thread_name_prefix="FahdRemote",
        )

        self.tv = WebOSTV(
            self.store,
            self._on_connection_state,
        )

        self.discovery = SSDPDiscovery()

        main = FloatLayout()

        self.manager = ScreenManager(
            transition=FadeTransition(
                duration=Design.SCREEN
            )
        )

        self.manager.add_widget(
            SplashScreen(name="splash")
        )
        self.manager.add_widget(
            WelcomeScreen(name="welcome")
        )
        self.manager.add_widget(
            HomeScreen(name="home")
        )
        self.manager.add_widget(
            DiscoveryScreen(name="discovery")
        )
        self.manager.add_widget(
            RemoteScreen(name="remote")
        )
        self.manager.add_widget(
            SettingsScreen(name="settings")
        )

        main.add_widget(self.manager)

        self.toast_layer = Toast()
        main.add_widget(self.toast_layer)

        self.manager.current = "splash"

        Clock.schedule_once(
            self._attempt_saved_connection,
            1.4,
        )

        return main

    def _attempt_saved_connection(self, _dt):
        host = self.store.get("last_tv", "").strip()

        if host and self.connection_state != "connected":
            self.connect_tv(
                host,
                quiet=True,
            )

    def go(self, screen_name):
        if not self.manager:
            return

        if screen_name not in self.manager.screen_names:
            return

        if self.manager.current == screen_name:
            return

        self.manager.current = screen_name

    def toast(self, message, error=False):
        if not self.toast_layer:
            return

        self.toast_layer.show(
            str(message),
            error=error,
        )

    def _on_connection_state(self, state, message=""):
        self.connection_state = state
        self.connection_message = message

        if not self.manager:
            return

        home = self.manager.get_screen("home")
        remote = self.manager.get_screen("remote")

        home.update_connection(state, message)
        remote.update_connection(state, message)

    def start_discovery(
        self,
        result_callback,
        done_callback,
    ):
        if self.discovery_running:
            return

        self.discovery_running = True

        self._on_connection_state(
            "searching",
            "Searching for LG webOS TVs",
        )

        self.discovery.stop()
        self.discovery = SSDPDiscovery()

        def finished():
            self.discovery_running = False

            if self.tv.connected:
                self._on_connection_state(
                    "connected",
                    "Connected",
                )
            else:
                self._on_connection_state(
                    "disconnected",
                    "Disconnected",
                )

            done_callback()

        self.executor.submit(
            self.discovery.discover,
            result_callback,
            finished,
            4.5,
        )

    @staticmethod
    def _valid_host(host):
        if not host:
            return False

        value = str(host).strip()

        if not value or len(value) > 255:
            return False

        try:
            socket.inet_aton(value)
            return value.count(".") == 3
        except OSError:
            pass

        allowed = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789.-"
        )

        return all(char in allowed for char in value)

    def connect_tv(
        self,
        host,
        friendly_name=None,
        quiet=False,
    ):
        host = str(host).strip()

        if not self._valid_host(host):
            self.toast(
                "Invalid TV address.",
                error=True,
            )
            return

        self._connection_generation += 1
        generation = self._connection_generation

        if friendly_name:
            self.store.set(
                "last_tv_name",
                friendly_name,
            )

        self.store.set("last_tv", host)

        self._on_connection_state(
            "connecting",
            "Connecting",
        )

        def worker():
            try:
                result = self.tv.connect(host)

                if generation != self._connection_generation:
                    return

                if result:
                    Clock.schedule_once(
                        lambda _dt: self._connected_ui(
                            quiet
                        ),
                        0,
                    )
                elif not quiet:
                    Clock.schedule_once(
                        lambda _dt: self.toast(
                            "Could not connect to the TV.",
                            error=True,
                        ),
                        0,
                    )

            except Exception as exc:
                if generation != self._connection_generation:
                    return

                Clock.schedule_once(
                    lambda _dt, error=str(exc):
                    self._connection_failed(
                        error,
                        quiet,
                    ),
                    0,
                )

        self.executor.submit(worker)

    def _connected_ui(self, quiet=False):
        if not quiet:
            self.toast("Connected to LG webOS TV.")

        if (
            self.manager
            and self.manager.current == "discovery"
        ):
            self.go("remote")

    def _connection_failed(
        self,
        error,
        quiet=False,
    ):
        self._on_connection_state(
            "error",
            error,
        )

        if not quiet:
            self.toast(
                "Connection failed: {}".format(error),
                error=True,
            )

    def reconnect(self):
        host = self.store.get("last_tv", "").strip()

        if not host:
            self.toast(
                "Select a TV first.",
                error=True,
            )
            self.go("discovery")
            return

        self.connect_tv(host)

    def _submit_command(
        self,
        function,
        *args,
        show_error=True
    ):
        if not self.tv.connected:
            if show_error:
                self.toast(
                    "Connect to your TV first.",
                    error=True,
                )
            return

        def worker():
            try:
                function(*args)
            except Exception as exc:
                if show_error:
                    Clock.schedule_once(
                        lambda _dt, error=str(exc):
                        self.toast(
                            "TV command failed: {}".format(
                                error
                            ),
                            error=True,
                        ),
                        0,
                    )

        self.executor.submit(worker)

    def remote_button(self, key):
        self._submit_command(
            self.tv.button,
            key,
            show_error=False,
        )

    def pointer_click(self):
        self._submit_command(
            self.tv.click,
            show_error=False,
        )

    def pointer_move(self, dx, dy):
        if not self.tv.connected:
            return

        with self._pointer_lock:
            self._pending_dx += dx
            self._pending_dy += dy

            if self._pointer_flush_scheduled:
                return

            self._pointer_flush_scheduled = True

        Clock.schedule_once(
            self._flush_pointer,
            1.0 / 45.0,
        )

    def _flush_pointer(self, _dt):
        with self._pointer_lock:
            dx = self._pending_dx
            dy = self._pending_dy

            self._pending_dx = 0.0
            self._pending_dy = 0.0
            self._pointer_flush_scheduled = False

        if not self.tv.connected:
            return

        if abs(dx) < 0.1 and abs(dy) < 0.1:
            return

        self._submit_command(
            self.tv.move_pointer,
            dx,
            dy,
            show_error=False,
        )

    def volume_up(self):
        self._submit_command(
            self.tv.volume_up
        )

    def volume_down(self):
        self._submit_command(
            self.tv.volume_down
        )

    def toggle_mute(self):
        self._submit_command(
            self.tv.toggle_mute
        )

    def power_off(self):
        self._submit_command(
            self.tv.power_off
        )

    def on_pause(self):
        return True

    def on_resume(self):
        if (
            self.store
            and self.connection_state != "connected"
        ):
            Clock.schedule_once(
                self._attempt_saved_connection,
                0.6,
            )

    def on_stop(self):
        if self._shutting_down:
            return

        self._shutting_down = True
        self._connection_generation += 1

        try:
            if self.discovery:
                self.discovery.stop()
        except Exception:
            pass

        try:
            if self.tv:
                self.tv.disconnect(
                    notify=False
                )
        except Exception:
            pass

        try:
            if self.executor:
                self.executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )
        except Exception:
            pass


if __name__ == "__main__":
    FahdRemoteApp().run()





    