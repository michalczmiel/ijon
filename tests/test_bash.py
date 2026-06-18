from ijon import execute_bash_script


def test_reports_exit_code_and_output():
    result = execute_bash_script("echo hi", timeout=10)

    assert "exit_code: 0" in result
    assert "stdout:\nhi" in result


def test_times_out():
    result = execute_bash_script("sleep 5", timeout=1)

    assert "timed out after 1 seconds" in result
