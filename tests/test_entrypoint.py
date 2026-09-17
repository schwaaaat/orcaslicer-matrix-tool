from matrix_tool import studio_arguments


def test_plain_launch_opens_studio():
    assert studio_arguments([]) == []


def test_explicit_studio_marker_is_removed():
    assert studio_arguments(["--studio", "--connect", "http://127.0.0.1:13130"]) == [
        "--connect",
        "http://127.0.0.1:13130",
    ]


def test_connect_launch_opens_studio_directly():
    assert studio_arguments(["--connect", "http://127.0.0.1:13130"]) == [
        "--connect",
        "http://127.0.0.1:13130",
    ]
    assert studio_arguments(["--connect=http://127.0.0.1:13130"]) == [
        "--connect=http://127.0.0.1:13130"
    ]


def test_legacy_cli_arguments_remain_legacy():
    assert studio_arguments(["--matrix", "layer_height=0.16,0.20"]) is None
