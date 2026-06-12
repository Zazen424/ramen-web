from pendant_server import protocol as P


def test_frame_math():
    assert P.FRAME_SAMPLES == 640
    assert P.FRAME_BYTES == 1280
    assert P.FRAME_BYTES == P.FRAME_SAMPLES * P.SAMPLE_WIDTH * P.CHANNELS


def test_roundtrip_control():
    msg = P.say(3, "hello there")
    wire = P.encode(msg)
    assert P.decode(wire) == msg


def test_decode_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        P.decode("not json")
    with pytest.raises(ValueError):
        P.decode('{"no":"type"}')


def test_builders_have_type_tags():
    assert P.hello()["t"] == P.HELLO
    assert P.start(1)["t"] == P.START
    assert P.end(1)["t"] == P.END
    assert P.cancel(1)["t"] == P.CANCEL
    assert P.ping(123)["ts"] == 123
    assert P.done(1, {"ttfa_ms": 5})["metrics"]["ttfa_ms"] == 5
