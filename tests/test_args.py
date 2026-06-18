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
