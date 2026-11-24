import unittest

import nvdaStubs

nvdaStubs.install()

from virtualTyper.textBuffer import TextBuffer  # noqa: E402


class TestTextBuffer(unittest.TestCase):
	def test_typingAndLines(self):
		buf = TextBuffer()
		buf.typeText("hello")
		buf.typeText("\n")
		buf.typeText("world")
		self.assertEqual(buf.text, "hello\nworld")
		self.assertEqual(buf.lineNumber(), 2)
		self.assertEqual(buf.lineCount, 2)
		self.assertEqual(buf.lineText(), "world")
		self.assertEqual(buf.columnNumber(), 6)

	def test_newlinesAreNormalized(self):
		buf = TextBuffer("a\r\nb\rc")
		self.assertEqual(buf.text, "a\nb\nc")
		buf.insertText("x\r\ny")
		self.assertEqual(buf.text, "a\nb\ncx\ny")

	def test_upAndDownKeepColumn(self):
		buf = TextBuffer("abcdef\nab\nabcdef")
		buf.caret = 5
		self.assertTrue(buf.moveLine(1))
		self.assertEqual(buf.caret, 9)
		self.assertTrue(buf.moveLine(1))
		self.assertEqual(buf.caret, 15)
		self.assertFalse(buf.moveLine(1))
		self.assertEqual(buf.caret, 15)
		buf.moveLine(-2)
		self.assertEqual(buf.caret, 5)
		self.assertFalse(buf.moveLine(-1))

	def test_pageMovesStopAtEdges(self):
		buf = TextBuffer("1\n2\n3")
		buf.caret = 0
		self.assertTrue(buf.moveLine(10))
		self.assertEqual(buf.lineNumber(), 3)

	def test_wordMovement(self):
		buf = TextBuffer("hello, big world\nnext")
		buf.caret = 0
		stops = []
		for _ in range(6):
			buf.moveWord(1)
			stops.append(buf.caret)
		self.assertEqual(stops, [5, 7, 11, 16, 17, 21])
		backStops = []
		for _ in range(6):
			buf.moveWord(-1)
			backStops.append(buf.caret)
		self.assertEqual(backStops, [17, 16, 11, 7, 5, 0])

	def test_wordAtAndBefore(self):
		buf = TextBuffer("one two")
		self.assertEqual(buf.wordAt(0), "one ")
		self.assertEqual(buf.wordBefore(3), "one")
		self.assertEqual(buf.wordBefore(), "two")

	def test_selectionAndCollapse(self):
		buf = TextBuffer("abcdef")
		buf.caret = 2
		buf.moveCharacter(1, select=True)
		buf.moveCharacter(1, select=True)
		self.assertEqual(buf.selectedText, "cd")
		buf.moveCharacter(-1)
		self.assertEqual(buf.caret, 2)
		self.assertFalse(buf.hasSelection)

	def test_typingReplacesSelection(self):
		buf = TextBuffer("hello world")
		buf.caret = 0
		buf.moveWord(1, select=True)
		buf.typeText("X")
		self.assertEqual(buf.text, "Xworld")

	def test_backspaceAndDelete(self):
		buf = TextBuffer("hello world")
		self.assertEqual(buf.backspace(), "d")
		self.assertEqual(buf.backspace(word=True), "worl")
		self.assertEqual(buf.text, "hello ")
		buf.caret = 0
		self.assertEqual(buf.deleteForward(word=True), "hello ")
		self.assertEqual(buf.text, "")
		self.assertEqual(buf.backspace(), "")
		self.assertEqual(buf.deleteForward(), "")

	def test_undoIsPerWordAndRedoWorks(self):
		buf = TextBuffer()
		for ch in "hi there":
			buf.typeText(ch)
		self.assertTrue(buf.undo())
		self.assertEqual(buf.text, "hi ")
		self.assertTrue(buf.undo())
		self.assertEqual(buf.text, "")
		self.assertFalse(buf.undo())
		self.assertTrue(buf.redo())
		self.assertTrue(buf.redo())
		self.assertEqual(buf.text, "hi there")
		self.assertFalse(buf.redo())

	def test_backspacesUndoTogether(self):
		buf = TextBuffer("abc")
		buf.backspace()
		buf.backspace()
		buf.undo()
		self.assertEqual(buf.text, "abc")

	def test_editAfterUndoClearsRedo(self):
		buf = TextBuffer()
		buf.typeText("a")
		buf.undo()
		buf.typeText("b")
		self.assertFalse(buf.redo())

	def test_selectAllAndCounts(self):
		buf = TextBuffer("one two\nthree")
		buf.selectAll()
		self.assertEqual(buf.selectedText, "one two\nthree")
		self.assertEqual(buf.wordCount, 3)


if __name__ == "__main__":
	unittest.main()
