from conftest import completion_requests
from factories import assistant_message


def test_posts_the_body_to_the_chat_completions_endpoint(
    ijon, httpserver, openai_endpoint
):
    openai_endpoint(assistant_message("hi"))

    ijon.run("hello", "--model", "test-model")

    request = completion_requests(httpserver)[0]
    assert request.get_json() == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert request.headers["Content-Type"] == "application/json"


def test_sends_the_api_key_as_a_bearer_token(ijon, httpserver, openai_endpoint):
    openai_endpoint(assistant_message("hi"))

    ijon.run("hi", "--model", "test-model", env={"OPENAI_API_KEY": "sk-secret"})

    request = completion_requests(httpserver)[0]
    assert request.headers["Authorization"] == "Bearer sk-secret"


def test_omits_authorization_without_an_api_key(ijon, httpserver, openai_endpoint):
    openai_endpoint(assistant_message("hi"))

    ijon.run("hi", "--model", "test-model")

    request = completion_requests(httpserver)[0]
    assert "Authorization" not in request.headers


def test_fails_on_unparseable_body(ijon, httpserver):
    # A 200 with a non-JSON body (e.g. proxy HTML, truncated response) must not crash.
    httpserver.expect_request("/v1/chat/completions").respond_with_data(
        "<html>502 Bad Gateway</html>", status=200
    )

    result = ijon.run("hi", "--model", "test-model")

    assert result.returncode == 1
    assert "non-JSON response body" in result.stderr
