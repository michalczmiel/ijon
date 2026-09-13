import re

import pytest

from conftest import (
    IMPLEMENTATIONS,
    Ijon,
    completion_requests,
    events,
    tool_names_offered,
)
from factories import assistant_message

FLAGS = [
    "-h",
    "--help",
    "--model",
    "--bash",
    "--mcp",
    "--skills",
    "--max-iterations",
    "--max-completion-tokens",
    "--jsonl",
]


def test_no_tools_by_default(ijon, httpserver, openai_endpoint):
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "test-model")

    assert "tools" not in completion_requests(httpserver)[0].get_json()


def test_bash_flag_enables_the_tool(ijon, httpserver, openai_endpoint):
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "test-model", "--bash")

    assert tool_names_offered(httpserver) == ["execute_bash_script"]


def test_model_is_forwarded(ijon, httpserver, openai_endpoint):
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "some/model:free")

    assert completion_requests(httpserver)[0].get_json()["model"] == "some/model:free"


def test_max_completion_tokens_is_forwarded_when_set(ijon, httpserver, openai_endpoint):
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "test-model", "--max-completion-tokens", "256")

    body = completion_requests(httpserver)[0].get_json()
    assert body["max_completion_tokens"] == 256


def test_max_completion_tokens_is_omitted_when_unset(ijon, httpserver, openai_endpoint):
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "test-model")

    assert "max_completion_tokens" not in completion_requests(httpserver)[0].get_json()


def test_missing_model_is_a_usage_error(ijon, httpserver):
    result = ijon.run("hi")

    assert result.returncode == 2
    assert "--model" in result.stderr
    assert not httpserver.log


def test_missing_prompt_is_a_usage_error(ijon):
    result = ijon.run("--model", "test-model")

    assert result.returncode == 2
    assert "prompt" in result.stderr


def test_non_integer_max_iterations_is_a_usage_error(ijon):
    result = ijon.run("hi", "--model", "test-model", "--max-iterations", "lots")

    assert result.returncode == 2
    assert "--max-iterations" in result.stderr


def test_non_integer_max_completion_tokens_is_a_usage_error(ijon):
    result = ijon.run("hi", "--model", "test-model", "--max-completion-tokens", "many")

    assert result.returncode == 2
    assert "--max-completion-tokens" in result.stderr


def test_unknown_flag_is_a_usage_error(ijon, httpserver):
    result = ijon.run("hi", "--model", "test-model", "--verbose")

    assert result.returncode == 2
    assert "--verbose" in result.stderr
    assert not httpserver.log


def test_extra_positional_is_a_usage_error(ijon, httpserver):
    result = ijon.run("hi", "there", "--model", "test-model")

    assert result.returncode == 2
    assert "there" in result.stderr
    assert not httpserver.log


def test_usage_errors_start_with_the_usage_line(ijon):
    result = ijon.run("hi")

    assert result.stderr.startswith("usage: ijon ")
    assert "ijon: error:" in result.stderr


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_exits_zero_and_lists_every_flag(ijon, flag):
    result = ijon.run(flag)

    assert result.returncode == 0
    assert result.stderr == ""
    for known in FLAGS:
        assert known in result.stdout


def test_help_is_identical_across_implementations(httpserver):
    # argparse wraps to the terminal width, so compare modulo whitespace
    outputs = {
        name: re.sub(
            r"\s+", " ", Ijon(command, httpserver.url_for("")).run("--help").stdout
        )
        for name, command in IMPLEMENTATIONS.items()
    }
    assert len(set(outputs.values())) == 1, outputs


def test_piped_stdin_is_appended_to_prompt(ijon, openai_endpoint):
    openai_endpoint(assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--jsonl", stdin="file contents")

    assert events(result)[0]["message"]["content"] == "hi\n\nfile contents"


def test_empty_pipe_leaves_prompt_unchanged(ijon, openai_endpoint):
    openai_endpoint(assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--jsonl", stdin="   \n")

    assert events(result)[0]["message"]["content"] == "hi"


def test_tty_stdin_is_not_read(ijon, openai_endpoint):
    openai_endpoint(assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--jsonl", tty=True)

    assert result.returncode == 0, result.stderr
    assert events(result)[0]["message"]["content"] == "hi"
