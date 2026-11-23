import sys
import unittest
from types import SimpleNamespace

from whitedot.platforms.windows import WinAdapter, _text_range
from whitedot.types import Rect, Target


class TextRange:
    """A UIA provider whose character units are UTF-16 code units."""

    def __init__(self, text, start=0, end=None):
        self.text = text
        self.raw = text.encode("utf-16-le")
        self.start = start
        self.end = end if end is not None else len(self.raw) // 2

    def Clone(self):
        return TextRange(self.text, self.start, self.end)

    def MoveEndpointByRange(self, endpoint, other, other_endpoint):
        dest = (other.start, other.end)[other_endpoint]
        if endpoint == 1:
            self.end = dest
            self.start = min(self.start, self.end)
        else:
            self.start = dest
            self.end = max(self.start, self.end)

    def MoveEndpointByUnit(self, endpoint, unit, distance):
        assert endpoint == 1 and unit == 0
        self.end = min(len(self.raw) // 2, self.end + distance)

    def GetText(self, limit):
        return self.raw[2*self.start : 2*self.end].decode("utf-16-le", errors="replace")

    def FindText(self, text, back, fold):
        needle = text.encode("utf-16-le")
        pos = self.raw.find(needle, self.start * 2, self.end * 2)
        if pos < 0:
            return None
        return TextRange(self.text, pos // 2, (pos + len(needle)) // 2)

    def CompareEndpoints(self, endpoint, other, other_endpoint):
        return (self.start, self.end)[endpoint] - (other.start, other.end)[other_endpoint]


class AdapterTests(unittest.TestCase):
    def test_line_breaks_emoji_and_repeated_word(self):
        source = "teh\n🙂 teh"
        start = source.rindex("teh")
        span = _text_range(TextRange("teh\r\n🙂 teh"), source, start, start + 3)
        self.assertEqual(span.GetText(-1), "teh")
        self.assertEqual(span.start, 8)

    def test_wrong_document_or_offsets_do_not_pick_another_occurrence(self):
        self.assertIsNone(_text_range(TextRange("teh x"), "x teh", 2, 5))
        self.assertIsNone(_text_range(TextRange("teh"), "teh", 0, 9))

    def test_replacement_requires_matching_snapshot_and_plain_edit(self):
        old = Target("1", "teh cat", "test.exe", Rect(0, 0, 100, 25))
        adapter = object.__new__(WinAdapter)
        adapter.api = SimpleNamespace(UIA_EditControlTypeId=42)
        adapter._errors = (OSError, ValueError, TypeError)
        field = SimpleNamespace(CurrentControlType=42, CurrentHasKeyboardFocus=True)
        value = SimpleNamespace(CurrentValue=old.text)
        value.SetValue = lambda new: setattr(value, "CurrentValue", new)
        adapter._focused = lambda: (old, field, value, None)
        walker = SimpleNamespace(GetFirstChildElement=lambda el: object())
        adapter.automation = SimpleNamespace(ControlViewWalker=walker)
        self.assertFalse(adapter.replace(old, 0, 3, "the"))  # rich content
        walker.GetFirstChildElement = lambda el: None
        self.assertFalse(adapter.replace(Target("2", old.text, old.app, old.bounds), 0, 3, "the"))
        value.CurrentValue = "teh cats"
        self.assertFalse(adapter.replace(old, 0, 3, "the"))
        value.CurrentValue = old.text
        self.assertTrue(adapter.replace(old, 0, 3, "the"))
        self.assertEqual(value.CurrentValue, "the cat")

    @unittest.skipUnless(sys.platform == "win32", "requires Windows UI Automation")
    def test_native_uia_client_initializes(self):
        adapter = WinAdapter()
        self.assertTrue(adapter.permission())
        self.assertEqual(adapter.api.UIA_EditControlTypeId, 50004)
        self.assertGreater(adapter.automation.TransactionTimeout, 0)
