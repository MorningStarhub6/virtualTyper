"""The virtual typer: a hidden, speech-only editor with saved files, a file list and spoken prompts."""

import enum
import os
import time
from functools import partial

import addonHandler
import api
import characterProcessing
import config
import core
import inputCore
import speech
import tones
import ui
import winKernel
from logHandler import log

from .addonConfig import getConfig
from .documents import TITLE_AUTO, TITLE_FIXED, TITLE_PROVISIONAL, DocumentStore, firstLineTitle
from .keyInput import CharacterTranslator
from .keys import (
	PASS_THROUGH_KEYS,
	VK_BACK,
	VK_DELETE,
	VK_DOWN,
	VK_END,
	VK_ESCAPE,
	VK_F1,
	VK_F2,
	VK_F24,
	VK_HOME,
	VK_INSERT,
	VK_LEFT,
	VK_N,
	VK_NEXT,
	VK_PRIOR,
	VK_RETURN,
	VK_RIGHT,
	VK_TAB,
	VK_UP,
	VK_Y,
	Modifiers,
)
from .sounds import keyboardSounds, soundKindForCharacter
from .textBuffer import TextBuffer, isWordChar, normalizeNewlines

addonHandler.initTranslation()

PAGE_LINES = 10
LIST_PAGE_SIZE = 10
MAX_SPOKEN_DELETION = 200
AUTO_SAVE_DELAY_MS = 3000

#: NVDA reading commands that read the virtual typer instead of the screen while it is open.
NVDA_COMMANDS = (
	("kb(desktop):NVDA+upArrow", "readLine"),
	("kb(laptop):NVDA+l", "readLine"),
	("kb(desktop):NVDA+shift+upArrow", "readSelection"),
	("kb(laptop):NVDA+shift+s", "readSelection"),
	("kb(desktop):NVDA+downArrow", "readToEnd"),
	("kb(laptop):NVDA+a", "readToEnd"),
	("kb:NVDA+numpadDelete", "reportPosition"),
	("kb(laptop):NVDA+delete", "reportPosition"),
	("kb:NVDA+t", "reportTitle"),
)


class Mode(enum.Enum):
	CLOSED = "closed"
	EDIT = "edit"
	LIST = "list"
	CONFIRM = "confirm"
	INPUT = "input"


class _ConfirmPrompt:
	def __init__(self, question, onYes, onNo, onCancel, returnMode):
		self.question = question
		self.onYes = onYes
		self.onNo = onNo
		self.onCancel = onCancel
		self.returnMode = returnMode


class _InputPrompt:
	def __init__(self, label, buffer, onDone, onCancel, returnMode):
		self.label = label
		self.buffer = buffer
		self.onDone = onDone
		self.onCancel = onCancel
		self.returnMode = returnMode


def _ignore():
	pass


def getClipboardText():
	"""Returns the clipboard text, or None after telling the user there is none."""
	try:
		text = api.getClipData()
	except Exception:
		log.debug("Virtual Typer: could not read the clipboard", exc_info=True)
		text = ""
	if not text:
		# Translators: Spoken when the clipboard has no text.
		ui.message(_("There is no text on the clipboard"))
		return None
	return text


def _dateTitle():
	try:
		date = winKernel.GetDateFormatEx(winKernel.LOCALE_NAME_USER_DEFAULT, winKernel.DATE_LONGDATE, None, None)
		clock = winKernel.GetTimeFormatEx(winKernel.LOCALE_NAME_USER_DEFAULT, winKernel.TIME_NOSECONDS, None, None)
		return f"{date} {clock}"
	except Exception:
		return time.strftime("%Y-%m-%d %H:%M")


def _formatTimestamp(timestamp):
	try:
		return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))
	except (TypeError, ValueError, OverflowError, OSError):
		return ""


def _speakBlank():
	# Translators: Spoken for an empty line or the end of the virtual typer text.
	speech.speakMessage(_("blank"))


def _speakCharacter(ch):
	if not ch or ch == "\n":
		_speakBlank()
	else:
		speech.speakSpelling(ch)


def _speakLine(text):
	if not text or text.isspace():
		_speakBlank()
	else:
		speech.speakText(text)


def _describeCharacter(ch):
	try:
		return characterProcessing.processSpeechSymbol(speech.getCurrentLanguage(), ch)
	except Exception:
		return ch


def _speakSelectionMessage(message, text):
	if len(text) == 1:
		text = _describeCharacter(text)
	speech.speakSelectionMessage(message, text)


def _speakDeleted(deleted):
	if deleted == "\n":
		# Translators: Spoken when a line break is deleted in the virtual typer.
		speech.speakMessage(_("line break"))
	elif len(deleted) == 1 or not deleted.strip():
		speech.speakSpelling(deleted[:1])
	elif len(deleted) <= MAX_SPOKEN_DELETION:
		speech.speakText(deleted)
	else:
		# Translators: Spoken when a large amount of text is deleted in the virtual typer.
		speech.speakMessage(_("{count} characters deleted").format(count=len(deleted)))


class VirtualEditor:
	def __init__(self, storageFolder, onTypeOut, legacyDraftPath=None):
		"""
		@param storageFolder: Folder for saved files and the session.
		@param onTypeOut: Called with text when the user asks for it to be auto typed into the focused app.
		@param legacyDraftPath: The single text file used by version 1.0, imported once as an unsaved draft.
		"""
		self._store = DocumentStore(storageFolder)
		self._onTypeOut = onTypeOut
		self._translator = CharacterTranslator()
		self._mode = Mode.CLOSED
		self._prompt = None
		self._listIndex = 0
		self._autoSaveTimer = None
		self._saveErrorReported = False
		self._nvdaCommands = {
			inputCore.normalizeGestureIdentifier(identifier): name for identifier, name in NVDA_COMMANDS
		}
		self._setDocument(None, "")
		self._restoreSession(legacyDraftPath)

	# State

	@property
	def isOpen(self):
		return self._mode is not Mode.CLOSED

	@property
	def isDirty(self):
		return self._buffer.text != self._savedText

	@property
	def _active(self):
		"""The buffer that editing keys act on: the title prompt while it is open, otherwise the document."""
		return self._prompt.buffer if self._mode is Mode.INPUT else self._buffer

	def _setDocument(self, doc, savedText, bufferText=None, caret=None):
		self._doc = doc
		self._savedText = normalizeNewlines(savedText)
		self._buffer = TextBuffer(self._savedText if bufferText is None else bufferText)
		if caret is not None:
			self._buffer.caret = max(0, min(caret, len(self._buffer.text)))

	def _hasUnsavedWork(self):
		if self._doc is None:
			return bool(self._buffer.text.strip())
		return self.isDirty or self._titlePending()

	def _titlePending(self):
		"""True when an auto saved file still needs the title the user asked to type."""
		return (
			getConfig()["titleMode"] == "ask"
			and self._doc is not None
			and self._doc.get("titleSource") == TITLE_PROVISIONAL
		)

	def _needsTitleQuestion(self):
		return self._doc is None and getConfig()["titleMode"] == "ask" or self._titlePending()

	def _titleForSpeech(self):
		# Translators: The name of a virtual typer file that has not been saved yet.
		return self._doc["title"] if self._doc else _("new file")

	def _positionSummary(self):
		buf = self._buffer
		if not buf.text:
			return _("blank")
		# Translators: Reports the caret line in the virtual typer.
		return _("line {line} of {total}").format(line=buf.lineNumber(), total=buf.lineCount)

	# Session

	def _restoreSession(self, legacyDraftPath):
		session = self._store.session
		doc = self._store.get(session.get("documentId"))
		savedText = ""
		if doc is not None:
			try:
				savedText = self._store.read(doc)
			except OSError:
				log.warning("Virtual Typer: could not read the last open file", exc_info=True)
				doc = None
		draft = session.get("draft") if isinstance(session.get("draft"), str) else None
		caret = session.get("caret") if isinstance(session.get("caret"), int) else None
		legacyText = None
		if not session and legacyDraftPath:
			try:
				with open(legacyDraftPath, encoding="utf-8") as legacyFile:
					legacyText = legacyFile.read()
			except FileNotFoundError:
				pass
			except (OSError, UnicodeDecodeError):
				log.warning("Virtual Typer: could not import the old saved text", exc_info=True)
		self._setDocument(doc, savedText, legacyText or draft, caret)
		if legacyText is not None and self.saveSession():
			try:
				os.remove(legacyDraftPath)
			except OSError:
				log.warning("Virtual Typer: could not remove the old saved text", exc_info=True)

	def saveSession(self):
		"""Remembers the open file and any unsaved text for the next time NVDA starts."""
		buf = self._buffer
		try:
			self._store.saveSession(
				{
					"documentId": self._doc["id"] if self._doc else None,
					"draft": buf.text if self.isDirty else None,
					"caret": buf.caret,
				},
			)
			return True
		except OSError:
			log.warning("Virtual Typer: could not save the session", exc_info=True)
			return False

	def terminate(self):
		self._cancelAutoSave()
		if getConfig()["autoSave"] and self.isDirty:
			self._writeDocument(announce=False)
		self.saveSession()

	# Opening and closing

	def open(self):
		self._mode = Mode.EDIT
		self._prompt = None
		self._translator.reset()
		tones.beep(880, 40)
		# Translators: Spoken when the virtual typer opens.
		ui.message(
			_("Virtual typer, {title}, {position}").format(
				title=self._titleForSpeech(),
				position=self._positionSummary(),
			),
		)

	def close(self):
		"""Closes the typer, first saving or asking about unsaved changes."""
		if self._mode is Mode.CLOSED:
			return
		self._prompt = None
		self._mode = Mode.EDIT
		self._resolveUnsaved(self._finishClose)

	def _closeQuietly(self):
		self._mode = Mode.CLOSED
		self._prompt = None
		self._translator.reset()
		self._cancelAutoSave()
		self.saveSession()

	def _finishClose(self):
		self._closeQuietly()
		tones.beep(440, 40)
		# Translators: Spoken when the virtual typer closes.
		ui.message(_("Virtual typer closed"))

	# Saving

	def _resolveUnsaved(self, then):
		"""Saves or asks about unsaved changes as the settings say, then calls then()."""
		if not self._hasUnsavedWork():
			then()
			return
		if getConfig()["autoSave"]:
			self._saveThen(then, announce=False)
			return

		def save():
			self._saveThen(then, announce=True)

		def discard():
			self._discardChanges()
			then()

		self._confirm(
			# Translators: Asked before closing or switching files with unsaved changes.
			_("Save changes to {title}?").format(title=self._titleForSpeech()),
			onYes=save,
			onNo=discard,
		)

	def _saveThen(self, then, announce):
		"""Saves the file, asking for its title first when the settings say so, then calls then()."""
		if not self._needsTitleQuestion():
			if self._writeDocument(announce):
				then()
			return
		suggested = firstLineTitle(self._buffer.text) or _dateTitle()

		def onTitle(title):
			if self._writeDocument(announce, title=title or suggested):
				then()

		# Translators: Label of the prompt for a file title in the virtual typer.
		self._askText(_("Title"), suggested, onTitle)

	def _writeDocument(self, announce, title=None):
		conf = getConfig()
		doc = self._doc
		text = self._buffer.text
		if doc is None and not text.strip():
			return True
		if title is not None:
			source = TITLE_FIXED
		elif doc is not None:
			source, title = doc.get("titleSource", TITLE_FIXED), doc["title"]
			if source in (TITLE_AUTO, TITLE_PROVISIONAL):
				title = firstLineTitle(text) or title
		elif conf["titleMode"] == "date":
			title, source = _dateTitle(), TITLE_FIXED
		else:
			title = firstLineTitle(text) or _dateTitle()
			source = TITLE_AUTO if conf["titleMode"] == "firstLine" else TITLE_PROVISIONAL
		try:
			self._doc = self._store.save(
				text,
				title,
				source,
				docId=doc["id"] if doc else None,
				caret=self._buffer.caret,
				maxDocuments=conf["maxDocuments"],
			)
		except OSError:
			log.error("Virtual Typer: could not save a file", exc_info=True)
			if announce or not self._saveErrorReported:
				# Translators: Spoken when a virtual typer file cannot be saved.
				ui.message(_("Could not save the file"))
			self._saveErrorReported = True
			return False
		self._saveErrorReported = False
		self._savedText = text
		if announce:
			# Translators: Spoken after saving a virtual typer file.
			ui.message(_("Saved {title}").format(title=title))
		return True

	def _discardChanges(self):
		if self._doc is not None:
			self._setDocument(self._doc, self._savedText)
		else:
			self._setDocument(None, "")

	def _onDocumentChanged(self):
		if getConfig()["autoSave"] and self._autoSaveTimer is None:
			self._autoSaveTimer = core.callLater(AUTO_SAVE_DELAY_MS, self._autoSave)

	def _autoSave(self):
		self._autoSaveTimer = None
		if getConfig()["autoSave"] and self.isDirty:
			self._writeDocument(announce=False)

	def _cancelAutoSave(self):
		if self._autoSaveTimer is not None:
			self._autoSaveTimer.Stop()
			self._autoSaveTimer = None

	def _saveCommand(self):
		if self._doc is None and not self._buffer.text.strip():
			# Translators: Spoken when there is nothing to save in the virtual typer.
			ui.message(_("Nothing to save"))
		elif not self._hasUnsavedWork():
			# Translators: Spoken when the virtual typer file has no unsaved changes.
			ui.message(_("No changes to save"))
		else:
			self._saveThen(_ignore, announce=True)

	def _newDocument(self):
		def start():
			self._setDocument(None, "")
			# Translators: Spoken after starting a new virtual typer file.
			ui.message(_("New file"))

		self._resolveUnsaved(start)

	# Prompts

	def _confirm(self, question, onYes, onNo, onCancel=None):
		self._prompt = _ConfirmPrompt(question, onYes, onNo, onCancel or self._cancelled, self._mode)
		self._mode = Mode.CONFIRM
		self._speakConfirm()

	def _speakConfirm(self):
		# Translators: Added after a yes or no question in the virtual typer.
		keysHint = _("Y for yes, N for no, Escape to cancel.")
		ui.message(f"{self._prompt.question} {keysHint}")

	def _askText(self, label, initial, onDone, onCancel=None):
		buffer = TextBuffer(initial)
		buffer.selectAll()
		self._prompt = _InputPrompt(label, buffer, onDone, onCancel or self._cancelled, self._mode)
		self._mode = Mode.INPUT
		self._translator.reset()
		self._speakInputPrompt()

	def _speakInputPrompt(self):
		prompt = self._prompt
		ui.message(
			# Translators: Spoken for a text prompt; {label} says what to type and {text} is the current text.
			_("{label}: {text}. Type and press Enter, or Escape to cancel.").format(
				label=prompt.label,
				text=prompt.buffer.text or _("blank"),
			),
		)

	def _endPrompt(self):
		prompt, self._prompt = self._prompt, None
		self._mode = prompt.returnMode
		return prompt

	def _cancelled(self):
		# Translators: Spoken when a virtual typer prompt is cancelled.
		ui.message(_("Cancelled"))
		if self._mode is Mode.LIST:
			self._speakListItem()

	# Keyboard

	def shouldCapture(self, gesture):
		"""Runs in NVDA's keyboard hook thread: decides which keys the typer takes from the system."""
		if self._mode is Mode.CLOSED:
			return False
		mods = Modifiers(gesture)
		vk = gesture.vkCode
		if mods.windows:
			return False
		if mods.nvda:
			return self._nvdaCommandFor(gesture) is not None
		if vk in PASS_THROUGH_KEYS:
			return False
		if mods.alt and not mods.control and vk in (VK_TAB, VK_ESCAPE):
			return False
		if mods.control and not mods.alt and vk == VK_ESCAPE:
			return False
		return True

	def _nvdaCommandFor(self, gesture):
		for identifier in gesture.normalizedIdentifiers:
			command = self._nvdaCommands.get(identifier)
			if command:
				return command
		return None

	def handleKey(self, gesture):
		"""Runs on NVDA's main thread for each key that shouldCapture took."""
		if self._mode is Mode.CLOSED:
			return
		mods = Modifiers(gesture)
		changeCount = self._buffer.changeCount
		if mods.nvda:
			command = self._nvdaCommandFor(gesture)
			if command:
				self._runNvdaCommand(command)
		elif self._mode is Mode.EDIT:
			self._handleEditKey(gesture, mods)
		elif self._mode is Mode.LIST:
			self._handleListKey(gesture, mods)
		elif self._mode is Mode.CONFIRM:
			self._handleConfirmKey(gesture, mods)
		elif self._mode is Mode.INPUT:
			self._handleInputKey(gesture, mods)
		if self._buffer.changeCount != changeCount:
			self._onDocumentChanged()

	def _runNvdaCommand(self, command):
		if self._mode is Mode.CONFIRM:
			self._speakConfirm()
		elif self._mode is Mode.LIST:
			if command == "reportTitle":
				ui.message(_("Saved files"))
			else:
				self._speakListItem(details=command == "readLine")
		elif self._mode is Mode.INPUT and command == "reportTitle":
			self._speakInputPrompt()
		else:
			{
				"readLine": self._readLine,
				"readSelection": self._readSelection,
				"readToEnd": self._readToEnd,
				"reportPosition": self._reportPosition,
				"reportTitle": self._reportTitle,
			}[command]()

	def _handleEditKey(self, gesture, mods):
		vk = gesture.vkCode
		shift = mods.shift
		action = None
		if mods.control and not mods.alt:
			action = {
				VK_RETURN: self._typeOut,
				VK_TAB: self._openList,
				ord("S"): self._saveCommand,
				ord("N"): self._newDocument,
			}.get(vk)
		elif mods.plain:
			if vk == VK_ESCAPE:
				action = self.close
			elif vk == VK_F1:
				action = self._speakEditHelp
			elif vk == VK_RETURN:
				action = partial(self._typeText, "\n")
			elif vk == VK_TAB:
				action = _ignore if shift else partial(self._typeText, "\t")
			elif vk in (VK_UP, VK_DOWN, VK_PRIOR, VK_NEXT):
				lines = PAGE_LINES if vk in (VK_PRIOR, VK_NEXT) else 1
				action = partial(self._moveLine, lines if vk in (VK_DOWN, VK_NEXT) else -lines, shift)
		if action is not None:
			self._translator.reset()
			action()
		else:
			self._handleTextKey(gesture, mods)

	def _handleInputKey(self, gesture, mods):
		vk = gesture.vkCode
		if mods.plain and vk == VK_RETURN:
			prompt = self._endPrompt()
			prompt.onDone(" ".join(prompt.buffer.text.split()))
		elif mods.plain and vk == VK_ESCAPE:
			self._endPrompt().onCancel()
		elif mods.plain and vk in (VK_UP, VK_DOWN):
			self._readLine()
		elif mods.plain and vk in (VK_TAB, VK_F1):
			self._translator.reset()
			self._speakInputPrompt()
		else:
			self._handleTextKey(gesture, mods)

	def _handleConfirmKey(self, gesture, mods):
		vk = gesture.vkCode
		answers = {VK_Y: "onYes", VK_N: "onNo", VK_ESCAPE: "onCancel"}
		if mods.plain and vk in answers:
			prompt = self._endPrompt()
			getattr(prompt, answers[vk])()
		else:
			self._speakConfirm()

	def _handleTextKey(self, gesture, mods):
		"""Editing keys shared by the document and the title prompt."""
		vk = gesture.vkCode
		action = self._textKeyAction(vk, mods)
		if action is None and mods.control == mods.alt and not VK_F1 <= vk <= VK_F24:
			self._typeKey(gesture, altGr=mods.control and mods.alt)
			return
		self._translator.reset()
		if action is not None:
			action()

	def _textKeyAction(self, vk, mods):
		shift = mods.shift
		if mods.control and not mods.alt:
			return {
				VK_LEFT: partial(self._moveWord, -1, shift),
				VK_RIGHT: partial(self._moveWord, 1, shift),
				VK_HOME: partial(self._moveDocumentBoundary, False, shift),
				VK_END: partial(self._moveDocumentBoundary, True, shift),
				VK_BACK: partial(self._backspace, True),
				VK_DELETE: partial(self._deleteForward, True),
				VK_INSERT: self._copy,
				ord("C"): self._copy,
				ord("A"): self._selectAll,
				ord("X"): self._cut,
				ord("V"): self._paste,
				ord("Z"): self._redo if shift else self._undo,
				ord("Y"): self._redo,
			}.get(vk, _ignore)
		if mods.alt:
			return None if mods.control else _ignore
		if vk == VK_LEFT:
			return partial(self._moveCharacter, -1, shift)
		if vk == VK_RIGHT:
			return partial(self._moveCharacter, 1, shift)
		if vk == VK_HOME:
			return partial(self._moveLineBoundary, False, shift)
		if vk == VK_END:
			return partial(self._moveLineBoundary, True, shift)
		if vk == VK_BACK:
			return partial(self._backspace, False)
		if vk == VK_DELETE:
			return self._cut if shift else partial(self._deleteForward, False)
		if vk == VK_INSERT:
			return self._paste if shift else _ignore
		if vk in (VK_UP, VK_DOWN, VK_PRIOR, VK_NEXT, VK_TAB, VK_RETURN, VK_ESCAPE):
			return _ignore
		return None

	# Typing and deleting

	def _typeKey(self, gesture, altGr):
		try:
			threadId = api.getFocusObject().windowThreadID
		except Exception:
			threadId = 0
		text = self._translator.translate(
			gesture.vkCode,
			gesture.scanCode,
			shift=Modifiers(gesture).shift,
			altGr=altGr,
			threadId=threadId,
		)
		if text and self._mode is Mode.INPUT:
			text = text.replace("\n", " ").replace("\t", " ")
		if text:
			self._typeText(text)

	def _typeText(self, text):
		buf = self._active
		buf.typeText(text)
		if getConfig()["soundsInTyper"]:
			keyboardSounds.play(soundKindForCharacter(text[0]))
		keyboardConf = config.conf["keyboard"]
		if keyboardConf["speakTypedWords"] and not isWordChar(text[0]):
			word = buf.wordBefore(buf.caret - len(text))
			if word:
				speech.speakText(word)
		if keyboardConf["speakTypedCharacters"] and text.isprintable():
			speech.speakSpelling(text)

	def _playDeleteSound(self):
		if getConfig()["soundsInTyper"]:
			keyboardSounds.play("delete")

	def _backspace(self, word):
		deleted = self._active.backspace(word)
		if deleted:
			self._playDeleteSound()
			_speakDeleted(deleted)

	def _deleteForward(self, word):
		buf = self._active
		hadSelection = buf.hasSelection
		deleted = buf.deleteForward(word)
		if not deleted:
			return
		self._playDeleteSound()
		if hadSelection:
			_speakDeleted(deleted)
		elif word:
			self._reportWord()
		else:
			_speakCharacter(buf.charAt())

	# Caret movement

	def _move(self, select, moveFunc, report):
		buf = self._active
		oldRange = buf.selectionRange
		moveFunc(buf)
		if select:
			self._reportSelectionChange(oldRange, buf.selectionRange)
		else:
			report()

	def _moveCharacter(self, direction, select):
		self._move(select, lambda buf: buf.moveCharacter(direction, select), self._reportCharacter)

	def _moveWord(self, direction, select):
		self._move(select, lambda buf: buf.moveWord(direction, select), self._reportWord)

	def _moveLine(self, count, select):
		self._move(select, lambda buf: buf.moveLine(count, select), self._readLine)

	def _moveLineBoundary(self, toEnd, select):
		self._move(select, lambda buf: buf.moveLineBoundary(toEnd, select), self._reportCharacter)

	def _moveDocumentBoundary(self, toEnd, select):
		self._move(select, lambda buf: buf.moveDocumentBoundary(toEnd, select), self._readLine)

	def _reportCharacter(self):
		_speakCharacter(self._active.charAt())

	def _reportWord(self):
		word = self._active.wordAt()
		stripped = word.strip()
		if len(stripped) > 1:
			speech.speakText(word)
		else:
			_speakCharacter(stripped or word[:1])

	def _reportSelectionChange(self, oldRange, newRange):
		text = self._active.text
		(oldStart, oldEnd), (newStart, newEnd) = oldRange, newRange
		if oldRange == newRange:
			return
		# Translators: Spoken when text is selected in the virtual typer; %s is the text.
		selectedMessage = _("%s selected")
		if newStart <= oldStart and newEnd >= oldEnd:
			_speakSelectionMessage(selectedMessage, text[newStart:oldStart] + text[oldEnd:newEnd])
		elif oldStart <= newStart and oldEnd >= newEnd:
			# Translators: Spoken when text is unselected in the virtual typer; %s is the text.
			_speakSelectionMessage(_("%s unselected"), text[oldStart:newStart] + text[newEnd:oldEnd])
		else:
			_speakSelectionMessage(selectedMessage, text[newStart:newEnd])

	# Reading

	def _readLine(self):
		_speakLine(self._active.lineText())

	def _readSelection(self):
		buf = self._active
		if buf.hasSelection:
			# Translators: Reports the selected text in the virtual typer; %s is the text.
			_speakSelectionMessage(_("selected %s"), buf.selectedText)
		else:
			# Translators: Spoken when there is no selection in the virtual typer.
			ui.message(_("No selection"))

	def _readToEnd(self):
		buf = self._active
		_speakLine(buf.text[buf.caret :])

	def _reportPosition(self):
		buf = self._active
		ui.message(
			# Translators: Reports the caret position and size of the virtual typer text.
			_("Line {line} of {lines}, column {column}. Words {words}, characters {characters}").format(
				line=buf.lineNumber(),
				lines=buf.lineCount,
				column=buf.columnNumber(),
				words=buf.wordCount,
				characters=len(buf.text),
			),
		)

	def _reportTitle(self):
		if self._doc is None:
			# Translators: Reported for a virtual typer file that has never been saved.
			state = _("not saved")
		elif self._hasUnsavedWork():
			# Translators: Reported for a virtual typer file with unsaved changes.
			state = _("unsaved changes")
		else:
			# Translators: Reported for a virtual typer file with no unsaved changes.
			state = _("saved")
		ui.message(f"{self._titleForSpeech()}, {state}")

	def _speakEditHelp(self):
		if config.conf["keyboard"]["keyboardLayout"] == "laptop":
			# Translators: Part of the virtual typer help for the laptop keyboard layout.
			reading = _("NVDA+L reads the line, NVDA+A reads to the end, NVDA+Delete reports the position.")
		else:
			# Translators: Part of the virtual typer help for the desktop keyboard layout.
			reading = _(
				"NVDA+Up arrow reads the line, NVDA+Down arrow reads to the end, "
				"NVDA+Numpad Delete reports the position.",
			)
		ui.message(
			" ".join(
				(
					# Translators: Part of the virtual typer help.
					_("Virtual typer help. Type as you would in Notepad; nothing is shown on screen."),
					# Translators: Part of the virtual typer help.
					_("Escape closes. Control+S saves, Control+N starts a new file, Control+Tab lists saved files."),
					# Translators: Part of the virtual typer help.
					_("Control+Enter types the text into the focused app."),
					# Translators: Part of the virtual typer help.
					_("Control+C, X and V copy, cut and paste. Control+Z undoes and Control+Y redoes."),
					reading,
				),
			),
		)

	# Clipboard, selection and undo

	def _selectAll(self):
		buf = self._active
		buf.selectAll()
		if buf.text:
			_speakSelectionMessage(_("%s selected"), buf.text)
		else:
			_speakBlank()

	def _copy(self, cut=False):
		buf = self._active
		if not buf.hasSelection:
			ui.message(_("No selection"))
			return
		if not api.copyToClip(buf.selectedText.replace("\n", "\r\n")):
			# Translators: Spoken when copying to the clipboard fails.
			ui.message(_("Could not copy to the clipboard"))
			return
		if cut:
			buf.deleteSelection()
			# Translators: Spoken after cutting text in the virtual typer.
			ui.message(_("Cut"))
		else:
			# Translators: Spoken after copying text in the virtual typer.
			ui.message(_("Copied"))

	def _cut(self):
		self._copy(cut=True)

	def _paste(self):
		text = getClipboardText()
		if text is None:
			return
		if self._mode is Mode.INPUT:
			text = " ".join(text.split())
		self._active.insertText(text)
		# Translators: Spoken after pasting into the virtual typer.
		ui.message(_("Pasted"))

	def _undo(self):
		if self._active.undo():
			# Translators: Spoken after undoing in the virtual typer.
			ui.message(_("Undo"))
		else:
			# Translators: Spoken when there is nothing to undo in the virtual typer.
			ui.message(_("Nothing to undo"))

	def _redo(self):
		if self._active.redo():
			# Translators: Spoken after redoing in the virtual typer.
			ui.message(_("Redo"))
		else:
			# Translators: Spoken when there is nothing to redo in the virtual typer.
			ui.message(_("Nothing to redo"))

	def _typeOut(self):
		buf = self._buffer
		text = buf.selectedText if buf.hasSelection else buf.text
		if not text.strip():
			# Translators: Spoken when there is no text to auto type.
			ui.message(_("Nothing to type"))
			return
		if getConfig()["autoSave"] and self.isDirty:
			self._writeDocument(announce=False)
		self._closeQuietly()
		self._onTypeOut(text)

	# Saved files list

	@property
	def _documents(self):
		return self._store.documents

	def _isCurrent(self, doc):
		return self._doc is not None and doc["id"] == self._doc["id"]

	def _openList(self):
		docs = self._documents
		if not docs:
			# Translators: Spoken when there are no saved virtual typer files.
			ui.message(_("No saved files"))
			return
		self._listIndex = next((index for index, doc in enumerate(docs) if not self._isCurrent(doc)), 0)
		self._mode = Mode.LIST
		# Translators: Spoken when the list of saved virtual typer files opens.
		ui.message(_("Saved files"))
		self._speakListItem()

	def _selectedDocument(self):
		docs = self._documents
		if not docs:
			return None
		self._listIndex = max(0, min(self._listIndex, len(docs) - 1))
		return docs[self._listIndex]

	def _speakListItem(self, details=False):
		doc = self._selectedDocument()
		if doc is None:
			self._mode = Mode.EDIT
			ui.message(_("No saved files"))
			return
		parts = [doc["title"]]
		if self._isCurrent(doc):
			# Translators: Marks the file that is open in the virtual typer, in the saved files list.
			parts.append(_("open"))
		# Translators: Position of a file in the saved files list.
		parts.append(_("{position} of {count}").format(position=self._listIndex + 1, count=len(self._documents)))
		if details:
			# Translators: When a virtual typer file was last saved.
			parts.append(_("saved {time}").format(time=_formatTimestamp(doc.get("modified"))))
		ui.message(", ".join(parts))

	def _handleListKey(self, gesture, mods):
		vk = gesture.vkCode
		self._translator.reset()
		if mods.control and not mods.alt and vk == VK_TAB:
			self._moveInList(-1 if mods.shift else 1, wrap=True)
			return
		if not mods.plain:
			return
		count = len(self._documents)
		listKeys = {
			VK_DOWN: partial(self._moveInList, 1),
			VK_UP: partial(self._moveInList, -1),
			VK_NEXT: partial(self._moveInList, LIST_PAGE_SIZE),
			VK_PRIOR: partial(self._moveInList, -LIST_PAGE_SIZE),
			VK_HOME: partial(self._moveInList, -count),
			VK_END: partial(self._moveInList, count),
			VK_RETURN: self._openSelected,
			VK_DELETE: self._deleteSelected,
			VK_F2: self._renameSelected,
			VK_ESCAPE: self._leaveList,
			VK_F1: self._speakListHelp,
		}
		action = listKeys.get(vk)
		if action is not None:
			action()
			return
		text = self._translator.translate(vk, gesture.scanCode, shift=mods.shift)
		self._translator.reset()
		if text and text.strip():
			self._jumpToTitleStartingWith(text.strip()[0])

	def _moveInList(self, step, wrap=False):
		count = len(self._documents)
		if not count:
			return
		index = self._listIndex + step
		self._listIndex = index % count if wrap else max(0, min(index, count - 1))
		self._speakListItem()

	def _jumpToTitleStartingWith(self, ch):
		docs = self._documents
		ch = ch.casefold()
		for offset in range(1, len(docs) + 1):
			index = (self._listIndex + offset) % len(docs)
			if docs[index]["title"].casefold().startswith(ch):
				self._listIndex = index
				break
		self._speakListItem()

	def _leaveList(self):
		self._mode = Mode.EDIT
		# Translators: Spoken when going back from the saved files list to the open file.
		ui.message(_("Back to {title}").format(title=self._titleForSpeech()))

	def _speakListHelp(self):
		ui.message(
			# Translators: Help for the saved files list in the virtual typer.
			_(
				"Saved files help. Up and Down arrows or Control+Tab move, Enter opens, Delete deletes, "
				"F2 renames, Escape goes back. Type a letter to jump to a title.",
			),
		)

	def _openSelected(self):
		doc = self._selectedDocument()
		if doc is None:
			return
		if self._isCurrent(doc):
			self._mode = Mode.EDIT
			ui.message(f"{self._titleForSpeech()}, {self._positionSummary()}")
			return

		def load():
			try:
				if self._store.get(doc["id"]) is None:
					raise FileNotFoundError(doc["file"])
				text = self._store.read(doc)
			except OSError:
				log.warning("Virtual Typer: could not open a saved file", exc_info=True)
				self._mode = Mode.EDIT
				# Translators: Spoken when a saved virtual typer file cannot be opened.
				ui.message(_("Could not open {title}").format(title=doc["title"]))
				return
			self._setDocument(doc, text, caret=doc.get("caret"))
			self._mode = Mode.EDIT
			self.saveSession()
			ui.message(f"{self._titleForSpeech()}, {self._positionSummary()}")

		self._resolveUnsaved(load)

	def _deleteSelected(self):
		doc = self._selectedDocument()
		if doc is None:
			return

		def delete():
			try:
				self._store.delete(doc["id"])
			except OSError:
				log.warning("Virtual Typer: could not delete a saved file", exc_info=True)
				# Translators: Spoken when a saved virtual typer file cannot be deleted.
				ui.message(_("Could not delete the file"))
				return
			if self._isCurrent(doc):
				# The open text stays, now as an unsaved new file.
				self._doc = None
				self._savedText = ""
			# Translators: Spoken after deleting a saved virtual typer file.
			ui.message(_("Deleted"))
			self._speakListItem()

		# Translators: Asked before deleting a saved virtual typer file.
		self._confirm(_("Delete {title}?").format(title=doc["title"]), onYes=delete, onNo=self._speakListItem)

	def _renameSelected(self):
		doc = self._selectedDocument()
		if doc is None:
			return

		def rename(title):
			if title:
				try:
					self._store.rename(doc["id"], title)
				except OSError:
					log.warning("Virtual Typer: could not rename a saved file", exc_info=True)
			self._speakListItem()

		# Translators: Label of the prompt for renaming a saved virtual typer file.
		self._askText(_("New title"), doc["title"], rename)
