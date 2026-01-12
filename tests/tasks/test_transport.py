"""Tests for transport layer."""


from exobrain.tasks.transport import TransportFactory, TransportType


def test_platform_detection():
    """Test platform transport detection."""
    detected = TransportFactory.detect_platform_transport()
    assert detected in [TransportType.UNIX, TransportType.PIPE, TransportType.HTTP]


def test_transport_availability():
    """Test transport availability checks."""
    # Unix should be available on Linux/macOS
    unix_available = TransportFactory.is_transport_available(TransportType.UNIX)
    assert isinstance(unix_available, bool)

    # HTTP availability depends on aiohttp
    http_available = TransportFactory.is_transport_available(TransportType.HTTP)
    assert isinstance(http_available, bool)


def test_create_unix_transport():
    """Test creating Unix socket transport."""
    transport = TransportFactory.create_transport(
        TransportType.UNIX, {"socket_path": "/tmp/test.sock"}
    )
    assert transport is not None
    assert not transport.is_connected()


def test_get_default_config():
    """Test getting default transport config."""
    config = TransportFactory.get_default_config(TransportType.UNIX)
    assert isinstance(config, dict)
    assert "socket_path" in config
