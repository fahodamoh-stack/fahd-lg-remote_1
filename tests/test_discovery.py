import socket

import pytest

from main import (
    DEFAULT_CAPABILITIES,
    TVDevice,
    TVDiscovery,
)


def lg_packet(
    usn="uuid:abc-123::urn:lge-com:service:webos-second-screen:1",
    server="Linux/3.0 UPnP/1.0 LG WebOS",
):
    return (
        "HTTP/1.1 200 OK\r\n"
        f"ST: urn:lge-com:service:webos-second-screen:1\r\n"
        f"USN: {usn}\r\n"
        f"SERVER: {server}\r\n"
        "LOCATION: http://192.168.1.20:3000/\r\n"
        "FRIENDLYNAME: Living Room TV\r\n"
        "MANUFACTURER: LG Electronics\r\n"
        "MODELNAME: OLED55\r\n"
        "\r\n"
    ).encode("utf-8")


def test_ssdp_parsing():
    headers = TVDiscovery.parse_ssdp_response(lg_packet())

    assert headers["friendlyname"] == "Living Room TV"
    assert headers["manufacturer"] == "LG Electronics"
    assert headers["modelname"] == "OLED55"


def test_ssdp_device_creation():
    headers = TVDiscovery.parse_ssdp_response(lg_packet())
    device = TVDiscovery.device_from_ssdp(
        headers,
        "192.168.1.20",
    )

    assert device is not None
    assert device.name == "Living Room TV"
    assert device.ip == "192.168.1.20"
    assert device.manufacturer == "LG Electronics"
    assert device.model == "OLED55"
    assert device.protocol == "lg-webos-ssap"


def test_malformed_ssdp_is_rejected():
    with pytest.raises(ValueError):
        TVDiscovery.parse_ssdp_response(
            b"garbage without status or headers"
        )


def test_malformed_header_line_is_ignored():
    packet = (
        b"HTTP/1.1 200 OK\r\n"
        b"BROKEN HEADER\r\n"
        b"SERVER: LG webOS\r\n\r\n"
    )

    headers = TVDiscovery.parse_ssdp_response(packet)

    assert headers["server"] == "LG webOS"
    assert "broken header" not in headers


def test_unsupported_device_is_filtered():
    packet = (
        b"HTTP/1.1 200 OK\r\n"
        b"SERVER: Generic UPnP Device\r\n"
        b"ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
        b"USN: uuid:not-lg\r\n\r\n"
    )

    headers = TVDiscovery.parse_ssdp_response(packet)

    assert (
        TVDiscovery.device_from_ssdp(
            headers,
            "192.168.1.50",
        )
        is None
    )


def test_duplicate_removal_by_device_id():
    first = TVDevice(
        name="TV",
        ip="192.168.1.2",
        device_id="same-id",
        manufacturer="LG",
    )
    second = TVDevice(
        name="TV duplicate",
        ip="192.168.1.3",
        device_id="same-id",
        manufacturer="LG",
    )

    result = TVDiscovery.deduplicate(
        [first, second]
    )

    assert len(result) == 1


def test_duplicate_removal_by_ip_manufacturer_protocol():
    first = TVDevice(
        name="TV",
        ip="192.168.1.2",
        manufacturer="LG",
        protocol="lg-webos-ssap",
    )
    second = TVDevice(
        name="TV duplicate",
        ip="192.168.1.2",
        manufacturer="LG",
        protocol="lg-webos-ssap",
    )

    result = TVDiscovery.deduplicate(
        [first, second]
    )

    assert len(result) == 1


def test_availability_is_preserved():
    first = TVDevice(
        name="TV",
        ip="192.168.1.4",
        manufacturer="LG",
        availability=False,
    )
    second = TVDevice(
        name="TV",
        ip="192.168.1.4",
        manufacturer="LG",
        availability=True,
    )

    result = TVDiscovery.deduplicate(
        [first, second]
    )

    assert result[0].availability is True


class DiscoverySocket:
    def __init__(self, packets):
        self.packets = list(packets)
        self.sent = []
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def setsockopt(self, *args):
        self.socket_options = args

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recvfrom(self, size):
        if self.packets:
            return self.packets.pop(0)
        raise socket.timeout()

    def close(self):
        self.closed = True


def test_discovery_without_real_network(monkeypatch):
    sock = DiscoverySocket(
        [
            (
                lg_packet(),
                ("192.168.1.20", 1900),
            )
        ]
    )

    discovery = TVDiscovery(
        socket_factory=lambda *args: sock
    )

    monkeypatch.setattr(
        TVDiscovery,
        "probe_lg",
        classmethod(
            lambda cls, ip, ports=(3001, 3000), timeout=0.3:
            True
        ),
    )
    monkeypatch.setattr(
        TVDiscovery,
        "tcp_available",
        staticmethod(
            lambda ip, port, timeout=0.3:
            port == 3001
        ),
    )

    result = discovery.discover(
        timeout=0.05,
        probe=True,
    )

    assert len(result) == 1
    assert result[0].name == "Living Room TV"
    assert result[0].availability is True
    assert result[0].port == 3001

    request, destination = sock.sent[0]
    assert b"M-SEARCH * HTTP/1.1" in request
    assert destination == (
        "239.255.255.250",
        1900,
    )
    assert sock.closed is True


def test_default_capabilities_do_not_claim_support():
    headers = TVDiscovery.parse_ssdp_response(lg_packet())
    device = TVDiscovery.device_from_ssdp(
        headers,
        "192.168.1.20",
    )

    assert device is not None
    assert device.capabilities == DEFAULT_CAPABILITIES


def test_mdns_is_not_claimed_as_lg_discovery_protocol():
    discovery = TVDiscovery()

    assert not hasattr(discovery, "discover_fake_mdns")