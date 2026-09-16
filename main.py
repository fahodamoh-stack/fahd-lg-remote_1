# -*- coding: utf-8 -*-

import json
import math
import os
import socket
import ssl
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import websocket

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    Rectangle,
    RoundedRectangle,
)
from kivy.metrics import dp, sp
from kivy.properties import (
    BooleanProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import (
    Screen,
    ScreenManager,
    SlideTransition,
)
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


# ============================================================
# Desktop development preview
# Android ignores the desktop window dimensions.
# ============================================================

if os.environ.get("ANDROID_ARGUMENT") is None:
    Window.size = (390, 800)

Window.clearcolor = (0.027, 0.035, 0.051, 1)


APP_NAME = "Fahd Remote"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path.home() / ".aether_lg_remote"
CONFIG_FILE = DATA_DIR / "settings.json"


# ============================================================
# Helpers
# ============================================================

def hex_color(value, alpha=1.0):
    value = value.strip().lstrip("#")

    if len(value) != 6:
        raise ValueError("Expected a 6-digit hex color")

    return [
        int(value[0:2], 16) / 255.0,
        int(value[2:4], 16) / 255.0,
        int(value[4:6], 16) / 255.0,
        alpha,
    ]


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def ui(callback, *args):
    Clock.schedule_once(lambda dt: callback(*args), 0)


# ============================================================
# Theme
# ============================================================

class Theme:
    COLORS = {
        "background": hex_color("#07090D"),
        "surface": hex_color("#0E1117"),
        "elevated": hex_color("#151922"),
        "soft": hex_color("#1B2029"),

        "text": hex_color("#E9EDF2"),
        "secondary": hex_color("#A7ADB8"),
        "muted": hex_color("#737B88"),

        "border": hex_color("#252B35"),

        "accent": hex_color("#8EA7C7"),
        "accent_dark": hex_color("#536B89"),

        "green": hex_color("#55C98A"),
        "red": hex_color("#B94A55"),
        "orange": hex_color("#C89658"),
    }

    @classmethod
    def get(cls, name, alpha=None):
        color = list(cls.COLORS[name])

        if alpha is not None:
            color[3] = alpha

        return color


# ============================================================
# Persistent settings
# ============================================================

class SettingsStore:
    def __init__(self):
        self.lock = threading.RLock()

        self.data = {
            "client_keys": {},
            "last_tv": None,
            "user_name": "",
        }

        self.load()

    def load(self):
        try:
            if not CONFIG_FILE.exists():
                return

            loaded = json.loads(
                CONFIG_FILE.read_text(encoding="utf-8")
            )

            if isinstance(loaded, dict):
                self.data.update(loaded)

            if not isinstance(self.data.get("client_keys"), dict):
                self.data["client_keys"] = {}

        except Exception:
            # A corrupt settings file must never prevent startup.
            pass

    def save(self):
        with self.lock:
            try:
                DATA_DIR.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                temp = CONFIG_FILE.with_suffix(".tmp")

                temp.write_text(
                    json.dumps(
                        self.data,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                temp.replace(CONFIG_FILE)

            except Exception:
                pass

    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)

    def set(self, key, value):
        with self.lock:
            self.data[key] = value

        self.save()

    def get_client_key(self, host):
        with self.lock:
            return self.data.get(
                "client_keys",
                {},
            ).get(host)

    def set_client_key(self, host, key):
        with self.lock:
            keys = self.data.setdefault(
                "client_keys",
                {},
            )

            keys[host] = key

        self.save()


# ============================================================
# Base themed widgets
# ============================================================

class AppLabel(Label):
    def __init__(self, **kwargs):
        kwargs.setdefault("color", Theme.get("text"))
        kwargs.setdefault("font_size", sp(14))
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")

        super().__init__(**kwargs)

        self.bind(
            size=self._update_text_size
        )

    def _update_text_size(self, *_):
        self.text_size = (
            self.width,
            None,
        )


class Surface(BoxLayout):
    def __init__(
        self,
        surface="surface",
        radius=22,
        border=True,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self._surface_name = surface
        self._radius = dp(radius)
        self._has_border = border

        with self.canvas.before:
            self._bg_color = Color(
                *Theme.get(surface)
            )

            self._background = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._radius],
            )

            self._border_color = Color(
                *Theme.get(
                    "border",
                    0.95 if border else 0,
                )
            )

            self._border = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    self._radius,
                ),
                width=dp(1),
            )

        self.bind(
            pos=self._sync_canvas,
            size=self._sync_canvas,
        )

    def _sync_canvas(self, *_):
        self._background.pos = self.pos
        self._background.size = self.size

        self._border.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            self._radius,
        )


class PremiumButton(Widget):
    text = StringProperty("")
    accent = StringProperty("soft")
    text_color_name = StringProperty("text")
    disabled = BooleanProperty(False)
    scale = NumericProperty(1.0)

    def __init__(
        self,
        callback=None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.callback = callback
        self._pressed = False

        if self.size_hint_y is None and not self.height:
            self.height = dp(52)

        with self.canvas.before:
            self._glow_color = Color(0, 0, 0, 0)

            self._glow = RoundedRectangle(
                radius=[dp(18)]
            )

            self._shadow_color = Color(
                0,
                0,
                0,
                0.18,
            )

            self._shadow = RoundedRectangle(
                radius=[dp(17)]
            )

            self._bg_color = Color(
                *Theme.get(self.accent)
            )

            self._background = RoundedRectangle(
                radius=[dp(17)]
            )

            self._border_color = Color(
                *Theme.get("border")
            )

            self._border = Line(
                width=dp(1),
                rounded_rectangle=(
                    0,
                    0,
                    1,
                    1,
                    dp(17),
                ),
            )

        self.label = AppLabel(
            text=self.text,
            color=Theme.get(self.text_color_name),
            font_size=sp(13),
            bold=True,
            halign="center",
        )

        self.add_widget(self.label)

        self.bind(
            text=self._sync_text,
            pos=self._sync_geometry,
            size=self._sync_geometry,
            scale=self._sync_geometry,
            accent=self._sync_colors,
            text_color_name=self._sync_colors,
        )

        Clock.schedule_once(
            lambda dt: self._sync_colors(),
            0,
        )

    def _sync_text(self, *_):
        self.label.text = self.text

    def _sync_colors(self, *_):
        self._bg_color.rgba = Theme.get(
            self.accent
        )

        self.label.color = Theme.get(
            self.text_color_name
        )

    def _sync_geometry(self, *_):
        width = self.width * self.scale
        height = self.height * self.scale

        x = self.center_x - width / 2
        y = self.center_y - height / 2

        self._background.pos = (x, y)
        self._background.size = (width, height)

        self._shadow.pos = (
            x,
            y - dp(2),
        )

        self._shadow.size = (
            width,
            height,
        )

        self._glow.pos = (
            x - dp(3),
            y - dp(3),
        )

        self._glow.size = (
            width + dp(6),
            height + dp(6),
        )

        self._border.rounded_rectangle = (
            x,
            y,
            width,
            height,
            dp(17),
        )

        self.label.pos = (
            x,
            y,
        )

        self.label.size = (
            width,
            height,
        )

    def press_visual(self):
        Animation.cancel_all(
            self,
            "scale",
        )

        Animation(
            scale=0.965,
            duration=0.075,
            t="out_quad",
        ).start(self)

    def release_visual(self):
        Animation.cancel_all(
            self,
            "scale",
        )

        Animation(
            scale=1,
            duration=0.14,
            t="out_back",
        ).start(self)

    def on_touch_down(self, touch):
        if (
            self.disabled
            or not self.collide_point(*touch.pos)
        ):
            return super().on_touch_down(touch)

        touch.grab(self)

        self._pressed = True
        self.press_visual()

        if self.accent == "red":
            self._glow_color.rgba = Theme.get(
                "red",
                0.12,
            )

        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)

        touch.ungrab(self)

        was_inside = self.collide_point(
            *touch.pos
        )

        self._pressed = False

        self.release_visual()

        Animation(
            a=0,
            duration=0.15,
        ).start(self._glow_color)

        if (
            was_inside
            and not self.disabled
            and self.callback
        ):
            Clock.schedule_once(
                lambda dt: self.callback(self),
                0,
            )

        return True


class PremiumInput(TextInput):
    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("font_size", sp(15))
        kwargs.setdefault("write_tab", False)

        super().__init__(**kwargs)

        self.size_hint_y = None
        self.height = dp(54)

        self.background_normal = ""
        self.background_active = ""

        self.background_color = Theme.get("elevated")
        self.foreground_color = Theme.get("text")
        self.hint_text_color = Theme.get("muted")
        self.cursor_color = Theme.get("accent")

        self.padding = [
            dp(16),
            dp(14),
        ]

        self.readonly = False
        self.disabled = False

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.focus = True

        return super().on_touch_down(touch)



# ============================================================
# Canvas icons
# ============================================================

class NavIcon(Widget):
    kind = StringProperty("home")
    active = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        with self.canvas:
            self._color = Color(
                *Theme.get("secondary")
            )

            self._line1 = Line(
                width=dp(1.7)
            )

            self._line2 = Line(
                width=dp(1.7)
            )

            self._circle = Line(
                width=dp(1.7)
            )

        self.bind(
            pos=self._draw,
            size=self._draw,
            kind=self._draw,
            active=self._draw,
        )

    def _draw(self, *_):
        self._color.rgba = Theme.get(
            "accent" if self.active else "muted"
        )

        self._line1.points = []
        self._line2.points = []
        self._circle.circle = (
            0,
            0,
            0,
        )

        cx = self.center_x
        cy = self.center_y

        s = min(
            self.width,
            self.height,
        )

        if self.kind == "home":
            self._line1.points = [
                cx - s * 0.28,
                cy,
                cx,
                cy + s * 0.24,
                cx + s * 0.28,
                cy,
            ]

            self._line2.points = [
                cx - s * 0.20,
                cy,
                cx - s * 0.20,
                cy - s * 0.24,
                cx + s * 0.20,
                cy - s * 0.24,
                cx + s * 0.20,
                cy,
            ]

        elif self.kind == "remote":
            self._line1.rounded_rectangle = (
                cx - s * 0.18,
                cy - s * 0.32,
                s * 0.36,
                s * 0.64,
                dp(5),
            )

            self._circle.circle = (
                cx,
                cy + s * 0.14,
                s * 0.06,
            )

        else:
            self._circle.circle = (
                cx,
                cy,
                s * 0.20,
            )

            self._line1.circle = (
                cx,
                cy,
                s * 0.31,
            )


# ============================================================
# Status indicator
# ============================================================

class StatusIndicator(Widget):
    state = StringProperty("disconnected")
    pulse = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        with self.canvas:
            self._glow_color = Color(
                0,
                0,
                0,
                0,
            )

            self._glow = Ellipse()

            self._ring_color = Color(
                *Theme.get("border")
            )

            self._ring = Line(
                width=dp(1.2),
            )

            self._dot_color = Color(
                *Theme.get("muted")
            )

            self._dot = Ellipse()

        self.bind(
            pos=self._sync,
            size=self._sync,
            pulse=self._sync,
            state=self._state_changed,
        )

        Clock.schedule_once(
            lambda dt: self._state_changed(),
            0,
        )

    def _sync(self, *_):
        radius = min(
            self.width,
            self.height,
        ) * 0.16

        glow_radius = radius * (
            2.1 + self.pulse * 0.35
        )

        self._glow.pos = (
            self.center_x - glow_radius,
            self.center_y - glow_radius,
        )

        self._glow.size = (
            glow_radius * 2,
            glow_radius * 2,
        )

        self._dot.pos = (
            self.center_x - radius,
            self.center_y - radius,
        )

        self._dot.size = (
            radius * 2,
            radius * 2,
        )

        self._ring.circle = (
            self.center_x,
            self.center_y,
            radius * (
                1.65 + self.pulse * 0.2
            ),
        )

    def _state_changed(self, *_):
        Animation.cancel_all(
            self,
            "pulse",
        )

        if self.state == "connected":
            c = Theme.get("green")

            self._dot_color.rgba = c
            self._ring_color.rgba = Theme.get(
                "green",
                0.35,
            )
            self._glow_color.rgba = Theme.get(
                "green",
                0.09,
            )

            Animation(
                pulse=0.65,
                duration=0.32,
                t="out_quad",
            ).start(self)

        elif self.state in (
            "searching",
            "connecting",
        ):
            self._dot_color.rgba = Theme.get(
                "accent"
            )

            self._ring_color.rgba = Theme.get(
                "accent",
                0.38,
            )

            self._glow_color.rgba = Theme.get(
                "accent",
                0.07,
            )

            anim = (
                Animation(
                    pulse=1,
                    duration=0.65,
                    t="in_out_quad",
                )
                +
                Animation(
                    pulse=0,
                    duration=0.65,
                    t="in_out_quad",
                )
            )

            anim.repeat = True
            anim.start(self)

        elif self.state == "error":
            self._dot_color.rgba = Theme.get(
                "red"
            )

            self._ring_color.rgba = Theme.get(
                "red",
                0.32,
            )

            self._glow_color.rgba = Theme.get(
                "red",
                0.06,
            )

        else:
            self._dot_color.rgba = Theme.get(
                "muted"
            )

            self._ring_color.rgba = Theme.get(
                "border"
            )

            self._glow_color.rgba = [
                0,
                0,
                0,
                0,
            ]


# ============================================================
# Loading indicator
# ============================================================

class LoadingRing(Widget):
    angle = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.running = False

        with self.canvas:
            self._track_color = Color(
                *Theme.get("border")
            )

            self._track = Line(
                width=dp(2),
            )

            self._arc_color = Color(
                *Theme.get("accent")
            )

            self._arc = Line(
                width=dp(2.2),
            )

        self.bind(
            pos=self._sync,
            size=self._sync,
            angle=self._sync,
        )

    def _sync(self, *_):
        radius = max(
            dp(5),
            min(
                self.width,
                self.height,
            ) / 2 - dp(4),
        )

        self._track.circle = (
            self.center_x,
            self.center_y,
            radius,
            0,
            360,
        )

        self._arc.circle = (
            self.center_x,
            self.center_y,
            radius,
            self.angle,
            self.angle + 92,
        )

    def start(self):
        self.running = True

        Animation.cancel_all(
            self,
            "angle",
        )

        self.angle = 0

        anim = Animation(
            angle=360,
            duration=0.85,
            t="linear",
        )

        anim.repeat = True
        anim.start(self)

    def stop(self):
        self.running = False

        Animation.cancel_all(
            self,
            "angle",
        )


# ============================================================
# LG webOS communication
# ============================================================

class LGWebOSClient:
    """
    Real LG webOS SSAP client.

    UI callbacks are always scheduled back onto Kivy's UI thread.
    Network work never runs on Kivy's main thread.
    """

    REGISTER_MANIFEST = {
        "manifestVersion": 1,
        "appVersion": "1.0",
        "signed": {
            "created": "20140509",
            "appId": "com.lge.test",
            "vendorId": "com.lge",
            "localizedAppNames": {
                "": "Fahd Remote"
            },
            "localizedVendorNames": {
                "": "Fahd"
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
                "READ_TV_CURRENT_TIME",
            ],
            "serial": "2f930e2d2cfe083771f68e4fe7bb07",
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
        ],
    }

    def __init__(
        self,
        settings,
        state_callback=None,
    ):
        self.settings = settings
        self.state_callback = state_callback

        self.host = None
        self.tv_name = None

        self.ws = None
        self.pointer_ws = None

        self.connected = False

        # SSAP replies must not be consumed by multiple threads.
        # Every request is serialized through this lock.
        self.request_lock = threading.RLock()

        self.pointer_lock = threading.RLock()
        self.connection_lock = threading.RLock()

        self.request_counter = 0

    def _emit(
        self,
        state,
        message="",
    ):
        if self.state_callback:
            ui(
                self.state_callback,
                state,
                message,
            )

    @staticmethod
    def discover(timeout=3.4):
        """
        SSDP discovery for LG webOS TVs.
        """

        targets = [
            "urn:lge-com:service:webos-second-screen:1",
            "urn:schemas-upnp-org:device:MediaRenderer:1",
            "ssdp:all",
        ]

        devices = {}

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
            socket.IPPROTO_UDP,
        )

        try:
            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )

            sock.settimeout(0.25)

            for target in targets:
                packet = (
                    "M-SEARCH * HTTP/1.1\r\n"
                    "HOST: 239.255.255.250:1900\r\n"
                    'MAN: "ssdp:discover"\r\n'
                    "MX: 2\r\n"
                    f"ST: {target}\r\n"
                    "\r\n"
                ).encode("utf-8")

                try:
                    sock.sendto(
                        packet,
                        (
                            "239.255.255.250",
                            1900,
                        ),
                    )
                except OSError:
                    pass

            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                try:
                    data, address = sock.recvfrom(
                        65535
                    )

                except socket.timeout:
                    continue

                except OSError:
                    break

                raw = data.decode(
                    "utf-8",
                    errors="ignore",
                )

                lower = raw.lower()

                # Avoid showing every UPnP device in the house.
                looks_like_lg = any(
                    token in lower
                    for token in (
                        "webos",
                        "lge",
                        "lg electronics",
                        "webos-second-screen",
                    )
                )

                if not looks_like_lg:
                    continue

                headers = {}

                for line in raw.splitlines():
                    if ":" not in line:
                        continue

                    key, value = line.split(
                        ":",
                        1,
                    )

                    headers[
                        key.strip().lower()
                    ] = value.strip()

                host = address[0]

                name = (
                    headers.get("friendlyname")
                    or headers.get("server")
                    or "LG webOS TV"
                )

                devices[host] = {
                    "host": host,
                    "name": name,
                    "location": headers.get(
                        "location",
                        "",
                    ),
                }

        finally:
            try:
                sock.close()
            except Exception:
                pass

        return list(devices.values())

    def connect_async(
        self,
        host,
        name=None,
    ):
        if not host:
            return

        threading.Thread(
            target=self._connect_worker,
            args=(
                host.strip(),
                name,
            ),
            daemon=True,
            name="lg-connect",
        ).start()

    def _open_control_socket(self, host):
        """
        Newer TVs normally use TLS :3001.
        Older models may use ws://:3000.

        webOS generally uses a self-signed TLS certificate, therefore
        certificate verification cannot be used without installing the
        TV certificate as a trust anchor.
        """

        attempts = [
            (
                f"wss://{host}:3001/",
                {
                    "cert_reqs": ssl.CERT_NONE,
                    "check_hostname": False,
                },
            ),
            (
                f"ws://{host}:3000/",
                None,
            ),
        ]

        last_error = None

        for url, ssl_options in attempts:
            try:
                kwargs = {
                    "timeout": 8,
                }

                if ssl_options is not None:
                    kwargs["sslopt"] = ssl_options

                ws = websocket.create_connection(
                    url,
                    **kwargs,
                )

                ws.settimeout(8)

                return ws

            except Exception as error:
                last_error = error

        if last_error:
            raise last_error

        raise ConnectionError(
            "Unable to open the webOS socket"
        )

    def _connect_worker(
        self,
        host,
        name=None,
    ):
        with self.connection_lock:
            self.disconnect(
                emit=False
            )

            self._emit(
                "connecting",
                "Connecting to TV...",
            )

            control = None

            try:
                control = self._open_control_socket(
                    host
                )

                client_key = (
                    self.settings.get_client_key(
                        host
                    )
                )

                payload = {
                    "type": "register",
                    "id": "register_0",
                    "payload": {
                        "forcePairing": False,
                        "pairingType": "PROMPT",
                        "manifest": self.REGISTER_MANIFEST,
                    },
                }

                if client_key:
                    payload["payload"][
                        "client-key"
                    ] = client_key

                control.send(
                    json.dumps(payload)
                )

                deadline = (
                    time.monotonic()
                    + 30
                )

                registered = False
                new_key = None

                while (
                    time.monotonic()
                    < deadline
                ):
                    try:
                        raw = control.recv()

                    except websocket.WebSocketTimeoutException:
                        continue

                    if not raw:
                        continue

                    reply = json.loads(raw)

                    reply_type = reply.get(
                        "type"
                    )

                    if reply_type == "registered":
                        registered = True

                        new_key = (
                            reply.get(
                                "payload",
                                {},
                            ).get(
                                "client-key"
                            )
                        )

                        break

                    if reply_type == "error":
                        raise ConnectionError(
                            reply.get(
                                "error",
                                "Pairing rejected",
                            )
                        )

                if not registered:
                    raise TimeoutError(
                        "Pairing timed out. Accept the pairing request on the TV."
                    )

                with self.request_lock:
                    self.ws = control
                    self.host = host
                    self.tv_name = (
                        name
                        or "LG webOS TV"
                    )
                    self.connected = True

                if new_key:
                    self.settings.set_client_key(
                        host,
                        new_key,
                    )

                self.settings.set(
                    "last_tv",
                    {
                        "host": host,
                        "name": self.tv_name,
                    },
                )

                self._emit(
                    "connected",
                    "Connected",
                )

                self._setup_pointer()

            except Exception as error:
                try:
                    if control:
                        control.close()
                except Exception:
                    pass

                with self.request_lock:
                    self.ws = None
                    self.connected = False

                self._emit(
                    "error",
                    self._friendly_error(
                        error
                    ),
                )

    @staticmethod
    def _friendly_error(error):
        text = str(error).strip()

        lower = text.lower()

        if isinstance(
            error,
            TimeoutError,
        ):
            return text

        if (
            "timed out" in lower
            or "timeout" in lower
        ):
            return (
                "Connection timed out. "
                "Make sure the TV is on and connected to the same network."
            )

        if "refused" in lower:
            return (
                "Connection refused. "
                "Check LG TV network and mobile-app connection settings."
            )

        if not text:
            return "Could not connect to the TV."

        return (
            "Connection failed: "
            + text[:120]
        )

    def _next_request_id(self):
        self.request_counter += 1
        return (
            f"aether_{self.request_counter}"
        )

    def request(
        self,
        uri,
        payload=None,
        timeout=6,
    ):
        """
        Send a serialized SSAP request.

        Serialization is intentional. websocket-client does not provide
        request/reply routing for LG's protocol.
        """

        with self.request_lock:
            if (
                not self.connected
                or not self.ws
            ):
                raise ConnectionError(
                    "TV is not connected"
                )

            request_id = (
                self._next_request_id()
            )

            message = {
                "type": "request",
                "id": request_id,
                "uri": uri,
                "payload": payload or {},
            }

            try:
                self.ws.settimeout(
                    timeout
                )

                self.ws.send(
                    json.dumps(message)
                )

                deadline = (
                    time.monotonic()
                    + timeout
                )

                while (
                    time.monotonic()
                    < deadline
                ):
                    try:
                        raw = self.ws.recv()

                    except websocket.WebSocketTimeoutException:
                        continue

                    if not raw:
                        continue

                    reply = json.loads(
                        raw
                    )

                    if (
                        reply.get("id")
                        != request_id
                    ):
                        continue

                    if reply.get(
                        "type"
                    ) == "error":
                        raise RuntimeError(
                            reply.get(
                                "error",
                                "webOS request failed",
                            )
                        )

                    return reply.get(
                        "payload",
                        {},
                    )

                raise TimeoutError(
                    "TV request timed out"
                )

            except Exception:
                # Do not incorrectly mark the TV disconnected for every
                # unsupported SSAP command. Only socket-level failures
                # should ultimately require reconnecting.
                raise

    def request_async(
        self,
        uri,
        payload=None,
        success=None,
        failure=None,
    ):
        def worker():
            try:
                result = self.request(
                    uri,
                    payload,
                )

                if success:
                    ui(
                        success,
                        result,
                    )

            except Exception as error:
                if failure:
                    ui(
                        failure,
                        error,
                    )

        threading.Thread(
            target=worker,
            daemon=True,
            name="lg-request",
        ).start()

    def _setup_pointer(self):
        try:
            result = self.request(
                "ssap://com.webos.service.networkinput/getPointerInputSocket",
                timeout=6,
            )

            socket_path = result.get(
                "socketPath"
            )

            if not socket_path:
                raise RuntimeError(
                    "TV did not return pointer socket"
                )

            kwargs = {
                "timeout": 6,
            }

            if socket_path.startswith(
                "wss://"
            ):
                kwargs["sslopt"] = {
                    "cert_reqs": ssl.CERT_NONE,
                    "check_hostname": False,
                }

            pointer = (
                websocket.create_connection(
                    socket_path,
                    **kwargs,
                )
            )

            with self.pointer_lock:
                old = self.pointer_ws
                self.pointer_ws = pointer

                try:
                    if old:
                        old.close()
                except Exception:
                    pass

        except Exception:
            with self.pointer_lock:
                self.pointer_ws = None

    def ensure_pointer_async(self):
        with self.pointer_lock:
            if self.pointer_ws:
                return

        threading.Thread(
            target=self._setup_pointer,
            daemon=True,
            name="lg-pointer-connect",
        ).start()

    def pointer_send(self, message):
        """
        Pointer traffic is tiny and uses a different socket.

        We keep the critical section short. If the pointer socket has
        disappeared, reconnect is scheduled in the background.
        """

        with self.pointer_lock:
            pointer = self.pointer_ws

            if not pointer:
                self.ensure_pointer_async()
                return False

            try:
                pointer.send(message)
                return True

            except Exception:
                try:
                    pointer.close()
                except Exception:
                    pass

                self.pointer_ws = None

        self.ensure_pointer_async()
        return False

    def button(self, name):
        self.pointer_send(
            "type:button\n"
            f"name:{name}\n"
            "\n"
        )

    def pointer_move(
        self,
        dx,
        dy,
    ):
        dx = int(
            clamp(
                dx,
                -300,
                300,
            )
        )

        dy = int(
            clamp(
                dy,
                -300,
                300,
            )
        )

        if dx == 0 and dy == 0:
            return

        self.pointer_send(
            "type:move\n"
            f"dx:{dx}\n"
            f"dy:{dy}\n"
            "down:0\n"
            "\n"
        )

    def click(self):
        self.pointer_send(
            "type:click\n\n"
        )

    def volume_up(self):
        self.request_async(
            "ssap://audio/volumeUp"
        )

    def volume_down(self):
        self.request_async(
            "ssap://audio/volumeDown"
        )

    def toggle_mute(self):
        def got_status(payload):
            muted = bool(
                payload.get("mute", False)
            )

            self.request_async(
                "ssap://audio/setMute",
                {
                    "mute": not muted
                },
            )

        self.request_async(
            "ssap://audio/getStatus",
            success=got_status,
        )

    def power_off(
        self,
        success=None,
        failure=None,
    ):
        self.request_async(
            "ssap://system/turnOff",
            success=success,
            failure=failure,
        )

    def disconnect(
        self,
        emit=True,
    ):
        with self.pointer_lock:
            pointer = self.pointer_ws
            self.pointer_ws = None

        try:
            if pointer:
                pointer.close()
        except Exception:
            pass

        with self.request_lock:
            control = self.ws

            self.ws = None
            self.connected = False

        try:
            if control:
                control.close()
        except Exception:
            pass

        if emit:
            self._emit(
                "disconnected",
                "Disconnected",
            )


# ============================================================
# Touchpad
# ============================================================

class TouchPad(Surface):
    def __init__(self, **kwargs):
        super().__init__(
            surface="elevated",
            radius=28,
            orientation="vertical",
            **kwargs,
        )

        self._touching = False
        self._last_position = None
        self._start_position = None
        self._start_time = 0

        self.label = AppLabel(
            text="TOUCHPAD",
            color=Theme.get("muted"),
            font_size=sp(11),
            halign="center",
        )

        self.hint = AppLabel(
            text="Move your finger to control",
            color=Theme.get("secondary"),
            font_size=sp(13),
            halign="center",
        )

        self.add_widget(
            Widget()
        )

        self.add_widget(
            self.label
        )

        self.add_widget(
            self.hint
        )

        self.add_widget(
            Widget()
        )

    def on_touch_down(
        self,
        touch,
    ):
        if not self.collide_point(
            *touch.pos
        ):
            return super().on_touch_down(
                touch
            )

        touch.grab(self)

        self._touching = True
        self._last_position = touch.pos
        self._start_position = touch.pos
        self._start_time = time.monotonic()

        self._border_color.rgba = Theme.get(
            "accent",
            0.58,
        )

        return True

    def on_touch_move(
        self,
        touch,
    ):
        if touch.grab_current is not self:
            return super().on_touch_move(
                touch
            )

        if self._last_position:
            dx = (
                touch.x
                - self._last_position[0]
            ) * 1.35

            dy = (
                touch.y
                - self._last_position[1]
            ) * 1.35

            App.get_running_app().lg.pointer_move(
                dx,
                dy,
            )

        self._last_position = touch.pos

        return True

    def on_touch_up(
        self,
        touch,
    ):
        if touch.grab_current is not self:
            return super().on_touch_up(
                touch
            )

        touch.ungrab(self)

        self._touching = False

        self._border_color.rgba = Theme.get(
            "border"
        )

        if self._start_position:
            distance = math.hypot(
                touch.x
                - self._start_position[0],
                touch.y
                - self._start_position[1],
            )

            duration = (
                time.monotonic()
                - self._start_time
            )

            if (
                distance < dp(12)
                and duration < 0.45
            ):
                App.get_running_app().lg.click()

        self._last_position = None
        self._start_position = None

        return True


# ============================================================
# Repeat D-pad button
# ============================================================

class RepeatButton(PremiumButton):
    command = StringProperty("")

    def __init__(self, **kwargs):
        # RepeatButton sends commands itself.
        kwargs["callback"] = None

        super().__init__(**kwargs)

        self._delay_event = None
        self._repeat_event = None

    def _send_command(self):
        if self.command:
            App.get_running_app().lg.button(
                self.command
            )

    def on_touch_down(
        self,
        touch,
    ):
        handled = super().on_touch_down(
            touch
        )

        if (
            handled
            and self._pressed
        ):
            # First command immediately.
            self._send_command()

            self._delay_event = (
                Clock.schedule_once(
                    self._start_repeat,
                    0.38,
                )
            )

        return handled

    def _start_repeat(
        self,
        dt,
    ):
        self._delay_event = None

        if not self._pressed:
            return

        self._repeat_event = (
            Clock.schedule_interval(
                self._repeat_tick,
                0.12,
            )
        )

    def _repeat_tick(
        self,
        dt,
    ):
        if not self._pressed:
            self._stop_repeat()
            return False

        self._send_command()

        return True

    def _stop_repeat(self):
        if self._delay_event:
            self._delay_event.cancel()
            self._delay_event = None

        if self._repeat_event:
            self._repeat_event.cancel()
            self._repeat_event = None

    def on_touch_up(
        self,
        touch,
    ):
        if touch.grab_current is self:
            self._stop_repeat()

        return super().on_touch_up(
            touch
        )


# ============================================================
# D-pad
# ============================================================

class DPad(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        size = (
            dp(66),
            dp(54),
        )

        self.btn_up = RepeatButton(
            text="UP",
            command="UP",
            size_hint=(None, None),
            size=size,
            pos_hint={
                "center_x": 0.5,
                "top": 1,
            },
        )

        self.btn_down = RepeatButton(
            text="DOWN",
            command="DOWN",
            size_hint=(None, None),
            size=size,
            pos_hint={
                "center_x": 0.5,
                "y": 0,
            },
        )

        self.btn_left = RepeatButton(
            text="LEFT",
            command="LEFT",
            size_hint=(None, None),
            size=size,
            pos_hint={
                "x": 0,
                "center_y": 0.5,
            },
        )

        self.btn_right = RepeatButton(
            text="RIGHT",
            command="RIGHT",
            size_hint=(None, None),
            size=size,
            pos_hint={
                "right": 1,
                "center_y": 0.5,
            },
        )

        self.btn_ok = PremiumButton(
            text="OK",
            accent="elevated",
            size_hint=(None, None),
            size=(
                dp(68),
                dp(68),
            ),
            pos_hint={
                "center_x": 0.5,
                "center_y": 0.5,
            },
            callback=lambda button:
                App.get_running_app().lg.button(
                    "ENTER"
                ),
        )

        for button in (
            self.btn_up,
            self.btn_down,
            self.btn_left,
            self.btn_right,
            self.btn_ok,
        ):
            self.add_widget(button)


# ============================================================
# Bottom navigation
# ============================================================

class BottomNavigation(Surface):
    def __init__(
        self,
        active="home",
        **kwargs,
    ):
        super().__init__(
            surface="surface",
            radius=23,
            orientation="horizontal",
            spacing=dp(4),
            padding=dp(5),
            **kwargs,
        )

        self.size_hint_y = None
        self.height = dp(67)

        self.active = active
        self.items = {}

        definitions = [
            (
                "home",
                "HOME",
                "home",
            ),
            (
                "remote",
                "REMOTE",
                "remote",
            ),
            (
                "settings",
                "SETTINGS",
                "settings",
            ),
        ]

        for screen_name, title, icon_kind in definitions:
            holder = FloatLayout()

            button = PremiumButton(
                text=title,
                accent=(
                    "elevated"
                    if screen_name == active
                    else "surface"
                ),
                callback=lambda button, name=screen_name:
                    self.navigate(name),
                pos_hint={
                    "x": 0,
                    "y": 0,
                },
                size_hint=(
                    1,
                    1,
                ),
            )

            holder.add_widget(
                button
            )

            self.add_widget(
                holder
            )

            self.items[
                screen_name
            ] = button

    def navigate(
        self,
        screen_name,
    ):
        app = App.get_running_app()

        if (
            screen_name == "remote"
            and not app.lg.connected
        ):
            app.toast(
                "Connect to your TV first."
            )
            return

        app.navigate(
            screen_name
        )


# ============================================================
# Screens
# ============================================================

class BaseScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        with self.canvas.before:
            self._background_color = Color(
                *Theme.get("background")
            )

            self._background = Rectangle(
                pos=self.pos,
                size=self.size,
            )

        self.bind(
            pos=self._sync_background,
            size=self._sync_background,
        )

    def _sync_background(
        self,
        *_,
    ):
        self._background.pos = self.pos
        self._background.size = self.size


class SplashScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = FloatLayout()
        self.add_widget(root)

        self.logo = Widget(
            size_hint=(None, None),
            size=(
                dp(112),
                dp(112),
            ),
            pos_hint={
                "center_x": 0.5,
                "center_y": 0.58,
            },
            opacity=0,
        )

        with self.logo.canvas:
            self._logo_glow_color = Color(
                *Theme.get(
                    "accent",
                    0.08,
                )
            )

            self._logo_glow = Ellipse()

            self._logo_surface_color = Color(
                *Theme.get("elevated")
            )

            self._logo_surface = Ellipse()

            self._logo_ring_color = Color(
                *Theme.get(
                    "accent",
                    0.65,
                )
            )

            self._logo_ring = Line(
                width=dp(2),
            )

            self._power_line = Line(
                width=dp(3),
                cap="round",
            )

        self.logo.bind(
            pos=self._sync_logo,
            size=self._sync_logo,
        )

        root.add_widget(
            self.logo
        )

        self.title = AppLabel(
            text="FAHD",
            font_size=sp(24),
            bold=True,
            halign="center",
            size_hint=(
                0.8,
                None,
            ),
            height=dp(42),
            pos_hint={
                "center_x": 0.5,
                "center_y": 0.41,
            },
            opacity=0,
        )

        root.add_widget(
            self.title
        )

        self.subtitle = AppLabel(
            text="Preparing your remote...",
            color=Theme.get("muted"),
            font_size=sp(12),
            halign="center",
            size_hint=(
                0.8,
                None,
            ),
            height=dp(30),
            pos_hint={
                "center_x": 0.5,
                "center_y": 0.36,
            },
            opacity=0,
        )

        root.add_widget(
            self.subtitle
        )

    def _sync_logo(self, *_):
        x = self.logo.x
        y = self.logo.y
        w = self.logo.width
        h = self.logo.height

        self._logo_glow.pos = (
            x - dp(9),
            y - dp(9),
        )

        self._logo_glow.size = (
            w + dp(18),
            h + dp(18),
        )

        self._logo_surface.pos = (
            x + dp(10),
            y + dp(10),
        )

        self._logo_surface.size = (
            w - dp(20),
            h - dp(20),
        )

        self._logo_ring.circle = (
            x + w / 2,
            y + h / 2,
            w * 0.31,
            -45,
            225,
        )

        self._power_line.points = [
            x + w / 2,
            y + h * 0.52,
            x + w / 2,
            y + h * 0.72,
        ]

    def begin(self):
        self.logo.opacity = 0
        self.title.opacity = 0
        self.subtitle.opacity = 0

        Animation(
            opacity=1,
            duration=0.38,
            t="out_quad",
        ).start(
            self.logo
        )

        Clock.schedule_once(
            lambda dt:
                Animation(
                    opacity=1,
                    duration=0.30,
                    t="out_quad",
                ).start(
                    self.title
                ),
            0.18,
        )

        Clock.schedule_once(
            lambda dt:
                Animation(
                    opacity=1,
                    duration=0.28,
                    t="out_quad",
                ).start(
                    self.subtitle
                ),
            0.30,
        )

        Clock.schedule_once(
            self.finish,
            1.20,
        )

    def finish(
        self,
        dt,
    ):
        app = App.get_running_app()

        if app.settings_store.get(
            "user_name",
            "",
        ).strip():
            app.navigate("home")
        else:
            app.navigate("welcome")


class WelcomeScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=[
                dp(24),
                dp(50),
                dp(24),
                dp(34),
            ],
            spacing=dp(12),
        )

        self.add_widget(root)

        root.add_widget(
            Widget(
                size_hint_y=0.65
            )
        )

        eyebrow = AppLabel(
            text="FAHD REMOTE",
            color=Theme.get("accent"),
            font_size=sp(11),
            bold=True,
            size_hint_y=None,
            height=dp(26),
        )

        root.add_widget(
            eyebrow
        )

        self.heading = AppLabel(
            text="Welcome",
            font_size=sp(31),
            bold=True,
            size_hint_y=None,
            height=dp(52),
        )

        root.add_widget(
            self.heading
        )

        self.copy = AppLabel(
            text="A calm, fast remote for your LG webOS TV.",
            color=Theme.get("secondary"),
            font_size=sp(14),
            size_hint_y=None,
            height=dp(52),
        )

        root.add_widget(
            self.copy
        )

        root.add_widget(
            Widget(
                size_hint_y=None,
                height=dp(10),
            )
        )

        self.name_input = PremiumInput(
            hint_text="Your name",
        )

        root.add_widget(
            self.name_input
        )

        self.continue_button = PremiumButton(
            text="CONTINUE",
            accent="accent",
            text_color_name="background",
            size_hint_y=None,
            height=dp(55),
            callback=self.continue_pressed,
        )

        root.add_widget(
            self.continue_button
        )

        root.add_widget(
            Widget(
                size_hint_y=1
            )
        )

    def on_pre_enter(self, *_):
        widgets = [
            self.heading,
            self.copy,
            self.name_input,
            self.continue_button,
        ]

        for widget in widgets:
            widget.opacity = 0

        for index, widget in enumerate(
            widgets
        ):
            Clock.schedule_once(
                lambda dt, w=widget:
                    Animation(
                        opacity=1,
                        duration=0.26,
                        t="out_quad",
                    ).start(w),
                0.06 * index,
            )

        Clock.schedule_once(
            self._focus_name_input,
            0.35,
        )

    def _focus_name_input(self, dt=0):
        if self.name_input:
            self.name_input.focus = True

    def continue_pressed(
        self,
        *_,
    ):
        name = self.name_input.text.strip()

        if not name:
            App.get_running_app().toast(
                "Enter your name to continue."
            )
            return

        app = App.get_running_app()

        app.settings_store.set(
            "user_name",
            name,
        )

        app.home.refresh_user()

        app.navigate(
            "home"
        )


class TVConnectionCard(Surface):
    def __init__(self, **kwargs):
        super().__init__(
            surface="surface",
            radius=24,
            orientation="vertical",
            padding=dp(17),
            spacing=dp(10),
            **kwargs,
        )

        self.size_hint_y = None
        self.height = dp(174)

        top = BoxLayout(
            spacing=dp(10),
            size_hint_y=None,
            height=dp(58),
        )

        self.indicator = StatusIndicator(
            size_hint=(None, None),
            size=(
                dp(48),
                dp(48),
            ),
        )

        top.add_widget(
            self.indicator
        )

        labels = BoxLayout(
            orientation="vertical"
        )

        self.name_label = AppLabel(
            text="LG webOS TV",
            font_size=sp(17),
            bold=True,
        )

        labels.add_widget(
            self.name_label
        )

        self.status_label = AppLabel(
            text="Disconnected",
            color=Theme.get("muted"),
            font_size=sp(12),
        )

        labels.add_widget(
            self.status_label
        )

        top.add_widget(
            labels
        )

        self.add_widget(
            top
        )

        self.search_button = PremiumButton(
            text="SEARCH FOR TV",
            accent="elevated",
            size_hint_y=None,
            height=dp(52),
            callback=lambda button:
                App.get_running_app().start_discovery(),
        )

        self.add_widget(
            self.search_button
        )

    def update(
        self,
        state,
        message="",
    ):
        self.indicator.state = state

        if state == "connected":
            app = App.get_running_app()

            self.name_label.text = (
                app.lg.tv_name
                or "LG webOS TV"
            )

            self.status_label.text = "Connected"
            self.status_label.color = Theme.get(
                "green"
            )

            self.search_button.text = "CHANGE TV"

        elif state == "connecting":
            self.status_label.text = (
                "Connecting..."
            )

            self.status_label.color = Theme.get(
                "secondary"
            )

        elif state == "searching":
            self.status_label.text = (
                "Searching..."
            )

            self.status_label.color = Theme.get(
                "accent"
            )

        elif state == "error":
            self.status_label.text = (
                "Connection failed"
            )

            self.status_label.color = Theme.get(
                "red"
            )

        else:
            self.status_label.text = (
                "Disconnected"
            )

            self.status_label.color = Theme.get(
                "muted"
            )

            self.search_button.text = (
                "SEARCH FOR TV"
            )


class HomeScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=[
                dp(17),
                dp(22),
                dp(17),
                dp(14),
            ],
            spacing=dp(13),
        )

        self.add_widget(root)

        self.brand = AppLabel(
            text="FAHD / LG",
            color=Theme.get("muted"),
            font_size=sp(10),
            bold=True,
            size_hint_y=None,
            height=dp(24),
        )

        root.add_widget(
            self.brand
        )

        self.greeting = AppLabel(
            text="Hello",
            font_size=sp(26),
            bold=True,
            size_hint_y=None,
            height=dp(48),
        )

        root.add_widget(
            self.greeting
        )

        self.tv_card = TVConnectionCard()

        root.add_widget(
            self.tv_card
        )

        quick = Surface(
            surface="surface",
            radius=24,
            orientation="vertical",
            padding=dp(16),
            spacing=dp(9),
            size_hint_y=None,
            height=dp(172),
        )

        quick.add_widget(
            AppLabel(
                text="QUICK ACCESS",
                color=Theme.get("muted"),
                font_size=sp(10),
                bold=True,
                size_hint_y=None,
                height=dp(25),
            )
        )

        buttons = BoxLayout(
            spacing=dp(9),
        )

        buttons.add_widget(
            PremiumButton(
                text="REMOTE",
                accent="elevated",
                callback=lambda button:
                    self.open_remote(),
            )
        )

        buttons.add_widget(
            PremiumButton(
                text="SETTINGS",
                callback=lambda button:
                    App.get_running_app().navigate(
                        "settings"
                    ),
            )
        )

        quick.add_widget(
            buttons
        )

        root.add_widget(
            quick
        )

        root.add_widget(
            Widget()
        )

        self.nav = BottomNavigation(
            active="home"
        )

        root.add_widget(
            self.nav
        )

    def refresh_user(self):
        app = App.get_running_app()

        name = app.settings_store.get(
            "user_name",
            "",
        ).strip()

        self.greeting.text = (
            f"Hello, {name}"
            if name
            else "Hello"
        )

    def open_remote(self):
        app = App.get_running_app()

        if not app.lg.connected:
            app.toast(
                "Connect to your TV first."
            )
            return

        app.navigate(
            "remote"
        )

    def on_pre_enter(self, *_):
        self.refresh_user()

        widgets = [
            self.brand,
            self.greeting,
            self.tv_card,
            self.nav,
        ]

        for widget in widgets:
            widget.opacity = 0

        for index, widget in enumerate(
            widgets
        ):
            Clock.schedule_once(
                lambda dt, w=widget:
                    Animation(
                        opacity=1,
                        duration=0.25,
                        t="out_quad",
                    ).start(w),
                index * 0.055,
            )


class DeviceCard(Surface):
    def __init__(
        self,
        device,
        **kwargs,
    ):
        super().__init__(
            surface="surface",
            radius=19,
            orientation="horizontal",
            padding=dp(13),
            spacing=dp(8),
            size_hint_y=None,
            height=dp(82),
            **kwargs,
        )

        self.device = device

        labels = BoxLayout(
            orientation="vertical"
        )

        labels.add_widget(
            AppLabel(
                text=device.get(
                    "name",
                    "LG webOS TV",
                ),
                font_size=sp(14),
                bold=True,
            )
        )

        labels.add_widget(
            AppLabel(
                text=device.get(
                    "host",
                    "",
                ),
                color=Theme.get("muted"),
                font_size=sp(11),
            )
        )

        self.add_widget(
            labels
        )

        connect = PremiumButton(
            text="CONNECT",
            accent="elevated",
            size_hint_x=None,
            width=dp(98),
            callback=self.connect,
        )

        self.add_widget(
            connect
        )

    def connect(
        self,
        *_,
    ):
        app = App.get_running_app()

        app.lg.connect_async(
            self.device["host"],
            self.device.get("name"),
        )

        app.navigate(
            "home"
        )


class DiscoveryScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=[
                dp(17),
                dp(22),
                dp(17),
                dp(20),
            ],
            spacing=dp(12),
        )

        self.add_widget(
            root
        )

        header = BoxLayout(
            size_hint_y=None,
            height=dp(52),
            spacing=dp(10),
        )

        header.add_widget(
            PremiumButton(
                text="BACK",
                size_hint_x=None,
                width=dp(86),
                callback=lambda button:
                    App.get_running_app().navigate(
                        "home"
                    ),
            )
        )

        header.add_widget(
            AppLabel(
                text="TV DEVICES",
                font_size=sp(20),
                bold=True,
            )
        )

        root.add_widget(
            header
        )

        status = Surface(
            surface="surface",
            radius=18,
            orientation="horizontal",
            size_hint_y=None,
            height=dp(62),
            padding=[
                dp(12),
                dp(7),
            ],
            spacing=dp(8),
        )

        self.loader = LoadingRing(
            size_hint=(None, None),
            size=(
                dp(44),
                dp(44),
            ),
        )

        status.add_widget(
            self.loader
        )

        self.status_label = AppLabel(
            text="Searching your local network...",
            color=Theme.get("secondary"),
            font_size=sp(12),
        )

        status.add_widget(
            self.status_label
        )

        root.add_widget(
            status
        )

        scroll = ScrollView(
            do_scroll_x=False,
        )

        self.results = BoxLayout(
            orientation="vertical",
            spacing=dp(9),
            size_hint_y=None,
        )

        self.results.bind(
            minimum_height=self.results.setter(
                "height"
            )
        )

        scroll.add_widget(
            self.results
        )

        root.add_widget(
            scroll
        )

        root.add_widget(
            PremiumButton(
                text="SEARCH AGAIN",
                accent="elevated",
                size_hint_y=None,
                height=dp(53),
                callback=lambda button:
                    App.get_running_app().start_discovery(),
            )
        )

    def start_search_ui(self):
        self.results.clear_widgets()

        self.status_label.text = (
            "Searching your local network..."
        )

        self.status_label.color = Theme.get(
            "secondary"
        )

        self.loader.opacity = 1
        self.loader.start()

    def display_results(
        self,
        devices,
    ):
        self.loader.stop()

        Animation(
            opacity=0,
            duration=0.18,
        ).start(
            self.loader
        )

        self.results.clear_widgets()

        if not devices:
            self.status_label.text = (
                "No LG webOS TVs found."
            )

            self.status_label.color = Theme.get(
                "muted"
            )

            self.status_label.opacity = 0

            Animation(
                opacity=1,
                duration=0.28,
                t="out_quad",
            ).start(
                self.status_label
            )

            return

        self.status_label.text = (
            f"{len(devices)} TV"
            + (
                "" if len(devices) == 1
                else "s"
            )
            + " found"
        )

        for index, device in enumerate(
            devices
        ):
            card = DeviceCard(
                device
            )

            card.opacity = 0

            self.results.add_widget(
                card
            )

            Clock.schedule_once(
                lambda dt, widget=card:
                    Animation(
                        opacity=1,
                        duration=0.25,
                        t="out_quad",
                    ).start(widget),
                index * 0.065,
            )
class RemoteScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=[
                dp(15),
                dp(18),
                dp(15),
                dp(12),
            ],
            spacing=dp(10),
        )

        self.add_widget(root)

        header = BoxLayout(
            size_hint_y=None,
            height=dp(48),
            spacing=dp(9),
        )

        self.heading = AppLabel(
            text="REMOTE",
            font_size=sp(21),
            bold=True,
        )

        header.add_widget(
            self.heading
        )

        self.power_button = PremiumButton(
            text="POWER",
            accent="red",
            size_hint_x=None,
            width=dp(100),
            callback=self.power_pressed,
        )

        header.add_widget(
            self.power_button
        )

        root.add_widget(
            header
        )

        self.touchpad = TouchPad(
            size_hint_y=None,
            height=dp(178),
        )

        root.add_widget(
            self.touchpad
        )

        control_row = BoxLayout(
            size_hint_y=None,
            height=dp(188),
            spacing=dp(10),
        )

        self.dpad = DPad()

        control_row.add_widget(
            self.dpad
        )

        volume = Surface(
            surface="surface",
            radius=20,
            orientation="vertical",
            size_hint_x=None,
            width=dp(91),
            padding=dp(7),
            spacing=dp(7),
        )

        volume.add_widget(
            PremiumButton(
                text="VOL +",
                callback=lambda button:
                    App.get_running_app().lg.volume_up(),
            )
        )

        volume.add_widget(
            PremiumButton(
                text="VOL -",
                callback=lambda button:
                    App.get_running_app().lg.volume_down(),
            )
        )

        volume.add_widget(
            PremiumButton(
                text="MUTE",
                callback=lambda button:
                    App.get_running_app().lg.toggle_mute(),
            )
        )

        control_row.add_widget(
            volume
        )

        root.add_widget(
            control_row
        )

        media = BoxLayout(
            size_hint_y=None,
            height=dp(52),
            spacing=dp(7),
        )

        commands = [
            (
                "BACK",
                "BACK",
            ),
            (
                "HOME",
                "HOME",
            ),
            (
                "PLAY",
                "PLAY",
            ),
        ]

        for title, command in commands:
            media.add_widget(
                PremiumButton(
                    text=title,
                    callback=lambda button, c=command:
                        App.get_running_app().lg.button(
                            c
                        ),
                )
            )

        root.add_widget(
            media
        )

        root.add_widget(
            Widget(
                size_hint_y=0.2
            )
        )

        self.nav = BottomNavigation(
            active="remote"
        )

        root.add_widget(
            self.nav
        )

    def on_pre_enter(
        self,
        *_,
    ):
        app = App.get_running_app()

        if not app.lg.connected:
            Clock.schedule_once(
                lambda dt:
                    app.navigate(
                        "home"
                    ),
                0,
            )

            return

        app.lg.ensure_pointer_async()

        widgets = [
            self.heading,
            self.touchpad,
            self.dpad,
            self.nav,
        ]

        for widget in widgets:
            widget.opacity = 0

        for index, widget in enumerate(
            widgets
        ):
            Clock.schedule_once(
                lambda dt, w=widget:
                    Animation(
                        opacity=1,
                        duration=0.24,
                        t="out_quad",
                    ).start(w),
                index * 0.055,
            )

    def power_pressed(
        self,
        *_,
    ):
        app = App.get_running_app()

        if not app.lg.connected:
            app.toast(
                "TV is not connected."
            )
            return

        self.power_button.disabled = True
        self.power_button.text = "SENDING..."

        app.lg.power_off(
            success=self._power_success,
            failure=self._power_failure,
        )

    def _power_success(
        self,
        payload,
    ):
        self.power_button.disabled = False
        self.power_button.text = "SENT"

        App.get_running_app().toast(
            "Power command sent."
        )

        Clock.schedule_once(
            lambda dt:
                setattr(
                    self.power_button,
                    "text",
                    "POWER",
                ),
            1.0,
        )

    def _power_failure(
        self,
        error,
    ):
        self.power_button.disabled = False
        self.power_button.text = "POWER"

        App.get_running_app().toast(
            "Could not send the power command."
        )


class SettingsScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(
            orientation="vertical",
            padding=[
                dp(17),
                dp(22),
                dp(17),
                dp(14),
            ],
            spacing=dp(11),
        )

        self.add_widget(
            root
        )

        root.add_widget(
            AppLabel(
                text="SETTINGS",
                font_size=sp(23),
                bold=True,
                size_hint_y=None,
                height=dp(50),
            )
        )

        profile = Surface(
            surface="surface",
            radius=22,
            orientation="vertical",
            padding=dp(15),
            spacing=dp(8),
            size_hint_y=None,
            height=dp(167),
        )

        profile.add_widget(
            AppLabel(
                text="PROFILE",
                color=Theme.get("muted"),
                font_size=sp(10),
                bold=True,
                size_hint_y=None,
                height=dp(25),
            )
        )

        self.name_input = PremiumInput(
            hint_text="Your name",
        )

        profile.add_widget(
            self.name_input
        )

        profile.add_widget(
            PremiumButton(
                text="SAVE NAME",
                accent="elevated",
                size_hint_y=None,
                height=dp(48),
                callback=self.save_name,
            )
        )

        root.add_widget(
            profile
        )

        tv = Surface(
            surface="surface",
            radius=22,
            orientation="vertical",
            padding=dp(15),
            spacing=dp(8),
            size_hint_y=None,
            height=dp(150),
        )

        tv.add_widget(
            AppLabel(
                text="TELEVISION",
                color=Theme.get("muted"),
                font_size=sp(10),
                bold=True,
                size_hint_y=None,
                height=dp(25),
            )
        )

        self.tv_status = AppLabel(
            text="No TV connected",
            color=Theme.get("secondary"),
            font_size=sp(13),
            size_hint_y=None,
            height=dp(31),
        )

        tv.add_widget(
            self.tv_status
        )

        tv.add_widget(
            PremiumButton(
                text="FIND A TV",
                size_hint_y=None,
                height=dp(48),
                callback=lambda button:
                    App.get_running_app().start_discovery(),
            )
        )

        root.add_widget(
            tv
        )

        info = Surface(
            surface="surface",
            radius=22,
            orientation="vertical",
            padding=dp(15),
            spacing=dp(2),
            size_hint_y=None,
            height=dp(102),
        )

        info.add_widget(
            AppLabel(
                text="FAHD REMOTE",
                font_size=sp(13),
                bold=True,
            )
        )

        info.add_widget(
            AppLabel(
                text="LG webOS • Local network control",
                color=Theme.get("muted"),
                font_size=sp(11),
            )
        )

        root.add_widget(
            info
        )

        root.add_widget(
            Widget()
        )

        self.nav = BottomNavigation(
            active="settings"
        )

        root.add_widget(
            self.nav
        )

    def on_pre_enter(
        self,
        *_,
    ):
        app = App.get_running_app()

        self.name_input.text = (
            app.settings_store.get(
                "user_name",
                "",
            )
        )

        if app.lg.connected:
            self.tv_status.text = (
                app.lg.tv_name
                or "LG webOS TV"
            )

            self.tv_status.color = Theme.get(
                "green"
            )
        else:
            self.tv_status.text = (
                "No TV connected"
            )

            self.tv_status.color = Theme.get(
                "secondary"
            )

    def save_name(
        self,
        *_,
    ):
        value = self.name_input.text.strip()

        if not value:
            App.get_running_app().toast(
                "Name cannot be empty."
            )
            return

        app = App.get_running_app()

        app.settings_store.set(
            "user_name",
            value,
        )

        app.home.refresh_user()

        app.toast(
            "Name saved."
        )


# ============================================================
# Toast
# ============================================================

class ToastLayer(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.opacity = 0
        self.disabled = True

        self.card = Surface(
            surface="elevated",
            radius=18,
            orientation="horizontal",
            padding=[
                dp(16),
                dp(7),
            ],
            size_hint=(
                0.90,
                None,
            ),
            height=dp(56),
            pos_hint={
                "center_x": 0.5,
                "y": 0.035,
            },
        )

        self.label = AppLabel(
            text="",
            font_size=sp(12),
            halign="center",
        )

        self.card.add_widget(
            self.label
        )

        self.add_widget(
            self.card
        )

        self._hide_event = None

    def on_touch_down(self, touch):
        # Toast is visual only. Never block controls behind it.
        return False

    def on_touch_move(self, touch):
        return False

    def on_touch_up(self, touch):
        return False

    def show(
        self,
        message,
    ):
        if self._hide_event:
            self._hide_event.cancel()

        self.label.text = str(
            message
        )

        Animation.cancel_all(
            self
        )

        self.opacity = 0

        Animation(
            opacity=1,
            duration=0.16,
            t="out_quad",
        ).start(self)

        self._hide_event = (
            Clock.schedule_once(
                self.hide,
                2.35,
            )
        )

    def hide(
        self,
        dt,
    ):
        self._hide_event = None

        Animation(
            opacity=0,
            duration=0.22,
            t="out_quad",
        ).start(self)


# ============================================================
# Root
# ============================================================

class RootWidget(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.manager = ScreenManager(
            transition=SlideTransition(
                duration=0.20,
            )
        )

        self.add_widget(
            self.manager
        )

        self.toast_layer = ToastLayer()

        self.add_widget(
            self.toast_layer
        )


# ============================================================
# Application
# ============================================================

class AetherRemoteApp(App):
    def build(self):
        self.title = "Fahd LG Remote"

        self.settings_store = SettingsStore()

        self.lg = LGWebOSClient(
            settings=self.settings_store,
            state_callback=self.on_tv_state,
        )

        root = RootWidget()

        self.root_widget = root

        manager = root.manager

        self.splash = SplashScreen(
            name="splash"
        )

        self.welcome = WelcomeScreen(
            name="welcome"
        )

        self.home = HomeScreen(
            name="home"
        )

        self.discovery = DiscoveryScreen(
            name="discovery"
        )

        self.remote = RemoteScreen(
            name="remote"
        )

        self.settings_screen = SettingsScreen(
            name="settings"
        )

        for screen in (
            self.splash,
            self.welcome,
            self.home,
            self.discovery,
            self.remote,
            self.settings_screen,
        ):
            manager.add_widget(
                screen
            )

        manager.current = "splash"

        Clock.schedule_once(
            lambda dt:
                self.splash.begin(),
            0.12,
        )

        # Reconnect in the background only after the UI is alive.
        last_tv = self.settings_store.get(
            "last_tv"
        )

        if (
            isinstance(last_tv, dict)
            and last_tv.get("host")
        ):
            Clock.schedule_once(
                lambda dt:
                    self.lg.connect_async(
                        last_tv["host"],
                        last_tv.get("name"),
                    ),
                1.55,
            )

        return root

    def navigate(
        self,
        screen_name,
    ):
        manager = self.root_widget.manager

        if screen_name not in manager.screen_names:
            return

        old = manager.current

        if old == screen_name:
            return

        order = {
            "welcome": 0,
            "home": 1,
            "remote": 2,
            "settings": 2,
            "discovery": 2,
        }

        manager.transition.direction = (
            "left"
            if order.get(
                screen_name,
                1,
            ) >= order.get(
                old,
                1,
            )
            else "right"
        )

        manager.current = screen_name

    def toast(
        self,
        message,
    ):
        if self.root_widget:
            self.root_widget.toast_layer.show(
                message
            )

    def start_discovery(self):
        self.navigate(
            "discovery"
        )

        self.discovery.start_search_ui()

        self.home.tv_card.update(
            "searching"
        )

        def worker():
            try:
                devices = LGWebOSClient.discover(
                    timeout=3.5
                )

            except Exception:
                devices = []

            ui(
                self.discovery_finished,
                devices,
            )

        threading.Thread(
            target=worker,
            daemon=True,
            name="lg-discovery",
        ).start()

    def discovery_finished(
        self,
        devices,
    ):
        self.discovery.display_results(
            devices
        )

        if not self.lg.connected:
            self.home.tv_card.update(
                "disconnected"
            )

    def on_tv_state(
        self,
        state,
        message,
    ):
        self.home.tv_card.update(
            state,
            message,
        )

        if state == "connected":
            self.toast(
                "TV connected."
            )

        elif state == "connecting":
            # Pairing prompt may appear on the physical TV.
            pass

        elif state == "error":
            self.toast(
                message
            )

        elif state == "disconnected":
            pass

    def on_pause(self):
        # Android can pause the Activity without actually terminating it.
        return True

    def on_stop(self):
        try:
            self.lg.disconnect(
                emit=False
            )
        except Exception:
            pass


if __name__ == "__main__":
    AetherRemoteApp().run()