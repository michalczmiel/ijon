import subprocess

from conftest import tool_results
from factories import assistant_message, bash_call


def run_script(ijon, openai_endpoint, script: str, **env: str) -> str:
    """Have the model call the bash tool once and return what it got back."""
    openai_endpoint(bash_call(script), assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--bash", "--jsonl", env=env)

    assert result.returncode == 0, result.stderr
    return tool_results(result)[0]["content"]


def test_reports_exit_code_and_output(ijon, openai_endpoint):
    output = run_script(ijon, openai_endpoint, "echo hi")

    assert "exit_code: 0" in output
    assert "stdout:\nhi" in output


def test_reports_stderr_and_failing_exit_code(ijon, openai_endpoint):
    output = run_script(ijon, openai_endpoint, "echo oops >&2; exit 3")

    assert output == "exit_code: 3\nstderr:\noops\n"


def test_omits_empty_streams(ijon, openai_endpoint):
    output = run_script(ijon, openai_endpoint, "true")

    assert output == "exit_code: 0"


def test_times_out(ijon, openai_endpoint):
    output = run_script(ijon, openai_endpoint, "sleep 5", IJON_BASH_TIMEOUT="1")

    assert "timed out after 1 seconds" in output


def test_timeout_leaves_no_orphaned_grandchildren(ijon, openai_endpoint):
    # On timeout only the shell is killed, so backgrounded grandchildren are orphaned.
    marker = "sleep 41337"  # unique so pgrep only matches our grandchild
    try:
        output = run_script(
            ijon, openai_endpoint, f"{marker} & echo started", IJON_BASH_TIMEOUT="1"
        )
        assert "timed out after 1 seconds" in output

        alive = (
            subprocess.run(
                ["pgrep", "-f", marker], capture_output=True, text=True
            ).returncode
            == 0
        )
        assert not alive, "grandchild survived the timeout (orphaned)"
    finally:
        subprocess.run(["pkill", "-f", marker])
