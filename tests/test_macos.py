import sys
import unittest
from unittest import mock

if sys.platform == "darwin":
    from whitedot.platforms import macos as mac
    from whitedot.types import Rect, Target


@unittest.skipUnless(sys.platform == "darwin", "macOS accessibility adapter")
class MacAdapterTests(unittest.TestCase):
    def test_native_range_round_trip(self):
        loc, size = mac._utf16_range("😀a teh", 3, 6)
        self.assertEqual((loc, size), (4, 3))
        boxed = mac._range(loc, size)
        self.assertEqual(mac._unpack(boxed, mac.ax.kAXValueTypeCFRange), (4, 3))

    def test_secure_field_is_excluded_before_value_is_read(self):
        adapter = mac.MacAdapter()
        fake = object()
        def attributes(element, name):
            return {"AXRole": "AXTextField", "AXSubrole": "AXSecureTextField"}[name]
        with (mock.patch.object(adapter, "permission", return_value=True),
              mock.patch.object(adapter, "_focus", return_value=(1, "Fixture", fake)),
              mock.patch.object(mac, "_attribute", side_effect=attributes),
              mock.patch.object(mac, "_text") as read):
            self.assertIsNone(adapter.capture())
        read.assert_not_called()

    def test_stale_field_rejected_without_mutation(self):
        adapter = mac.MacAdapter()
        adapter._pid, adapter._generation, adapter._element = 35, 2, object()
        stale = Target("mac:35:1", "teh", "Fixture", Rect(0, 0, 80, 22))
        with mock.patch.object(mac.ax, "AXUIElementSetAttributeValue") as write:
            self.assertFalse(adapter.replace(stale, 0, 3, "the"))
        write.assert_not_called()

    def test_rich_text_run_offsets_and_refusal_on_mismatch(self):
        a, b, parent = object(), object(), object()
        def attributes(node, name):
            if node is parent:
                return [a, b] if name == "AXChildren" else None
            return "AXStaticText" if name == "AXRole" else {a: "😀 abc ", b: "teh"}[node]
        box = Rect(110, 50, 25, 19)
        with (mock.patch.object(mac, "_attribute", side_effect=attributes),
              mock.patch.object(mac, "_row_rects", return_value=[box]) as rows):
            self.assertEqual(mac._rich_rows(parent, "😀 abc teh", 6, 9), [box])
            rows.assert_called_once_with(b, 0, 3, 1)
            self.assertEqual(mac._rich_rows(parent, "other teh", 6, 9), [])
