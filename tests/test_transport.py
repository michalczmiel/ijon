import socket

import pytest
from pytest_httpserver import HTTPServer

from ijon import HttpTransport


def test_request_retries_on_server_error(
    httpserver: HTTPServer, transport: HttpTransport
):
    httpserver.expect_request("/x", method="POST").respond_with_data("boom", status=500)

    result = transport.request(
        httpserver.url_for("/x"), {"Content-Type": "application/json"}, {}
    )

    assert result is None
    assert len(httpserver.log) == transport.request_max_attempts


def test_request_retries_on_too_many_requests(
    httpserver: HTTPServer, transport: HttpTransport
):
    httpserver.expect_request("/x", method="POST").respond_with_data(
        "slow down", status=429
    )

    result = transport.request(
        httpserver.url_for("/x"), {"Content-Type": "application/json"}, {}
    )

    assert result is None
    assert len(httpserver.log) == transport.request_max_attempts


def test_request_does_not_retry_on_client_error(
    httpserver: HTTPServer, transport: HttpTransport
):
    httpserver.expect_request("/x", method="POST").respond_with_data("nope", status=400)

    result = transport.request(
        httpserver.url_for("/x"), {"Content-Type": "application/json"}, {}
    )

    assert result is None
    assert len(httpserver.log) == 1


def test_request_retries_on_timeout(
    monkeypatch: pytest.MonkeyPatch, transport: HttpTransport
):
    timeouts = []

    def time_out(_req, timeout=None):
        timeouts.append(timeout)
        raise socket.timeout("timed out")

    monkeypatch.setattr("urllib.request.urlopen", time_out)

    result = transport.request(
        "http://example.test/x", {"Content-Type": "application/json"}, {}
    )

    assert result is None
    # retried up to the limit, each attempt forwarding the configured timeout
    assert timeouts == [transport.timeout] * transport.request_max_attempts


def test_request_returns_data_after_a_retry(
    httpserver: HTTPServer, transport: HttpTransport
):
    httpserver.expect_ordered_request("/x", method="POST").respond_with_data(
        "boom", status=500
    )
    httpserver.expect_ordered_request("/x", method="POST").respond_with_data("ok")

    result = transport.request(
        httpserver.url_for("/x"), {"Content-Type": "application/json"}, {}
    )

    assert result is not None
    data, _ = result
    assert data == "ok"
    assert len(httpserver.log) == 2
