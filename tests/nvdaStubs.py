"""Minimal fake NVDA modules so the add-on can be imported and exercised outside NVDA."""

import os
import sys
import tempfile
import types

ADDON_PLUGINS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "addon", "globalPlugins")

DEFAULT_ADDON_CONFIG = {
	"charsPerSecond": 20,
	"naturalRhythm": True,
	"typos": False,
	"autoSave": True,
	"maxDocuments": 50,
	"titleMode": "firstLine",
	"soundPack": "keyboard18",
	"soundVolume": 80,
	"soundsInTyper": False,
}


class Recorder:
	def __init__(self):
		self.events = []

	def clear(self):
		self.events.clear()

	def spoken(self):
		return [text for kind, text in self.events if kind != "cancel"]


recorder = Recorder()


class FakeTimer:
	pending = []

	def __init__(self, callback, args):
		self.callback = callback
		self.args = args
		FakeTimer.pending.append(self)

	def Stop(self):
		if self in FakeTimer.pending:
			FakeTimer.pending.remove(self)


def runTimers():
	while FakeTimer.pending:
		timer = FakeTimer.pending.pop(0)
		timer.callback(*timer.args)


class FakeWavePlayer:
	instances = []

	def __init__(self, **kwargs):
		self.kwargs = kwargs
		self.fed = []
		self.stops = 0
		self.closed = False
		FakeWavePlayer.instances.append(self)

	def feed(self, data):
		self.fed.append(data)

	def stop(self):
		self.stops += 1

	def close(self):
		self.closed = True


class FakeTextInfo:
	textBeforeCaret = ""

	def collapse(self):
		pass

	def move(self, unit, direction, endPoint=None):
		return direction

	@property
	def text(self):
		if FakeTextInfo.textBeforeCaret is None:
			raise NotImplementedError
		return FakeTextInfo.textBeforeCaret


class FakeFocus:
	windowThreadID = 0

	def makeTextInfo(self, position):
		return FakeTextInfo()


def _module(name, **attrs):
	module = types.ModuleType(name)
	module.__dict__.update(attrs)
	sys.modules[name] = module
	return module


def _initTranslation():
	callerGlobals = sys._getframe(1).f_globals
	callerGlobals["_"] = lambda text: text
	callerGlobals["ngettext"] = lambda singular, plural, count: singular if count == 1 else plural


def normalizeGestureIdentifier(identifier):
	identifier = identifier.lower()
	prefix, main = identifier.split(":", 1)
	return prefix + ":" + "+".join(sorted(main.split("+")))


class Decider:
	def __init__(self):
		self.handlers = []

	def register(self, handler):
		self.handlers.append(handler)

	def unregister(self, handler):
		self.handlers.remove(handler)

	def decide(self, **kwargs):
		return all(handler(**kwargs) for handler in list(self.handlers))


class KeyboardInputGesture:
	SPEECHEFFECT_CANCEL = "cancel"

	def __init__(self, vkCode, scanCode=0, modifiers=(), identifiers=()):
		self.vkCode = vkCode
		self.scanCode = scanCode
		self.isExtended = False
		self.generalizedModifiers = set(modifiers)
		self.normalizedIdentifiers = [normalizeGestureIdentifier(i) for i in identifiers]
		self.isModifier = vkCode in (0x10, 0x11, 0x12, 0x2D)
		self.speechEffectWhenExecuted = self.SPEECHEFFECT_CANCEL


class Conf(dict):
	spec = {}


class FakeClipboard:
	text = ""


def install():
	"""Installs the fake modules once and returns the temporary NVDA config folder."""
	if "globalVars" in sys.modules:
		return sys.modules["globalVars"].appArgs.configPath
	configPath = tempfile.mkdtemp(prefix="virtualTyperTest")
	_module("addonHandler", initTranslation=_initTranslation)
	_module(
		"api",
		getFocusObject=FakeFocus,
		getClipData=lambda: FakeClipboard.text,
		copyToClip=lambda text, notify=False: setattr(FakeClipboard, "text", text) or True,
	)
	_module("characterProcessing", processSpeechSymbol=lambda locale, ch: {" ": "space"}.get(ch, ch))
	_module(
		"config",
		conf=Conf(
			virtualTyper=dict(DEFAULT_ADDON_CONFIG),
			keyboard={"speakTypedCharacters": 1, "speakTypedWords": 0, "keyboardLayout": "desktop"},
			audio={"outputDevice": "default"},
		),
	)
	_module("core", callLater=lambda delay, callback, *args: FakeTimer(callback, args))

	class GlobalPlugin:
		def terminate(self):
			pass

	_module("globalPluginHandler", GlobalPlugin=GlobalPlugin)
	_module("globalVars", appArgs=types.SimpleNamespace(secure=False, configPath=configPath))
	settingsDialogs = _module(
		"gui.settingsDialogs",
		NVDASettingsDialog=types.SimpleNamespace(categoryClasses=[]),
		SettingsPanel=type("SettingsPanel", (), {}),
	)
	_module(
		"gui",
		settingsDialogs=settingsDialogs,
		guiHelper=_module("gui.guiHelper"),
		nvdaControls=_module("gui.nvdaControls"),
	)
	_module("wx", CheckBox=object, Choice=object, EVT_CHOICE=None)
	_module(
		"inputCore",
		decide_executeGesture=Decider(),
		manager=types.SimpleNamespace(isInputHelpActive=False),
		normalizeGestureIdentifier=normalizeGestureIdentifier,
	)
	_module(
		"keyboardHandler",
		VK_WIN="windows",
		currentModifiers=set(),
		isNVDAModifierKey=lambda vk, extended: vk == 0x2D,
		KeyboardInputGesture=KeyboardInputGesture,
	)
	_module(
		"nvwave",
		WavePlayer=FakeWavePlayer,
		AudioPurpose=types.SimpleNamespace(SOUNDS="sounds"),
	)
	_module("queueHandler", eventQueue=None, queueFunction=lambda queue, func, *args, **kwargs: func(*args))
	_module("scriptHandler", queueScript=lambda script, gesture: script(gesture), script=lambda **kwargs: (lambda f: f))
	_module(
		"speech",
		cancelSpeech=lambda: recorder.events.append(("cancel", None)),
		speakMessage=lambda text, priority=None: recorder.events.append(("message", text)),
		speakSpelling=lambda text, *args, **kwargs: recorder.events.append(("spell", text)),
		speakText=lambda text, *args, **kwargs: recorder.events.append(("text", text)),
		speakSelectionMessage=lambda message, text, priority=None: recorder.events.append(("message", message % text)),
		getCurrentLanguage=lambda: "en",
	)
	_module("textInfos", POSITION_CARET="caret", UNIT_CHARACTER="character")
	_module("tones", beep=lambda *args, **kwargs: None)
	_module("ui", message=lambda text, *args, **kwargs: recorder.events.append(("message", text)))

	_module(
		"winKernel",
		LOCALE_NAME_USER_DEFAULT=None,
		DATE_LONGDATE=2,
		TIME_NOSECONDS=2,
		GetDateFormatEx=lambda *args: "22 November 2026",
		GetTimeFormatEx=lambda *args: "14:05",
	)

	class Log:
		def __getattr__(self, name):
			return lambda *args, **kwargs: None

	_module("logHandler", log=Log())
	if ADDON_PLUGINS not in sys.path:
		sys.path.insert(0, ADDON_PLUGINS)
	return configPath
