import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from steam_frame_passthrough_toggle import TriStateController  # noqa: E402


class FakeCamera:
    def __init__(self, available=True):
        self.available = available
        self.current = None

    def rgb_available(self):
        return self.available

    def source(self):
        return self.current

    def set_source(self, source, retry_seconds=3.0):
        self.current = source


class TriStateTests(unittest.TestCase):
    def test_rgb_cycle(self):
        camera = FakeCamera()
        control = TriStateController(camera)
        self.assertEqual(control.cycle(False), {"state": "color", "invokeNative": True, "postSource": "color"})
        control.activate_source("color")
        self.assertEqual(control.cycle(True), {"state": "mono", "invokeNative": False})
        self.assertEqual(control.cycle(True), {"state": "off", "invokeNative": True})

    def test_no_accessory_skips_color(self):
        camera = FakeCamera(available=False)
        control = TriStateController(camera)
        self.assertEqual(control.cycle(False), {"state": "mono", "invokeNative": True, "postSource": "mono"})
        control.activate_source("mono")
        self.assertEqual(control.cycle(True), {"state": "off", "invokeNative": True})


if __name__ == "__main__":
    unittest.main()
