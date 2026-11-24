"""Types text into the focused application one key press at a time, like a person typing."""

import collections
import ctypes
import enum
import random
import threading
import unicodedata
from ctypes import wintypes

from logHandler import log

from .sounds import soundKindForCharacter
from .textBuffer import normalizeNewlines

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MAPVK_VK_TO_VSC = 0
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D

#: Seconds to wait before the first key, so the start announcement can begin.
START_DELAY = 0.6
MODIFIER_POLL_INTERVAL = 0.02
TYPO_CHANCE = 0.03
THINKING_PAUSE_CHANCE = 0.02

#: How many characters before the caret must match the typed text to trust a resume point.
RESUME_WINDOW = 20
#: How far back from where typing paused to look for the resume point.
RESUME_SEARCH_BACK = 60
#: The most characters that resuming will erase to repair the end of the typed text.
MAX_REPAIR = 40
#: Erasing needs at least this many matching characters, so unrelated text is never erased.
MIN_REPAIR_MATCH = 8
#: Erasing may remove this many characters more than were typed after the resume point.
REPAIR_SLACK = 3

_QWERTY_NEIGHBOURS = {
	"q": "wa",
	"w": "qeas",
	"e": "wrsd",
	"r": "etdf",
	"t": "ryfg",
	"y": "tugh",
	"u": "yihj",
	"i": "uojk",
	"o": "ipkl",
	"p": "ol",
	"a": "qwsz",
	"s": "awedxz",
	"d": "serfcx",
	"f": "drtgvc",
	"g": "ftyhbv",
	"h": "gyujnb",
	"j": "huikmn",
	"k": "jiolm",
	"l": "kop",
	"z": "asx",
	"x": "zsdc",
	"c": "xdfv",
	"v": "cfgb",
	"b": "vghn",
	"n": "bhjm",
	"m": "njk",
}

#: Characters that apps commonly change while typing (smart quotes, dashes), mapped to what was typed.
_MATCH_TRANSLATION = str.maketrans(
	{
		"‘": "'",
		"’": "'",
		"‚": "'",
		"‛": "'",
		"“": '"',
		"”": '"',
		"„": '"',
		"‟": '"',
		" ": " ",
		"–": "-",
		"—": "-",
	},
)


class _KEYBDINPUT(ctypes.Structure):
	_fields_ = (
		("wVk", wintypes.WORD),
		("wScan", wintypes.WORD),
		("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ctypes.c_size_t),
	)


class _MOUSEINPUT(ctypes.Structure):
	_fields_ = (
		("dx", wintypes.LONG),
		("dy", wintypes.LONG),
		("mouseData", wintypes.DWORD),
		("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ctypes.c_size_t),
	)


class _HARDWAREINPUT(ctypes.Structure):
	_fields_ = (
		("uMsg", wintypes.DWORD),
		("wParamL", wintypes.WORD),
		("wParamH", wintypes.WORD),
	)


class _INPUTUNION(ctypes.Union):
	# The mouse and hardware members are unused but give the union the size SendInput expects.
	_fields_ = (("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT))


class _INPUT(ctypes.Structure):
	_fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT
_user32.GetForegroundWindow.argtypes = ()
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_user32.MapVirtualKeyW.restype = wintypes.UINT


class FinishReason(enum.Enum):
	DONE = "done"
	PAUSED = "paused"
	STOPPED = "stopped"
	WINDOW_CHANGED = "windowChanged"
	FAILED = "failed"


#: Typing that was paused: the full text and the index of the next character to type.
PausedJob = collections.namedtuple("PausedJob", ("text", "nextIndex"))


def _keyInput(vk=0, scan=0, flags=0):
	item = _INPUT(type=INPUT_KEYBOARD)
	item.union.ki = _KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
	return item


def _send(inputs):
	array = (_INPUT * len(inputs))(*inputs)
	sent = _user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))
	if sent != len(inputs):
		raise ctypes.WinError(ctypes.get_last_error())


def _pressKey(vk):
	scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
	_send([_keyInput(vk=vk, scan=scan), _keyInput(vk=vk, scan=scan, flags=KEYEVENTF_KEYUP)])


def typeCharacter(ch):
	if ch == "\n":
		_pressKey(VK_RETURN)
		return
	if ch == "\t":
		_pressKey(VK_TAB)
		return
	data = ch.encode("utf-16-le")
	inputs = []
	for index in range(0, len(data), 2):
		unit = int.from_bytes(data[index : index + 2], "little")
		inputs.append(_keyInput(scan=unit, flags=KEYEVENTF_UNICODE))
		inputs.append(_keyInput(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
	_send(inputs)


def prepareText(text):
	"""Normalizes line endings and drops control characters that cannot be typed."""
	text = normalizeNewlines(text)
	return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) != "Cc")


def typoFor(ch):
	"""Returns a neighbouring key on a QWERTY keyboard, or None if ch is not a plain letter."""
	neighbours = _QWERTY_NEIGHBOURS.get(ch.lower()) if ch.isascii() else None
	if not neighbours:
		return None
	wrong = random.choice(neighbours)
	return wrong.upper() if ch.isupper() else wrong


def characterDelay(ch, baseDelay, naturalRhythm):
	"""Seconds to wait after typing ch."""
	if not naturalRhythm:
		return baseDelay
	delay = baseDelay * random.uniform(0.5, 1.5)
	if ch == " ":
		delay += baseDelay * random.uniform(0.2, 1.0)
	elif ch == "\n":
		delay += baseDelay * random.uniform(3, 6)
	elif ch in ".!?":
		delay += baseDelay * random.uniform(2, 5)
	elif ch in ",;:":
		delay += baseDelay * random.uniform(1, 2.5)
	if random.random() < THINKING_PAUSE_CHANCE:
		delay += baseDelay * random.uniform(4, 10)
	return delay


def _normalizeForMatch(text):
	"""Ignores case and smart punctuation, keeping one output character per input character."""
	text = text.translate(_MATCH_TRANSLATION)
	return "".join(lower if len(lower := ch.lower()) == 1 else ch for ch in text)


def findResumePoint(text, typedCount, textBeforeCaret):
	"""Works out where to resume by comparing the typed text with the text before the caret.

	Returns (startIndex, backspaces): press Backspace that many times, then type text from startIndex.
	Returns None when the text before the caret does not look like the typed text at all.
	"""
	if typedCount <= 0:
		return (0, 0)
	actual = _normalizeForMatch(normalizeNewlines(textBeforeCaret))
	target = _normalizeForMatch(text)
	lowest = max(1, typedCount - RESUME_SEARCH_BACK)
	for backspaces in range(min(MAX_REPAIR, len(actual)) + 1):
		end = len(actual) - backspaces
		for startIndex in range(typedCount, lowest - 1, -1):
			window = min(RESUME_WINDOW, startIndex)
			if end < window:
				continue
			if backspaces and (
				window < MIN_REPAIR_MATCH or backspaces > typedCount - startIndex + REPAIR_SLACK
			):
				continue
			if actual[end - window : end] == target[startIndex - window : startIndex]:
				return (startIndex, backspaces)
	return None


class _Run:
	def __init__(self, startIndex):
		self.stopEvent = threading.Event()
		self.pauseRequested = False
		self.nextIndex = startIndex


class AutoTyper:
	"""Types text on a background thread so NVDA stays responsive."""

	def __init__(self, onFinished, modifiersHeld, onKey=None):
		"""
		@param onFinished: Called from the typing thread with a L{FinishReason} when typing ends.
		@param modifiersHeld: Returns True while the user holds a modifier key; typing waits until it is released.
		@param onKey: Called from the typing thread after each key with type, space, enter or delete.
		"""
		self._onFinished = onFinished
		self._modifiersHeld = modifiersHeld
		self._onKey = onKey
		self._thread = None
		self._run = None
		#: The L{PausedJob} that L{resume} continues, or None.
		self.pausedJob = None

	@property
	def isRunning(self):
		thread = self._thread
		return thread is not None and thread.is_alive()

	def start(self, text, charsPerSecond, naturalRhythm, typos):
		"""Starts typing into the foreground window. Returns False if already typing or text is empty."""
		if self.isRunning:
			return False
		text = prepareText(text)
		if not text:
			return False
		self.pausedJob = None
		self._launch(text, 0, 0, charsPerSecond, naturalRhythm, typos)
		return True

	def resume(self, startIndex, backspaces, charsPerSecond, naturalRhythm, typos):
		"""Continues the paused job: presses Backspace backspaces times, then types from startIndex."""
		job = self.pausedJob
		if self.isRunning or job is None:
			return False
		self.pausedJob = None
		self._launch(job.text, max(0, min(startIndex, len(job.text))), backspaces, charsPerSecond, naturalRhythm, typos)
		return True

	def pause(self):
		run = self._run
		if run is not None and self.isRunning:
			run.pauseRequested = True
			run.stopEvent.set()

	def cancel(self):
		"""Stops typing and forgets any paused job."""
		self.pausedJob = None
		run = self._run
		if run is not None:
			run.pauseRequested = False
			run.stopEvent.set()

	def _launch(self, text, startIndex, backspaces, charsPerSecond, naturalRhythm, typos):
		run = self._run = _Run(startIndex)
		self._thread = threading.Thread(
			target=self._worker,
			name="VirtualTyper.AutoTyper",
			args=(
				run,
				text,
				backspaces,
				_user32.GetForegroundWindow(),
				1.0 / max(1, charsPerSecond),
				naturalRhythm,
				typos,
			),
			daemon=True,
		)
		self._thread.start()

	def _worker(self, run, text, backspaces, targetWindow, baseDelay, naturalRhythm, typos):
		try:
			reason = self._typeAll(run, text, backspaces, targetWindow, baseDelay, naturalRhythm, typos)
		except Exception:
			log.error("Virtual Typer: auto typing failed", exc_info=True)
			reason = FinishReason.FAILED
		if reason in (FinishReason.PAUSED, FinishReason.WINDOW_CHANGED):
			self.pausedJob = PausedJob(text, run.nextIndex)
		self._onFinished(reason)

	def _typeAll(self, run, text, backspaces, targetWindow, baseDelay, naturalRhythm, typos):
		if run.stopEvent.wait(START_DELAY):
			return self._stoppedReason(run)
		for _index in range(backspaces):
			reason = self._blockedReason(run, targetWindow)
			if reason:
				return reason
			self._press(VK_BACK)
			run.stopEvent.wait(baseDelay)
		while run.nextIndex < len(text):
			reason = self._blockedReason(run, targetWindow)
			if reason:
				return reason
			ch = text[run.nextIndex]
			wrong = typoFor(ch) if typos and random.random() < TYPO_CHANCE else None
			if wrong:
				self._type(wrong)
				run.stopEvent.wait(baseDelay * random.uniform(2, 4))
				if _user32.GetForegroundWindow() != targetWindow:
					return FinishReason.WINDOW_CHANGED
				self._press(VK_BACK)
				run.stopEvent.wait(baseDelay * random.uniform(1, 2))
			self._type(ch)
			run.nextIndex += 1
			if run.nextIndex < len(text):
				run.stopEvent.wait(characterDelay(ch, baseDelay, naturalRhythm))
		return FinishReason.DONE

	def _blockedReason(self, run, targetWindow):
		"""Waits for held modifiers to be released, then says why typing must end, or returns None to carry on."""
		# A held modifier would turn typed letters into shortcuts, such as NVDA+T or Control+S.
		while self._modifiersHeld():
			if run.stopEvent.wait(MODIFIER_POLL_INTERVAL):
				break
		if run.stopEvent.is_set():
			return self._stoppedReason(run)
		if _user32.GetForegroundWindow() != targetWindow:
			return FinishReason.WINDOW_CHANGED
		return None

	@staticmethod
	def _stoppedReason(run):
		return FinishReason.PAUSED if run.pauseRequested else FinishReason.STOPPED

	def _type(self, ch):
		typeCharacter(ch)
		self._keySound(soundKindForCharacter(ch))

	def _press(self, vk):
		_pressKey(vk)
		self._keySound("delete")

	def _keySound(self, kind):
		if self._onKey is not None:
			try:
				self._onKey(kind)
			except Exception:
				log.debugWarning("Virtual Typer: key sound failed", exc_info=True)
