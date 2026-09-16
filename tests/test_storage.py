import json
import os
from pathlib import Path

from main import (
    DEFAULT_CAPABILITIES,
    SettingsManager,
    TVDevice,
)


def make_settings(tmp_path):
    return SettingsManager(str(tmp_path))


def sample_tv():
    capabilities = dict(DEFAULT_CAPABILITIES)
    capabilities["pointer"] = True

    return TVDevice(
        name="Living Room",
        ip="192.168.1.25",
        port=3001,
        device_id="lg-device-1",
        manufacturer="LG",
        model="OLED",
        capabilities=capabilities,
    )


def test_defaults(tmp_path):
    settings = make_settings(tmp_path)

    assert settings.get("pointer_sensitivity") == 1.0
    assert settings.get("pointer_acceleration") == 0.12
    assert settings.get("auto_reconnect") is True
    assert settings.saved_tvs() == []


def test_save_and_load_setting(tmp_path):
    settings = make_settings(tmp_path)
    settings.set("pointer_sensitivity", 1.75)
    settings.set("language", "ar")

    loaded = make_settings(tmp_path)

    assert loaded.get("pointer_sensitivity") == 1.75
    assert loaded.get("language") == "ar"


def test_corrupted_json_falls_back_to_defaults(tmp_path):
    file = Path(tmp_path) / "settings.json"
    file.write_text(
        "{ definitely broken",
        encoding="utf-8",
    )

    settings = make_settings(tmp_path)

    assert settings.get("pointer_sensitivity") == 1.0
    assert settings.saved_tvs() == []


def test_save_tv(tmp_path):
    settings = make_settings(tmp_path)
    device = sample_tv()

    settings.save_tv(device)

    loaded = make_settings(tmp_path)
    saved = loaded.saved_tvs()

    assert len(saved) == 1
    assert saved[0].device_id == device.device_id
    assert saved[0].model == "OLED"
    assert saved[0].capabilities["pointer"] is True


def test_saving_same_tv_updates_instead_of_duplicates(tmp_path):
    settings = make_settings(tmp_path)
    device = sample_tv()

    settings.save_tv(device)

    updated = sample_tv()
    updated.name = "Updated Living Room"
    settings.save_tv(updated)

    saved = settings.saved_tvs()

    assert len(saved) == 1
    assert saved[0].name == "Updated Living Room"


def test_forget_tv(tmp_path):
    settings = make_settings(tmp_path)
    device = sample_tv()

    settings.save_tv(device)
    settings.set_client_key(device, "test-key")

    assert settings.get_client_key(device) == "test-key"

    settings.forget_tv(device.identity)

    assert settings.saved_tvs() == []
    assert settings.get_client_key(device) is None
    assert settings.get("selected_tv") == ""


def test_client_key_is_not_written_to_settings_json(tmp_path):
    settings = make_settings(tmp_path)
    device = sample_tv()

    settings.set_client_key(
        device,
        "a-sensitive-client-key",
    )
    settings.save_tv(device)

    content = (
        Path(tmp_path) / "settings.json"
    ).read_text(encoding="utf-8")

    assert "a-sensitive-client-key" not in content
    assert "client_key" not in content
    assert "client-key" not in content


def test_desktop_secret_fallback_file_created_privately(tmp_path):
    settings = make_settings(tmp_path)
    device = sample_tv()

    settings.set_client_key(device, "desktop-test-key")

    secret_file = (
        Path(tmp_path) / ".client_keys.json"
    )

    assert secret_file.exists()
    assert settings.get_client_key(device) == "desktop-test-key"

    if os.name != "nt":
        mode = secret_file.stat().st_mode & 0o777
        assert mode & 0o077 == 0


def test_migration_from_old_devices_key(tmp_path):
    old = {
        "version": 1,
        "pointer_sensitivity": 2.0,
        "devices": [
            sample_tv().to_dict()
        ],
    }

    file = Path(tmp_path) / "settings.json"
    file.write_text(
        json.dumps(old),
        encoding="utf-8",
    )

    settings = make_settings(tmp_path)

    assert settings.get("version") == SettingsManager.VERSION
    assert settings.get("pointer_sensitivity") == 2.0
    assert len(settings.saved_tvs()) == 1
    assert "devices" not in settings.data


def test_invalid_saved_tv_is_skipped(tmp_path):
    data = dict(SettingsManager.DEFAULTS)
    data["saved_tvs"] = [
        {"invalid": True},
        sample_tv().to_dict(),
    ]

    file = Path(tmp_path) / "settings.json"
    file.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    settings = make_settings(tmp_path)

    assert len(settings.saved_tvs()) == 1


def test_unknown_settings_survive_load(tmp_path):
    file = Path(tmp_path) / "settings.json"
    file.write_text(
        json.dumps(
            {
                "version": SettingsManager.VERSION,
                "future_option": "value",
            }
        ),
        encoding="utf-8",
    )

    settings = make_settings(tmp_path)

    assert settings.get("future_option") == "value"