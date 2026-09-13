import threading
import time

from werkzeug.wrappers import Response

from conftest import completion_requests
from factories import assistant_message


def test_retries_on_server_error(ijon, httpserver):
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_data(
        "boom", status=500
    )

    result = ijon.run("hi", "--model", "test-model", env={"IJON_MAX_ATTEMPTS": "3"})

    assert result.returncode == 1
    assert len(completion_requests(httpserver)) == 3
    assert "giving up after 3 attempts" in result.stderr


def test_retries_on_too_many_requests(ijon, httpserver):
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_data(
        "slow down", status=429
    )

    result = ijon.run("hi", "--model", "test-model", env={"IJON_MAX_ATTEMPTS": "3"})

    assert result.returncode == 1
    assert len(completion_requests(httpserver)) == 3


def test_does_not_retry_on_client_error(ijon, httpserver):
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_data(
        "nope", status=400
    )

    result = ijon.run("hi", "--model", "test-model", env={"IJON_MAX_ATTEMPTS": "3"})

    assert result.returncode == 1
    assert len(completion_requests(httpserver)) == 1
    assert "HTTP 400" in result.stderr
    assert "nope" in result.stderr


def test_returns_data_after_a_retry(ijon, httpserver):
    httpserver.expect_ordered_request(
        "/v1/chat/completions", method="POST"
    ).respond_with_data("boom", status=500)
    httpserver.expect_ordered_request(
        "/v1/chat/completions", method="POST"
    ).respond_with_json(assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model")

    assert result.returncode == 0, result.stderr
    assert len(completion_requests(httpserver)) == 2
    assert "retrying in 0.0s (attempt 1/3)" in result.stderr


def test_retries_on_timeout(ijon, httpserver):
    release = threading.Event()

    def stall(_request) -> Response:
        release.wait(timeout=10)
        return Response("late")

    httpserver.expect_request("/v1/chat/completions").respond_with_handler(stall)

    try:
        result = ijon.run(
            "hi",
            "--model",
            "test-model",
            env={"IJON_HTTP_TIMEOUT": "1", "IJON_MAX_ATTEMPTS": "2"},
        )
    finally:
        # let the stalled handler threads finish so they don't leak into the next test
        release.set()
        for _ in range(50):
            if len(completion_requests(httpserver)) >= 2:
                break
            time.sleep(0.1)

    assert result.returncode == 1
    assert result.stderr.count("timed out after 1s") == 2
    assert "giving up after 2 attempts" in result.stderr


def test_unauthorized_explains_static_token_auth(ijon, httpserver):
    httpserver.expect_request("/v1/chat/completions").respond_with_data(
        "", status=401, headers={"WWW-Authenticate": "Bearer"}
    )

    result = ijon.run("hi", "--model", "test-model")

    assert result.returncode == 1
    assert len(completion_requests(httpserver)) == 1
    assert "static tokens" in result.stderr
