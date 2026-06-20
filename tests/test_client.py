from pytest_httpserver import HTTPServer

from ijon import OpenAICompatibleClient


def test_posts_the_body_to_the_chat_completions_endpoint(httpserver: HTTPServer):
    answer = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
    httpserver.expect_request(
        "/v1/chat/completions", method="POST"
    ).respond_with_json(answer)

    client = OpenAICompatibleClient(httpserver.url_for(""))
    messages = [{"role": "user", "content": "hi"}]
    result = client.chat_completions("test-model", messages)

    assert result == answer
    request, _ = httpserver.log[0]
    assert request.get_json() == {"model": "test-model", "messages": messages}
    assert request.headers["Content-Type"] == "application/json"


def test_sends_the_api_key_as_a_bearer_token(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json({})

    client = OpenAICompatibleClient(httpserver.url_for(""), api_key="sk-secret")
    client.chat_completions("test-model", [])

    request, _ = httpserver.log[0]
    assert request.headers["Authorization"] == "Bearer sk-secret"


def test_omits_authorization_without_an_api_key(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json({})

    client = OpenAICompatibleClient(httpserver.url_for(""))
    client.chat_completions("test-model", [])

    request, _ = httpserver.log[0]
    assert "Authorization" not in request.headers


def test_includes_tools_and_max_completion_tokens_when_set(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json({})

    client = OpenAICompatibleClient(httpserver.url_for(""))
    tools = [{"type": "function", "function": {"name": "t"}}]
    client.chat_completions("test-model", [], tools=tools, max_completion_tokens=256)

    request, _ = httpserver.log[0]
    assert request.get_json() == {
        "model": "test-model",
        "messages": [],
        "tools": tools,
        "max_completion_tokens": 256,
    }


def test_omits_tools_and_max_completion_tokens_when_unset(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json({})

    client = OpenAICompatibleClient(httpserver.url_for(""))
    client.chat_completions("test-model", [])

    request, _ = httpserver.log[0]
    body = request.get_json()
    assert "tools" not in body
    assert "max_completion_tokens" not in body


def test_returns_none_on_http_error(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_data(
        "boom", status=500
    )

    client = OpenAICompatibleClient(httpserver.url_for(""))
    result = client.chat_completions("test-model", [])

    assert result is None
