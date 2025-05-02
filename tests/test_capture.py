import pytest
from src.capture import Capture

@pytest.fixture
def capture_instance():
    return Capture()

def test_start_capture(capture_instance):
    assert capture_instance.start_capture() is True

def test_stop_capture(capture_instance):
    capture_instance.start_capture()
    assert capture_instance.stop_capture() is True

def test_capture_state(capture_instance):
    capture_instance.start_capture()
    assert capture_instance.is_capturing is True
    capture_instance.stop_capture()
    assert capture_instance.is_capturing is False