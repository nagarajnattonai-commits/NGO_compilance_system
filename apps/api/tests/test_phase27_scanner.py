"""Phase 27 ClamAV adapter against a protocol-faithful fake clamd."""
import socket
import socketserver
import struct
import threading

import pytest

from app.malware_scanner import ClamAVScanner, scanner_from_environment
from app.production_security import validate_production_configuration

EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


class FakeClamd(socketserver.BaseRequestHandler):
    def handle(self):
        command = b""
        while not command.endswith(b"\0"):
            command += self.request.recv(1)
        if command == b"zPING\0":
            self.request.sendall(b"PONG\0")
            return
        assert command == b"zINSTREAM\0"
        received = b""
        while True:
            size = struct.unpack(">I", self._exact(4))[0]
            if size == 0:
                break
            received += self._exact(size)
        self.server.sizes.append(len(received))
        if self.server.mode == "error":
            self.request.sendall(b"INSTREAM size limit exceeded. ERROR\0")
        elif EICAR_MARKER in received or self.server.mode == "infected":
            self.request.sendall(b"stream: Eicar-Test-Signature FOUND\0")
        else:
            self.request.sendall(b"stream: OK\0")

    def _exact(self, size):
        data = b""
        while len(data) < size:
            data += self.request.recv(size - len(data))
        return data


@pytest.fixture
def clamd():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeClamd)
    server.mode, server.sizes = "ok", []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_clean_infected_and_chunked_streams(clamd):
    scanner = ClamAVScanner("127.0.0.1", clamd.server_address[1], timeout=5)
    assert scanner.ping() is True
    assert scanner.scan(b"%PDF-1.7 clean", "application/pdf") == "CLEAN"
    assert scanner.scan(b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + EICAR_MARKER + b"!$H+H*", "text/plain") == "QUARANTINED"
    large = b"a" * (64 * 1024 * 3 + 17)  # several INSTREAM chunks
    assert scanner.scan(large, "application/pdf") == "CLEAN" and clamd.sizes[-1] == len(large)


def test_scanner_errors_fail_closed(clamd):
    clamd.mode = "error"
    with pytest.raises(RuntimeError):
        ClamAVScanner("127.0.0.1", clamd.server_address[1], timeout=5).scan(b"data", "application/pdf")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        unused = probe.getsockname()[1]
    offline = ClamAVScanner("127.0.0.1", unused, timeout=1)
    assert offline.ping() is False
    with pytest.raises(OSError):
        offline.scan(b"data", "application/pdf")


def test_upload_is_scanned_through_the_existing_hook(clamd, monkeypatch):
    from test_documents import image_bytes, platform_client, upload_original
    monkeypatch.setenv("DOCUMENT_SCANNER", "clamav")
    monkeypatch.setenv("CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMAV_PORT", str(clamd.server_address[1]))
    monkeypatch.setenv("DOCUMENT_SCAN_REQUIRED", "true")
    with platform_client(monkeypatch) as client:
        clean = upload_original(client)
        assert clean.status_code == 201, clean.text
        assert clean.json()["file"]["scan_status"] == "SCANNED_CLEAN"
        clamd.mode = "infected"
        infected = upload_original(client, content=image_bytes("red"))
        assert infected.status_code == 201, infected.text
        assert infected.json()["file"]["scan_status"] == "QUARANTINED"
        clamd.mode = "error"
        assert upload_original(client, content=image_bytes("blue")).status_code == 503


def test_environment_configuration():
    assert scanner_from_environment({}) is None
    scanner = scanner_from_environment({"DOCUMENT_SCANNER": "clamav", "CLAMAV_HOST": "clamav", "CLAMAV_PORT": "3310"})
    assert isinstance(scanner, ClamAVScanner) and scanner.host == "clamav"
    for bad in ({"DOCUMENT_SCANNER": "other"}, {"DOCUMENT_SCANNER": "clamav"},
                {"DOCUMENT_SCANNER": "clamav", "CLAMAV_HOST": "h", "CLAMAV_PORT": "x"},
                {"DOCUMENT_SCANNER": "clamav", "CLAMAV_HOST": "h", "CLAMAV_PORT": "70000"}):
        with pytest.raises(RuntimeError):
            scanner_from_environment(bad)


def test_production_allows_required_scanning_once_an_adapter_is_configured():
    from test_phase25_production import production_values
    base = production_values() | {"DOCUMENT_SCAN_REQUIRED": "true"}
    with pytest.raises(RuntimeError):
        validate_production_configuration(base)
    validate_production_configuration(base | {"DOCUMENT_SCANNER": "clamav", "CLAMAV_HOST": "clamav"})
