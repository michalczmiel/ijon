from pytest_httpserver import HTTPServer

from ijon import HttpTransport

MAX_ATTEMPTS = 3
request = HttpTransport(
    request_max_attempts=MAX_ATTEMPTS, request_base_delay=1.0
).request


def test_request_retries_on_server_error(httpserver: HTTPServer):
    httpserver.expect_request("/x", method="POST").respond_with_data("boom", status=500)

    result = request(httpserver.url_for("/x"), {"Content-Type": "application/json"}, {})

    assert result is None
    assert len(httpserver.log) == MAX_ATTEMPTS


def test_request_retries_on_too_many_requests(httpserver: HTTPServer):
    httpserver.expect_request("/x", method="POST").respond_with_data(
        "slow down", status=429
    )

    result = request(httpserver.url_for("/x"), {"Content-Type": "application/json"}, {})

    assert result is None
    assert len(httpserver.log) == MAX_ATTEMPTS


def test_request_does_not_retry_on_client_error(httpserver: HTTPServer):
    httpserver.expect_request("/x", method="POST").respond_with_data("nope", status=400)

    result = request(httpserver.url_for("/x"), {"Content-Type": "application/json"}, {})

    assert result is None
    assert len(httpserver.log) == 1


def test_request_returns_data_after_a_retry(httpserver: HTTPServer):
    httpserver.expect_ordered_request("/x", method="POST").respond_with_data(
        "boom", status=500
    )
    httpserver.expect_ordered_request("/x", method="POST").respond_with_data("ok")

    result = request(httpserver.url_for("/x"), {"Content-Type": "application/json"}, {})

    assert result is not None
    data, _ = result
    assert data == "ok"
    assert len(httpserver.log) == 2
