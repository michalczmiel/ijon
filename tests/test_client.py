from pytest_httpserver import HTTPServer

from ijon import OpenAICompatibleClient


def test_posts_the_body_to_the_chat_completions_endpoint(httpserver: HTTPServer):
    answer = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
    httpserver.expect_request(
        "/v1/chat/completions", method="POST"
    ).respond_with_json(answer)

    client = OpenAICompatibleClient(httpserver.url_for(""))
    body = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
    result = client.chat_completions(body)

    assert result == answer
    request, _ = httpserver.log[0]
    assert request.get_json() == body
    assert request.headers["Content-Type"] == "application/json"


def test_sends_the_api_key_as_a_bearer_token(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json({})

    client = OpenAICompatibleClient(httpserver.url_for(""), api_key="sk-secret")
    client.chat_completions({"model": "test-model", "messages": []})

    request, _ = httpserver.log[0]
    assert request.headers["Authorization"] == "Bearer sk-secret"


def test_omits_authorization_without_an_api_key(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json({})

    client = OpenAICompatibleClient(httpserver.url_for(""))
    client.chat_completions({"model": "test-model", "messages": []})

    request, _ = httpserver.log[0]
    assert "Authorization" not in request.headers


def test_returns_none_on_http_error(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_data(
        "boom", status=500
    )

    client = OpenAICompatibleClient(httpserver.url_for(""))
    result = client.chat_completions({"model": "test-model", "messages": []})

    assert result is None
