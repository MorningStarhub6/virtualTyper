"""Drives the global plugin with fake key presses through NVDA's gesture decider."""

import os
import shutil
import sys
import unittest

import nvdaStubs

configPath = nvdaStubs.install()

import inputCore  # noqa: E402
import keyboardHandler  # noqa: E402
import config  # noqa: E402
import virtualTyper  # noqa: E402
from virtualTyper.autoTyper import PausedJob  # noqa: E402

recorder = nvdaStubs.recorder
addonConf = config.conf["virtualTyper"]
SHIFT = (0x10, False)
CONTROL = (0x11, False)
ALT = (0x12, False)
WINDOWS = ("windows", False)
NVDA = (0x2D, False)
ESCAPE, ENTER, TAB, DELETE, F2 = 0x1B, 0x0D, 0x09, 0x2E, 0x71
UP, DOWN = 0x26, 0x28


def fakeTranslate(vkCode, scanCode, shift=False, altGr=False, threadId=0):
	if altGr:
		return "€" if vkCode == ord("E") else None
	if vkCode == 0x20:
		return " "
	if ord("A") <= vkCode <= ord("Z"):
		return chr(vkCode) if shift else chr(vkCode).lower()
	if vkCode == 0xBE:
		return "."
	return None


class PluginTestCase(unittest.TestCase):
	def setUp(self):
		shutil.rmtree(os.path.join(configPath, virtualTyper.STORAGE_FOLDER_NAME), ignore_errors=True)
		addonConf.clear()
		addonConf.update(nvdaStubs.DEFAULT_ADDON_CONFIG)
		addonConf["soundPack"] = ""
		nvdaStubs.FakeTimer.pending.clear()
		self.plugin = self._newPlugin()
		recorder.clear()

	def tearDown(self):
		if self.plugin in [getattr(h, "__self__", None) for h in inputCore.decide_executeGesture.handlers]:
			self.plugin.terminate()

	def _newPlugin(self):
		plugin = virtualTyper.GlobalPlugin()
		plugin._editor._translator.translate = fakeTranslate
		self.started = []
		plugin._autoTyper.start = lambda text, *args: self.started.append(text) or True
		return plugin

	def restartNvda(self):
		self.plugin.terminate()
		self.plugin = self._newPlugin()

	@property
	def editor(self):
		return self.plugin._editor

	@property
	def buffer(self):
		return self.editor._buffer

	@property
	def titles(self):
		return [doc["title"] for doc in self.editor._store.documents]

	def press(self, vk, *modifiers, identifiers=()):
		"""Returns True when the key would be passed on to Windows."""
		gesture = keyboardHandler.KeyboardInputGesture(vk, modifiers=modifiers, identifiers=identifiers)
		return inputCore.decide_executeGesture.decide(gesture=gesture)

	def typeString(self, text):
		for ch in text:
			if ch == " ":
				self.assertFalse(self.press(0x20))
			elif ch == ".":
				self.assertFalse(self.press(0xBE))
			elif ch == "\n":
				self.assertFalse(self.press(ENTER))
			elif ch.isupper():
				self.assertFalse(self.press(ord(ch), SHIFT))
			else:
				self.assertFalse(self.press(ord(ch.upper())))

	def openTyper(self):
		self.plugin.script_toggleTyper(None)
		recorder.clear()

	def lastSpoken(self):
		return recorder.spoken()[-1]


class TestClosedTyper(PluginTestCase):
	def test_keysPassThroughWhenClosed(self):
		self.assertTrue(self.press(ord("A")))
		self.assertTrue(self.press(ESCAPE))

	def test_openAnnouncesAndRegistersSettings(self):
		self.plugin.script_toggleTyper(None)
		self.assertIn("Virtual typer, new file, blank", recorder.spoken())
		categories = sys.modules["gui"].settingsDialogs.NVDASettingsDialog.categoryClasses
		self.assertIn(virtualTyper.VirtualTyperSettingsPanel, categories)

	def test_importsVersionOneText(self):
		self.plugin.terminate()
		shutil.rmtree(os.path.join(configPath, virtualTyper.STORAGE_FOLDER_NAME), ignore_errors=True)
		legacyPath = os.path.join(configPath, virtualTyper.LEGACY_FILE_NAME)
		with open(legacyPath, "w", encoding="utf-8") as legacyFile:
			legacyFile.write("old text")
		self.plugin = self._newPlugin()
		self.assertEqual(self.buffer.text, "old text")
		self.assertFalse(os.path.exists(legacyPath))


class TestEditing(PluginTestCase):
	def setUp(self):
		super().setUp()
		self.openTyper()

	def test_typingEchoesAndStoresText(self):
		self.typeString("Hi you")
		self.assertEqual(self.buffer.text, "Hi you")
		self.assertEqual(recorder.spoken()[:3], ["H", "i", " "])

	def test_wordEcho(self):
		config.conf["keyboard"]["speakTypedWords"] = 1
		config.conf["keyboard"]["speakTypedCharacters"] = 0
		try:
			self.typeString("good day.")
		finally:
			config.conf["keyboard"]["speakTypedWords"] = 0
			config.conf["keyboard"]["speakTypedCharacters"] = 1
		self.assertEqual(recorder.spoken(), ["good", "day"])

	def test_navigationSpeaks(self):
		self.typeString("first\nsecond")
		recorder.clear()
		self.assertFalse(self.press(UP))
		self.assertEqual(recorder.spoken(), ["first"])
		recorder.clear()
		self.press(0x24)
		self.assertEqual(recorder.spoken(), ["f"])
		recorder.clear()
		self.press(0x27, CONTROL)
		self.assertEqual(recorder.spoken(), ["blank"])
		recorder.clear()
		self.press(0x23, CONTROL)
		self.assertEqual(recorder.spoken(), ["second"])

	def test_selectionCopyAndPaste(self):
		self.typeString("hello world")
		recorder.clear()
		self.press(0x25, CONTROL, SHIFT)
		self.assertEqual(recorder.spoken(), ["world selected"])
		recorder.clear()
		self.press(0x27, SHIFT)
		self.assertEqual(recorder.spoken(), ["w unselected"])
		self.press(0x25, CONTROL, SHIFT)
		self.press(ord("C"), CONTROL)
		self.assertEqual(nvdaStubs.FakeClipboard.text, "world")
		self.press(0x23)
		self.press(ord("V"), CONTROL)
		self.assertEqual(self.buffer.text, "hello worldworld")

	def test_undoRedoAndBackspace(self):
		self.typeString("one two")
		self.press(0x08)
		self.assertEqual(self.lastSpoken(), "o")
		self.press(ord("Z"), CONTROL)
		self.assertEqual(self.buffer.text, "one two")
		self.press(ord("Z"), CONTROL)
		self.assertEqual(self.buffer.text, "one ")
		self.press(ord("Y"), CONTROL)
		self.assertEqual(self.buffer.text, "one two")

	def test_altGrTypesCharacter(self):
		self.assertFalse(self.press(ord("E"), CONTROL, ALT))
		self.assertEqual(self.buffer.text, "€")

	def test_nvdaCommandsAreRedirected(self):
		self.typeString("line one")
		recorder.clear()
		self.assertFalse(self.press(UP, NVDA, identifiers=("kb(desktop):NVDA+upArrow", "kb:NVDA+upArrow")))
		self.assertEqual(recorder.spoken(), ["line one"])
		self.assertFalse(self.press(ord("T"), NVDA, identifiers=("kb(desktop):NVDA+t", "kb:NVDA+t")))
		self.assertEqual(self.lastSpoken(), "new file, not saved")
		self.assertTrue(self.press(ord("F"), NVDA, identifiers=("kb(desktop):NVDA+f", "kb:NVDA+f")))

	def test_systemKeysPassThrough(self):
		self.assertTrue(self.press(TAB, ALT))
		self.assertTrue(self.press(ord("D"), WINDOWS))
		self.assertTrue(self.press(0xAF))
		self.assertTrue(self.press(0x14))
		self.assertTrue(self.press(0x10, SHIFT))
		self.assertEqual(self.buffer.text, "")

	def test_otherKeysAreSwallowed(self):
		self.assertFalse(self.press(0x74))
		self.assertFalse(self.press(ord("F"), ALT))
		self.assertFalse(self.press(ord("Q"), CONTROL))
		self.assertEqual(self.buffer.text, "")
		self.assertFalse(self.press(0x70))
		self.assertTrue(self.lastSpoken().startswith("Virtual typer help."))

	def test_soundsInTyperFollowSetting(self):
		nvdaStubs.FakeWavePlayer.instances.clear()
		addonConf["soundPack"] = "keyboard18"
		self.typeString("a")
		self.assertEqual(nvdaStubs.FakeWavePlayer.instances, [])
		addonConf["soundsInTyper"] = True
		self.typeString("b ")
		self.press(0x08)
		self.assertEqual(sum(len(p.fed) for p in nvdaStubs.FakeWavePlayer.instances), 3)


class TestSaving(PluginTestCase):
	def setUp(self):
		super().setUp()
		self.openTyper()

	def test_autoSaveTimerSavesWithFirstLineTitle(self):
		self.typeString("Shopping\nmilk")
		self.assertEqual(self.titles, [])
		nvdaStubs.runTimers()
		self.assertEqual(self.titles, ["Shopping"])
		self.assertFalse(self.editor.isDirty)

	def test_escapeAutoSavesAndTextSurvivesRestart(self):
		self.typeString("keep me")
		self.assertFalse(self.press(ESCAPE))
		self.assertEqual(self.lastSpoken(), "Virtual typer closed")
		self.assertEqual(self.titles, ["keep me"])
		self.assertTrue(self.press(ord("A")))
		self.restartNvda()
		self.assertEqual(self.buffer.text, "keep me")
		self.assertEqual(self.editor._doc["title"], "keep me")

	def test_withoutAutoSaveCloseAsksAndNoDiscards(self):
		addonConf["autoSave"] = False
		self.typeString("scratch")
		self.press(ESCAPE)
		self.assertTrue(self.lastSpoken().startswith("Save changes to new file?"))
		self.assertTrue(self.editor.isOpen)
		self.press(ord("Q"))
		self.assertTrue(self.lastSpoken().startswith("Save changes to new file?"))
		self.press(ord("N"))
		self.assertFalse(self.editor.isOpen)
		self.assertEqual(self.titles, [])
		self.openTyper()
		self.assertEqual(self.buffer.text, "")

	def test_withoutAutoSaveYesSavesAndEscapeStays(self):
		addonConf["autoSave"] = False
		self.typeString("notes")
		self.press(ESCAPE)
		self.press(ESCAPE)
		self.assertEqual(self.lastSpoken(), "Cancelled")
		self.assertTrue(self.editor.isOpen)
		self.press(ESCAPE)
		self.press(ord("Y"))
		self.assertEqual(self.titles, ["notes"])
		self.assertIn("Saved notes", recorder.spoken())
		self.assertFalse(self.editor.isOpen)

	def test_unsavedDraftSurvivesRestartWithoutAutoSave(self):
		addonConf["autoSave"] = False
		self.typeString("draft")
		self.restartNvda()
		self.assertEqual(self.buffer.text, "draft")
		self.assertTrue(self.editor.isDirty)

	def test_askModeTitlePrompt(self):
		addonConf["autoSave"] = False
		addonConf["titleMode"] = "ask"
		self.typeString("draft text")
		self.press(ord("S"), CONTROL)
		self.assertEqual(self.lastSpoken(), "Title: draft text. Type and press Enter, or Escape to cancel.")
		self.typeString("My notes")
		self.assertEqual(self.buffer.text, "draft text")
		self.press(ENTER)
		self.assertEqual(self.titles, ["My notes"])
		self.assertEqual(self.lastSpoken(), "Saved My notes")
		self.typeString(" more")
		nvdaStubs.runTimers()
		self.press(ord("S"), CONTROL)
		self.assertEqual(self.titles, ["My notes"])

	def test_askModeWithAutoSaveAsksOnClose(self):
		addonConf["titleMode"] = "ask"
		self.typeString("idea")
		nvdaStubs.runTimers()
		self.assertEqual(self.titles, ["idea"])
		self.press(ESCAPE)
		self.assertTrue(self.lastSpoken().startswith("Title: idea."))
		self.press(ENTER)
		self.assertFalse(self.editor.isOpen)
		self.assertEqual(self.editor._doc["titleSource"], "fixed")

	def test_dateTitleMode(self):
		addonConf["titleMode"] = "date"
		self.typeString("x")
		self.press(ord("S"), CONTROL)
		self.assertEqual(self.titles, ["22 November 2026 14:05"])

	def test_newFileAndMaximumKept(self):
		addonConf["maxDocuments"] = 2
		for word in ("one", "two", "three"):
			self.typeString(word)
			self.press(ord("N"), CONTROL)
		self.assertEqual(self.titles, ["three", "two"])
		self.assertEqual(self.lastSpoken(), "New file")


class TestFileList(PluginTestCase):
	def setUp(self):
		super().setUp()
		self.openTyper()
		self.typeString("alpha")
		self.press(ord("N"), CONTROL)
		self.typeString("beta")
		self.press(ord("S"), CONTROL)
		recorder.clear()

	def test_emptyList(self):
		shutil.rmtree(os.path.join(configPath, virtualTyper.STORAGE_FOLDER_NAME))
		self.editor._store.documents.clear()
		self.press(TAB, CONTROL)
		self.assertEqual(self.lastSpoken(), "No saved files")

	def test_openAnotherFile(self):
		self.press(TAB, CONTROL)
		self.assertEqual(recorder.spoken(), ["Saved files", "alpha, 2 of 2"])
		self.press(UP)
		self.assertEqual(self.lastSpoken(), "beta, open, 1 of 2")
		self.press(TAB, CONTROL)
		self.press(ENTER)
		self.assertEqual(self.lastSpoken(), "alpha, line 1 of 1")
		self.assertEqual(self.buffer.text, "alpha")

	def test_switchingSavesOrAsksAboutChanges(self):
		self.typeString(" more")
		self.press(TAB, CONTROL)
		self.press(ENTER)
		self.assertEqual(self.buffer.text, "alpha")
		self.assertEqual(self.titles[0], "beta more")
		addonConf["autoSave"] = False
		self.typeString(" edit")
		self.press(TAB, CONTROL)
		self.press(ENTER)
		self.assertTrue(self.lastSpoken().startswith("Save changes to alpha?"))
		self.press(ord("N"))
		self.assertEqual(self.buffer.text, "beta more")

	def test_firstLetterNavigationAndHelp(self):
		self.press(TAB, CONTROL)
		self.press(ord("B"))
		self.assertEqual(self.lastSpoken(), "beta, open, 1 of 2")
		self.press(0x70)
		self.assertTrue(self.lastSpoken().startswith("Saved files help."))
		self.press(ESCAPE)
		self.assertEqual(self.lastSpoken(), "Back to beta")

	def test_deleteAndRename(self):
		self.press(TAB, CONTROL)
		self.press(DELETE)
		self.assertTrue(self.lastSpoken().startswith("Delete alpha?"))
		self.press(ord("Y"))
		self.assertEqual(self.titles, ["beta"])
		self.assertEqual(recorder.spoken()[-2:], ["Deleted", "beta, open, 1 of 1"])
		self.press(F2)
		self.typeString("Renamed")
		self.press(ENTER)
		self.assertEqual(self.lastSpoken(), "Renamed, open, 1 of 1")
		self.press(ESCAPE)
		self.assertEqual(self.lastSpoken(), "Back to Renamed")

	def test_deletingOpenFileKeepsTextAsNewFile(self):
		self.press(TAB, CONTROL)
		self.press(UP)
		self.press(DELETE)
		self.press(ord("Y"))
		self.assertEqual(self.lastSpoken(), "alpha, 1 of 1")
		self.press(ESCAPE)
		self.assertEqual(self.buffer.text, "beta")
		self.assertIsNone(self.editor._doc)


class TestAutoTyping(PluginTestCase):
	def test_controlEnterTypesOutText(self):
		self.openTyper()
		self.typeString("send this")
		self.assertFalse(self.press(ENTER, CONTROL))
		self.assertFalse(self.editor.isOpen)
		self.assertEqual(self.started, ["send this"])
		self.assertIn("Typing. Press escape to stop.", recorder.spoken())

	def test_typesClipboard(self):
		nvdaStubs.FakeClipboard.text = "from clipboard"
		self.plugin.script_typeClipboard(None)
		self.assertEqual(self.started, ["from clipboard"])

	def test_emptyClipboard(self):
		nvdaStubs.FakeClipboard.text = ""
		self.plugin.script_typeClipboard(None)
		self.assertEqual(self.started, [])
		self.assertIn("There is no text on the clipboard", recorder.spoken())

	def test_runningTyperKeys(self):
		calls = []
		typer = self.plugin._autoTyper
		typer.pause = lambda: calls.append("pause")
		typer.cancel = lambda: calls.append("cancel")
		typerClass = type(typer)
		originalIsRunning = typerClass.isRunning
		typerClass.isRunning = property(lambda self: True)
		try:
			self.assertFalse(self.press(ESCAPE))
			self.assertTrue(self.press(ord("A")))
			self.plugin.script_typeClipboard(None)
			self.plugin.script_cancelAutoTyping(None)
		finally:
			typerClass.isRunning = originalIsRunning
		self.assertEqual(calls, ["cancel", "pause", "cancel"])

	def _pause(self, text, nextIndex):
		self.plugin._autoTyper.pausedJob = PausedJob(text, nextIndex)
		self.resumed = []
		self.plugin._autoTyper.resume = lambda *args: self.resumed.append(args[:2]) or True

	def test_resumeContinuesWhenTextMatches(self):
		self._pause("hello world", 5)
		nvdaStubs.FakeTextInfo.textBeforeCaret = "Dear Sam, hello"
		self.plugin.script_typeClipboard(None)
		self.assertEqual(self.resumed, [(5, 0)])
		self.assertEqual(self.lastSpoken(), "Resuming")

	def test_resumeReportsMissingCharacters(self):
		self._pause("hello world", 8)
		nvdaStubs.FakeTextInfo.textBeforeCaret = "hello"
		self.plugin.script_typeClipboard(None)
		self.assertEqual(self.resumed, [(5, 0)])
		self.assertEqual(self.lastSpoken(), "3 characters were missing. Resuming from there")

	def test_resumeAsksBeforeContinuingOnMismatch(self):
		self._pause("hello world", 8)
		nvdaStubs.FakeTextInfo.textBeforeCaret = "nothing alike"
		self.plugin.script_typeClipboard(None)
		self.assertEqual(self.resumed, [])
		self.assertTrue(self.lastSpoken().startswith("The text before the cursor does not match"))
		self.plugin.script_typeClipboard(None)
		self.assertEqual(self.resumed, [(8, 0)])

	def test_resumeWithoutReadableTextContinues(self):
		self._pause("hello world", 8)
		nvdaStubs.FakeTextInfo.textBeforeCaret = None
		try:
			self.plugin.script_typeClipboard(None)
		finally:
			nvdaStubs.FakeTextInfo.textBeforeCaret = ""
		self.assertEqual(self.resumed, [(8, 0)])

	def test_cancelPausedJob(self):
		self._pause("hello", 2)
		self.plugin.script_cancelAutoTyping(None)
		self.assertIsNone(self.plugin._autoTyper.pausedJob)
		self.assertEqual(self.lastSpoken(), "Paused typing cancelled")
		self.plugin.script_cancelAutoTyping(None)
		self.assertEqual(self.lastSpoken(), "Not auto typing")

	def test_finishAnnouncements(self):
		self.plugin._onAutoTypingFinished(virtualTyper.FinishReason.WINDOW_CHANGED)
		self.plugin._onAutoTypingFinished(virtualTyper.FinishReason.PAUSED)
		self.assertEqual(
			recorder.spoken(),
			[
				"Typing paused because the window changed. Press NVDA+Control+apostrophe to resume.",
				"Typing paused. Press NVDA+Control+apostrophe to resume.",
			],
		)


if __name__ == "__main__":
	unittest.main()
