import subprocess

from ijon import execute_bash_script


def test_reports_exit_code_and_output():
    result = execute_bash_script("echo hi", timeout=10)

    assert "exit_code: 0" in result
    assert "stdout:\nhi" in result


def test_times_out():
    result = execute_bash_script("sleep 5", timeout=1)

    assert "timed out after 1 seconds" in result


def test_timeout_leaves_no_orphaned_grandchildren():
    # On timeout only the shell is killed, so backgrounded grandchildren are orphaned.
    marker = "sleep 41337"  # unique so pgrep only matches our grandchild
    try:
        result = execute_bash_script(f"{marker} & echo started", timeout=1)
        assert "timed out after 1 seconds" in result

        alive = (
            subprocess.run(
                ["pgrep", "-f", marker], capture_output=True, text=True
            ).returncode
            == 0
        )
        assert not alive, "grandchild survived the timeout (orphaned)"
    finally:
        subprocess.run(["pkill", "-f", marker])
