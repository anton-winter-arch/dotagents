from greenhouse.sensors import humidity


def test_read_is_a_percentage():
    assert 0.0 <= humidity.read() <= 100.0
