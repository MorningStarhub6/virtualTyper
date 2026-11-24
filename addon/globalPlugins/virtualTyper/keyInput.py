"""Works out which characters a key press would type with the user's current keyboard layout."""

import ctypes
import unicodedata
from ctypes import wintypes

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_CAPITAL = 0x14
VK_LSHIFT = 0xA0
VK_LCONTROL = 0xA2
VK_RMENU = 0xA5
VK_PACKET = 0xE7

_KEY_DOWN = 0x80
# ToUnicodeEx flag (Windows 10 1607+) that stops it from disturbing the dead key state of the real keyboard.
_NO_KEYBOARD_STATE_CHANGE = 0x4

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.argtypes = ()
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
_user32.GetKeyboardLayout.restype = wintypes.HKL
_user32.GetKeyState.argtypes = (ctypes.c_int,)
_user32.GetKeyState.restype = ctypes.c_short
_user32.ToUnicodeEx.argtypes = (
	wintypes.UINT,
	wintypes.UINT,
	ctypes.POINTER(ctypes.c_ubyte),
	ctypes.POINTER(ctypes.c_wchar),
	ctypes.c_int,
	wintypes.UINT,
	wintypes.HKL,
)
_user32.ToUnicodeEx.restype = ctypes.c_int

#: Spacing characters that keyboard layouts report for dead keys, mapped to the combining mark they add.
_DEAD_KEY_MARKS = {
	"`": "̀",
	"ˋ": "̀",
	"´": "́",
	"'": "́",
	"ˊ": "́",
	"΄": "́",
	"^": "̂",
	"ˆ": "̂",
	"~": "̃",
	"˜": "̃",
	"¯": "̄",
	"˘": "̆",
	"˙": "̇",
	"¨": "̈",
	'"': "̈",
	"°": "̊",
	"˚": "̊",
	"˝": "̋",
	"ˇ": "̌",
	"¸": "̧",
	"˛": "̨",
}


def _withoutControlChars(text):
	return "".join(ch for ch in text if unicodedata.category(ch) != "Cc")


def composeDeadKey(deadChar, text):
	"""Combines a pending dead key with the text of the next key, the way Windows does."""
	if text == " ":
		return deadChar
	mark = _DEAD_KEY_MARKS.get(deadChar)
	if mark is None and unicodedata.category(deadChar) == "Mn":
		mark = deadChar
	if mark and len(text) == 1:
		composed = unicodedata.normalize("NFC", text + mark)
		if len(composed) == 1:
			return composed
	return deadChar + text


def keyboardLayoutForThread(threadId):
	if not threadId:
		window = _user32.GetForegroundWindow()
		threadId = _user32.GetWindowThreadProcessId(window, None) if window else 0
	return _user32.GetKeyboardLayout(threadId)


class CharacterTranslator:
	"""Turns key presses into text, tracking dead keys and UTF-16 surrogate pairs between presses."""

	def __init__(self):
		self._deadChar = None
		self._highSurrogate = None

	def reset(self):
		self._deadChar = None
		self._highSurrogate = None

	def translate(self, vkCode, scanCode, shift=False, altGr=False, threadId=0):
		"""Returns the typed text, "" when the key only started a sequence, or None when it types nothing."""
		if vkCode == VK_PACKET:
			return self._translatePacket(scanCode)
		states = (ctypes.c_ubyte * 256)()
		if shift:
			states[VK_SHIFT] = states[VK_LSHIFT] = _KEY_DOWN
		if altGr:
			states[VK_CONTROL] = states[VK_LCONTROL] = _KEY_DOWN
			states[VK_MENU] = states[VK_RMENU] = _KEY_DOWN
		states[VK_CAPITAL] = _user32.GetKeyState(VK_CAPITAL) & 1
		buffer = ctypes.create_unicode_buffer(16)
		count = _user32.ToUnicodeEx(
			vkCode,
			scanCode,
			states,
			buffer,
			len(buffer),
			_NO_KEYBOARD_STATE_CHANGE,
			keyboardLayoutForThread(threadId),
		)
		if count < 0:
			deadChar = buffer[0]
			if self._deadChar:
				previous, self._deadChar = self._deadChar, None
				return previous + deadChar
			self._deadChar = deadChar
			return ""
		text = _withoutControlChars(buffer[:count]) if count > 0 else ""
		if self._deadChar:
			deadChar, self._deadChar = self._deadChar, None
			if text:
				return composeDeadKey(deadChar, text)
		return text or None

	def _translatePacket(self, unit):
		"""Handles VK_PACKET keys, which carry a UTF-16 code unit from software such as braille keyboards."""
		unit &= 0xFFFF
		if 0xD800 <= unit <= 0xDBFF:
			self._highSurrogate = unit
			return ""
		high, self._highSurrogate = self._highSurrogate, None
		if 0xDC00 <= unit <= 0xDFFF:
			if high is None:
				return None
			return chr(0x10000 + ((high - 0xD800) << 10) + (unit - 0xDC00))
		ch = chr(unit)
		if ch in "\r\n":
			return "\n"
		if ch == "\t":
			return ch
		return _withoutControlChars(ch) or None
