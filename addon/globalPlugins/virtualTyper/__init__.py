"""Virtual Typer: a hidden notepad you only hear, plus an auto typer that types like a person."""

import os
import time

import addonHandler
import config
import globalPluginHandler
import globalVars
import gui
import inputCore
import keyboardHandler
import queueHandler
import scriptHandler
import speech
import textInfos
import tones
import ui
import api
from logHandler import log
from scriptHandler import script

from .addonConfig import CONFIG_SECTION, CONFIG_SPEC, getConfig
from .autoTyper import AutoTyper, FinishReason, findResumePoint
from .keys import VK_ESCAPE
from .settingsPanel import VirtualTyperSettingsPanel
from .sounds import keyboardSounds
from .virtualEditor import VirtualEditor, getClipboardText

try:
	from winAPI.sessionTracking import isLockScreenModeActive
except ImportError:

	def isLockScreenModeActive():
		return False


addonHandler.initTranslation()
config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC

STORAGE_FOLDER_NAME = "virtualTyper"
LEGACY_FILE_NAME = "virtualTyper.txt"
#: Characters read from before the caret to check where paused typing should continue.
RESUME_READ_LENGTH = 120
#: Seconds in which a second resume press continues even though the text did not match.
FORCE_RESUME_SECONDS = 5


def _modifiersHeld():
	return bool(keyboardHandler.currentModifiers)


def _textBeforeCaret():
	"""Returns text just before the caret in the focused control, or None if it cannot be read."""
	try:
		info = api.getFocusObject().makeTextInfo(textInfos.POSITION_CARET)
		info.collapse()
		info.move(textInfos.UNIT_CHARACTER, -RESUME_READ_LENGTH, endPoint="start")
		return info.text
	except Exception:
		log.debugWarning("Virtual Typer: could not read the text before the caret", exc_info=True)
		return None


def _disableInSecureMode(cls):
	return globalPluginHandler.GlobalPlugin if globalVars.appArgs.secure else cls


@_disableInSecureMode
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	# Translators: Category of the Virtual Typer commands in the Input gestures dialog.
	scriptCategory = _("Virtual Typer")

	def __init__(self):
		super().__init__()
		configPath = globalVars.appArgs.configPath
		self._editor = VirtualEditor(
			os.path.join(configPath, STORAGE_FOLDER_NAME),
			onTypeOut=self._startAutoTyping,
			legacyDraftPath=os.path.join(configPath, LEGACY_FILE_NAME),
		)
		self._autoTyper = AutoTyper(
			onFinished=self._onAutoTypingFinished,
			modifiersHeld=_modifiersHeld,
			onKey=keyboardSounds.play,
		)
		self._forceResumeUntil = 0
		inputCore.decide_executeGesture.register(self._decideExecuteGesture)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(VirtualTyperSettingsPanel)

	def terminate(self):
		inputCore.decide_executeGesture.unregister(self._decideExecuteGesture)
		self._autoTyper.cancel()
		self._editor.terminate()
		keyboardSounds.terminate()
		try:
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(VirtualTyperSettingsPanel)
		except ValueError:
			pass
		super().terminate()

	# Commands

	@script(
		# Translators: Description of a Virtual Typer command in the Input gestures dialog.
		description=_("Opens or closes the virtual typer, a hidden text editor that you only hear"),
		gesture="kb:NVDA+'",
	)
	def script_toggleTyper(self, gesture):
		if self._autoTyper.isRunning:
			# Translators: Spoken when the virtual typer cannot open because auto typing is running.
			ui.message(_("Auto typing is running. Pause or stop it first."))
		elif self._editor.isOpen:
			self._editor.close()
		else:
			self._editor.open()

	@script(
		# Translators: Description of a Virtual Typer command in the Input gestures dialog.
		description=_(
			"Types the clipboard text into the focused control one key at a time, like a person typing. "
			"Press again to pause, and again to resume.",
		),
		gesture="kb:NVDA+control+'",
	)
	def script_typeClipboard(self, gesture):
		typer = self._autoTyper
		if typer.isRunning:
			typer.pause()
		elif typer.pausedJob is not None:
			self._resumeAutoTyping()
		elif self._editor.isOpen:
			# Translators: Spoken when clipboard typing is requested while the virtual typer is open.
			ui.message(_("Close the virtual typer first"))
		else:
			text = getClipboardText()
			if text is not None:
				self._startAutoTyping(text)

	@script(
		# Translators: Description of a Virtual Typer command in the Input gestures dialog.
		description=_("Stops auto typing and forgets typing that was paused"),
		gesture="kb:NVDA+control+shift+'",
	)
	def script_cancelAutoTyping(self, gesture):
		typer = self._autoTyper
		if typer.isRunning:
			typer.cancel()
		elif typer.pausedJob is not None:
			typer.cancel()
			# Translators: Spoken when paused auto typing is cancelled.
			ui.message(_("Paused typing cancelled"))
		else:
			# Translators: Spoken when there is no auto typing to cancel.
			ui.message(_("Not auto typing"))

	# Keyboard capture

	def _decideExecuteGesture(self, gesture, **kwargs):
		"""Consumes keys meant for Virtual Typer before any other add-on or app can see them."""
		if not isinstance(gesture, keyboardHandler.KeyboardInputGesture):
			return True
		try:
			action = self._actionForGesture(gesture)
		except Exception:
			log.error("Virtual Typer: could not handle a key press", exc_info=True)
			return True
		if action is None:
			return True
		if gesture.speechEffectWhenExecuted == gesture.SPEECHEFFECT_CANCEL:
			queueHandler.queueFunction(queueHandler.eventQueue, speech.cancelSpeech)
		gesture._virtualTyperAction = action
		scriptHandler.queueScript(self._runQueuedAction, gesture)
		return False

	def _runQueuedAction(self, gesture):
		"""Runs the Virtual Typer action chosen for a key press."""
		action = getattr(gesture, "_virtualTyperAction", None)
		if action is not None:
			action(gesture)

	def _actionForGesture(self, gesture):
		"""Runs in NVDA's keyboard hook thread, so it only decides and leaves the work to the main thread."""
		if gesture.isModifier or inputCore.manager.isInputHelpActive:
			return None
		if self._autoTyper.isRunning:
			if gesture.vkCode == VK_ESCAPE and not gesture.generalizedModifiers:
				return self._stopAutoTypingFromEscape
			return None
		if not self._editor.isOpen or isLockScreenModeActive():
			return None
		if self._editor.shouldCapture(gesture):
			return self._editor.handleKey
		return None

	def _stopAutoTypingFromEscape(self, gesture):
		self._autoTyper.cancel()

	# Auto typing

	def _autoTypingSettings(self):
		conf = getConfig()
		return conf["charsPerSecond"], conf["naturalRhythm"], conf["typos"]

	def _startAutoTyping(self, text):
		self._autoTyper.cancel()
		if self._autoTyper.start(text, *self._autoTypingSettings()):
			tones.beep(660, 40)
			# Translators: Spoken when auto typing starts.
			ui.message(_("Typing. Press escape to stop."))
		else:
			# Translators: Spoken when there is no text to auto type.
			ui.message(_("Nothing to type"))

	def _resumeAutoTyping(self):
		job = self._autoTyper.pausedJob
		before = _textBeforeCaret()
		if before is None:
			startIndex, backspaces = job.nextIndex, 0
		else:
			point = findResumePoint(job.text, job.nextIndex, before)
			if point is None and time.monotonic() > self._forceResumeUntil:
				self._forceResumeUntil = time.monotonic() + FORCE_RESUME_SECONDS
				ui.message(
					# Translators: Spoken when the text before the cursor does not match the paused typing.
					_(
						"The text before the cursor does not match what was typed. "
						"Move to the end of the typed text, or press again to continue anyway.",
					),
				)
				return
			startIndex, backspaces = point or (job.nextIndex, 0)
		self._forceResumeUntil = 0
		if not self._autoTyper.resume(startIndex, backspaces, *self._autoTypingSettings()):
			return
		tones.beep(660, 40)
		if backspaces:
			# Translators: Spoken when resuming auto typing after erasing wrongly typed characters.
			message = _("Correcting {count} characters, then resuming").format(count=backspaces)
		elif startIndex < job.nextIndex:
			# Translators: Spoken when resuming auto typing finds characters that never arrived.
			message = _("{count} characters were missing. Resuming from there").format(
				count=job.nextIndex - startIndex,
			)
		else:
			# Translators: Spoken when auto typing resumes.
			message = _("Resuming")
		ui.message(message)

	def _onAutoTypingFinished(self, reason):
		queueHandler.queueFunction(queueHandler.eventQueue, self._announceAutoTypingFinished, reason)

	def _announceAutoTypingFinished(self, reason):
		if reason is FinishReason.DONE:
			tones.beep(1000, 40)
			# Translators: Spoken when auto typing has typed all the text.
			ui.message(_("Finished typing"))
		elif reason is FinishReason.PAUSED:
			tones.beep(440, 40)
			# Translators: Spoken when auto typing is paused.
			ui.message(_("Typing paused. Press NVDA+Control+apostrophe to resume."))
		elif reason is FinishReason.WINDOW_CHANGED:
			tones.beep(440, 40)
			# Translators: Spoken when auto typing pauses because another window became active.
			ui.message(_("Typing paused because the window changed. Press NVDA+Control+apostrophe to resume."))
		elif reason is FinishReason.STOPPED:
			# Translators: Spoken when the user stops auto typing.
			ui.message(_("Typing stopped"))
		else:
			# Translators: Spoken when auto typing fails.
			ui.message(_("Typing failed"))
