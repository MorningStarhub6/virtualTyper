"""Plain text editing model for the virtual typer.

It has no NVDA dependencies so it can be unit tested with plain Python.
"""

import unicodedata

UNDO_LIMIT = 500


def _charClass(ch):
	if ch == "\n":
		return "newline"
	if ch in " \t":
		return "space"
	if ch == "_" or unicodedata.category(ch)[0] in "LMN":
		return "word"
	return "punctuation"


def isWordChar(ch):
	return bool(ch) and _charClass(ch) == "word"


def normalizeNewlines(text):
	return text.replace("\r\n", "\n").replace("\r", "\n")


class TextBuffer:
	"""A multi-line text with a caret, an optional selection and undo history."""

	def __init__(self, text=""):
		self.text = normalizeNewlines(text)
		self.caret = len(self.text)
		self.anchor = None
		self._goalColumn = None
		self._undoStack = []
		self._redoStack = []
		self._lastEditKind = None
		#: Increases on every change to the text, so callers can tell whether an action edited it.
		self.changeCount = 0

	# Selection

	@property
	def hasSelection(self):
		return self.anchor is not None and self.anchor != self.caret

	@property
	def selectionRange(self):
		if not self.hasSelection:
			return (self.caret, self.caret)
		return (min(self.anchor, self.caret), max(self.anchor, self.caret))

	@property
	def selectedText(self):
		start, end = self.selectionRange
		return self.text[start:end]

	def selectAll(self):
		self.anchor = 0
		self.caret = len(self.text)
		self._goalColumn = None
		self._lastEditKind = None

	# Lines, characters and words

	def _pos(self, pos):
		return self.caret if pos is None else pos

	def lineStart(self, pos=None):
		return self.text.rfind("\n", 0, self._pos(pos)) + 1

	def lineEnd(self, pos=None):
		end = self.text.find("\n", self._pos(pos))
		return len(self.text) if end == -1 else end

	def lineText(self, pos=None):
		return self.text[self.lineStart(pos) : self.lineEnd(pos)]

	def lineNumber(self, pos=None):
		return self.text.count("\n", 0, self._pos(pos)) + 1

	@property
	def lineCount(self):
		return self.text.count("\n") + 1

	def columnNumber(self, pos=None):
		pos = self._pos(pos)
		return pos - self.lineStart(pos) + 1

	@property
	def wordCount(self):
		return len(self.text.split())

	def charAt(self, pos=None):
		pos = self._pos(pos)
		return self.text[pos] if 0 <= pos < len(self.text) else ""

	def nextWordStart(self, pos=None):
		text = self.text
		pos = self._pos(pos)
		length = len(text)
		if pos >= length:
			return length
		cls = _charClass(text[pos])
		if cls == "newline":
			return pos + 1
		if cls != "space":
			while pos < length and _charClass(text[pos]) == cls:
				pos += 1
		while pos < length and _charClass(text[pos]) == "space":
			pos += 1
		return pos

	def previousWordStart(self, pos=None):
		text = self.text
		pos = self._pos(pos)
		if pos <= 0:
			return 0
		pos -= 1
		while pos > 0 and _charClass(text[pos]) == "space":
			pos -= 1
		cls = _charClass(text[pos])
		if cls == "newline":
			return pos
		while pos > 0 and _charClass(text[pos - 1]) == cls:
			pos -= 1
		return pos

	def wordAt(self, pos=None):
		pos = self._pos(pos)
		return self.text[pos : self.nextWordStart(pos)]

	def wordBefore(self, pos=None):
		"""Returns the run of word characters that ends at pos."""
		end = self._pos(pos)
		start = end
		while start > 0 and isWordChar(self.text[start - 1]):
			start -= 1
		return self.text[start:end]

	# Caret movement

	def _moveTo(self, pos, select, keepGoalColumn=False):
		pos = max(0, min(pos, len(self.text)))
		if select:
			if self.anchor is None:
				self.anchor = self.caret
		else:
			self.anchor = None
		self.caret = pos
		if not keepGoalColumn:
			self._goalColumn = None
		self._lastEditKind = None

	def moveCharacter(self, direction, select=False):
		if not select and self.hasSelection:
			start, end = self.selectionRange
			self._moveTo(start if direction < 0 else end, False)
			return
		self._moveTo(self.caret + direction, select)

	def moveWord(self, direction, select=False):
		if direction > 0:
			self._moveTo(self.nextWordStart(), select)
		else:
			self._moveTo(self.previousWordStart(), select)

	def moveLine(self, count, select=False):
		"""Moves the caret count lines down (or up when negative), keeping the column. Returns False at the edge."""
		start = self.lineStart()
		goal = self._goalColumn if self._goalColumn is not None else self.caret - start
		target = start
		for _ in range(abs(count)):
			if count > 0:
				end = self.lineEnd(target)
				if end >= len(self.text):
					break
				target = end + 1
			else:
				if target == 0:
					break
				target = self.lineStart(target - 1)
		if target == start:
			return False
		self._moveTo(min(target + goal, self.lineEnd(target)), select, keepGoalColumn=True)
		self._goalColumn = goal
		return True

	def moveLineBoundary(self, toEnd, select=False):
		self._moveTo(self.lineEnd() if toEnd else self.lineStart(), select)

	def moveDocumentBoundary(self, toEnd, select=False):
		self._moveTo(len(self.text) if toEnd else 0, select)

	# Editing

	def _recordUndo(self, kind, merge):
		if not merge:
			self._undoStack.append((self.text, self.caret, self.anchor))
			if len(self._undoStack) > UNDO_LIMIT:
				del self._undoStack[0]
		self._redoStack.clear()
		self._lastEditKind = kind

	def _replaceRange(self, start, end, newText):
		self.text = self.text[:start] + newText + self.text[end:]
		self.caret = start + len(newText)
		self.anchor = None
		self._goalColumn = None
		self.changeCount += 1

	def typeText(self, newText):
		"""Inserts typed text. Consecutive typing is undone one word at a time."""
		if not newText:
			return
		startsWord = not newText[0].isspace()
		afterSpace = self.caret > 0 and self.text[self.caret - 1].isspace()
		merge = self._lastEditKind == "type" and not self.hasSelection and not (startsWord and afterSpace)
		self._recordUndo("type", merge)
		start, end = self.selectionRange
		self._replaceRange(start, end, newText)

	def insertText(self, newText):
		"""Inserts a block of text such as a paste, as a single undo step."""
		newText = normalizeNewlines(newText)
		if not newText:
			return
		self._recordUndo("insert", False)
		start, end = self.selectionRange
		self._replaceRange(start, end, newText)

	def deleteSelection(self):
		if not self.hasSelection:
			return ""
		start, end = self.selectionRange
		deleted = self.text[start:end]
		self._recordUndo("deleteSelection", False)
		self._replaceRange(start, end, "")
		return deleted

	def backspace(self, word=False):
		"""Deletes before the caret and returns the deleted text."""
		if self.hasSelection:
			return self.deleteSelection()
		if self.caret == 0:
			return ""
		start = self.previousWordStart() if word else self.caret - 1
		kind = "backspaceWord" if word else "backspace"
		self._recordUndo(kind, kind == "backspace" and self._lastEditKind == "backspace")
		deleted = self.text[start : self.caret]
		self._replaceRange(start, self.caret, "")
		return deleted

	def deleteForward(self, word=False):
		"""Deletes after the caret and returns the deleted text."""
		if self.hasSelection:
			return self.deleteSelection()
		if self.caret >= len(self.text):
			return ""
		end = self.nextWordStart() if word else self.caret + 1
		kind = "deleteWord" if word else "delete"
		self._recordUndo(kind, kind == "delete" and self._lastEditKind == "delete")
		deleted = self.text[self.caret : end]
		self._replaceRange(self.caret, end, "")
		return deleted

	def undo(self):
		if not self._undoStack:
			return False
		self._redoStack.append((self.text, self.caret, self.anchor))
		self.text, self.caret, self.anchor = self._undoStack.pop()
		self._goalColumn = None
		self._lastEditKind = None
		self.changeCount += 1
		return True

	def redo(self):
		if not self._redoStack:
			return False
		self._undoStack.append((self.text, self.caret, self.anchor))
		self.text, self.caret, self.anchor = self._redoStack.pop()
		self._goalColumn = None
		self._lastEditKind = None
		self.changeCount += 1
		return True
