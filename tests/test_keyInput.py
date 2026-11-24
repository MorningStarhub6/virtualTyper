import ctypes
import unittest

import nvdaStubs

nvdaStubs.install()

from virtualTyper import keyInput  # noqa: E402
from virtualTyper.keyInput import VK_PACKET, CharacterTranslator, composeDeadKey  # noqa: E402

US_ENGLISH_LAYOUT = 0x04090409
UK_ENGLISH_LAYOUT = 0x08090809
FRENCH_LAYOUT = 0x040C040C


def _loadedLayouts():
	user32 = ctypes.WinDLL("user32")
	count = user32.GetKeyboardLayoutList(0, None)
	layouts = (ctypes.c_void_p * count)()
	user32.GetKeyboardLayoutList(count, layouts)
	return [layout or 0 for layout in layouts]


LOADED_LAYOUTS = _loadedLayouts()
ENGLISH_LAYOUT = next((layout for layout in (US_ENGLISH_LAYOUT, UK_ENGLISH_LAYOUT) if layout in LOADED_LAYOUTS), None)


class _LayoutTestCase(unittest.TestCase):
	layout = None

	def setUp(self):
		self._original = keyInput.keyboardLayoutForThread
		keyInput.keyboardLayoutForThread = lambda threadId: self.layout

	def tearDown(self):
		keyInput.keyboardLayoutForThread = self._original


class TestDeadKeys(unittest.TestCase):
	def test_composes(self):
		self.assertEqual(composeDeadKey("^", "e"), "ê")
		self.assertEqual(composeDeadKey("´", "a"), "á")
		self.assertEqual(composeDeadKey("¨", "u"), "ü")
		self.assertEqual(composeDeadKey("~", "n"), "ñ")

	def test_spaceGivesDeadChar(self):
		self.assertEqual(composeDeadKey("^", " "), "^")

	def test_noCompositionKeepsBoth(self):
		self.assertEqual(composeDeadKey("^", "x"), "^x")


class TestPacketKeys(unittest.TestCase):
	def test_plainAndSurrogatePair(self):
		translator = CharacterTranslator()
		self.assertEqual(translator.translate(VK_PACKET, ord("a")), "a")
		self.assertEqual(translator.translate(VK_PACKET, 0xD83D), "")
		self.assertEqual(translator.translate(VK_PACKET, 0xDE00), "\U0001f600")
		self.assertIsNone(translator.translate(VK_PACKET, 0xDE00))
		self.assertEqual(translator.translate(VK_PACKET, 0x0D), "\n")
		self.assertIsNone(translator.translate(VK_PACKET, 0x07))


@unittest.skipUnless(ENGLISH_LAYOUT, "No US or UK English keyboard layout is installed")
class TestEnglishLayout(_LayoutTestCase):
	layout = ENGLISH_LAYOUT

	def test_lettersDigitsAndShift(self):
		translator = CharacterTranslator()
		capsLockOn = keyInput._user32.GetKeyState(keyInput.VK_CAPITAL) & 1
		self.assertEqual(translator.translate(ord("A"), 0x1E), "A" if capsLockOn else "a")
		self.assertEqual(translator.translate(ord("A"), 0x1E, shift=True), "a" if capsLockOn else "A")
		self.assertEqual(translator.translate(ord("1"), 0x02, shift=True), "!")
		self.assertEqual(translator.translate(0x20, 0x39), " ")

	def test_nonCharacterKeysTypeNothing(self):
		translator = CharacterTranslator()
		self.assertIsNone(translator.translate(0x74, 0x3F))
		expectedAltGrA = "á" if self.layout == UK_ENGLISH_LAYOUT else None
		self.assertEqual(translator.translate(ord("A"), 0x1E, altGr=True), expectedAltGrA)


@unittest.skipUnless(FRENCH_LAYOUT in LOADED_LAYOUTS, "French keyboard layout is not installed")
class TestFrenchLayout(_LayoutTestCase):
	layout = FRENCH_LAYOUT

	def test_deadCircumflexAndAltGr(self):
		translator = CharacterTranslator()
		self.assertEqual(translator.translate(0xDD, 0x1A), "")
		self.assertEqual(translator.translate(ord("E"), 0x12), "ê")
		self.assertEqual(translator.translate(0xDD, 0x1A), "")
		self.assertEqual(translator.translate(0x20, 0x39), "^")
		self.assertEqual(translator.translate(ord("E"), 0x12, altGr=True), "€")


if __name__ == "__main__":
	unittest.main()
