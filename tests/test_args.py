import io

from ijon import Arguments


def parse(*extra: str) -> Arguments:
    return Arguments.from_args(["hi", "--model", "test-model", *extra])


def test_bash_disabled_by_default():
    assert parse().bash is False


def test_bash_flag_enables_the_tool():
    assert parse("--bash").bash is True


def test_mcp_disabled_by_default():
    assert parse().mcp is False


def test_mcp_flag_enables_the_tool():
    assert parse("--mcp").mcp is True


def test_skills_disabled_by_default():
    assert parse().skills is False


def test_skills_flag_enables_the_tool():
    assert parse("--skills").skills is True


class FakeStdin(io.StringIO):
    def __init__(self, content: str, tty: bool):
        super().__init__(content)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_piped_stdin_is_appended_to_prompt(monkeypatch):
    monkeypatch.setattr("sys.stdin", FakeStdin("file contents", tty=False))
    assert parse().prompt == "hi\n\nfile contents"


def test_empty_pipe_leaves_prompt_unchanged(monkeypatch):
    monkeypatch.setattr("sys.stdin", FakeStdin("   \n", tty=False))
    assert parse().prompt == "hi"


def test_tty_stdin_is_not_read(monkeypatch):
    monkeypatch.setattr("sys.stdin", FakeStdin("should be ignored", tty=True))
    assert parse().prompt == "hi"
