import threading
import types
import unittest

import nvdaStubs

nvdaStubs.install()

from virtualTyper import autoTyper  # noqa: E402
from virtualTyper.autoTyper import AutoTyper, FinishReason, findResumePoint  # noqa: E402


class TestHelpers(unittest.TestCase):
	def test_prepareText(self):
		self.assertEqual(autoTyper.prepareText("a\r\nb\rc\x07\td"), "a\nb\nc\td")

	def test_typoIsNeighbourWithSameCase(self):
		for _ in range(50):
			self.assertIn(autoTyper.typoFor("g"), "ftyhbv")
			self.assertIn(autoTyper.typoFor("G"), "FTYHBV")
		self.assertIsNone(autoTyper.typoFor("1"))
		self.assertIsNone(autoTyper.typoFor("é"))

	def test_delayRange(self):
		self.assertEqual(autoTyper.characterDelay("a", 0.05, False), 0.05)
		for _ in range(200):
			delay = autoTyper.characterDelay("a", 0.05, True)
			self.assertGreaterEqual(delay, 0.025)
			self.assertLessEqual(delay, 0.075 + 0.5)


class TestFindResumePoint(unittest.TestCase):
	def test_everythingArrived(self):
		self.assertEqual(findResumePoint("hello world", 11, "Dear Sam, hello world"), (11, 0))

	def test_lastCharactersMissing(self):
		self.assertEqual(findResumePoint("hello world", 11, "hello wor"), (9, 0))

	def test_repairsADroppedLetter(self):
		text = "Hello there, the quick brown fox"
		self.assertEqual(findResumePoint(text, 28, "Hello there, the quik brown"), (20, 7))

	def test_ignoresCaseAndSmartQuotes(self):
		self.assertEqual(findResumePoint("it's here", 9, "It’s here"), (9, 0))
		self.assertEqual(findResumePoint("a\nb", 3, "a\r\nb"), (3, 0))

	def test_unrelatedTextIsNotTouched(self):
		self.assertIsNone(findResumePoint("Hello there, the quick brown", 28, "something else entirely here"))
		self.assertIsNone(findResumePoint("abc", 3, "xyz"))
		self.assertIsNone(findResumePoint("abc", 3, ""))

	def test_nothingTypedYet(self):
		self.assertEqual(findResumePoint("abc", 0, "anything"), (0, 0))


class TestAutoTyper(unittest.TestCase):
	def setUp(self):
		self.typed = []
		self.sounds = []
		self.modifiersHeld = False
		self.onType = None
		self._saved = (autoTyper.typeCharacter, autoTyper._pressKey, autoTyper._user32, autoTyper.START_DELAY)
		autoTyper.typeCharacter = self._fakeType
		autoTyper._pressKey = lambda vk: self.typed.append("<back>" if vk == autoTyper.VK_BACK else vk)
		autoTyper._user32 = types.SimpleNamespace(GetForegroundWindow=lambda: 1)
		autoTyper.START_DELAY = 0
		self.finished = threading.Event()
		self.reason = None

	def tearDown(self):
		autoTyper.typeCharacter, autoTyper._pressKey, autoTyper._user32, autoTyper.START_DELAY = self._saved

	def _fakeType(self, ch):
		self.typed.append(ch)
		if self.onType:
			self.onType()

	def _onFinished(self, reason):
		self.reason = reason
		self.finished.set()

	def _typer(self):
		return AutoTyper(self._onFinished, lambda: self.modifiersHeld, onKey=self.sounds.append)

	def _waitFinished(self):
		self.assertTrue(self.finished.wait(5))
		self.finished.clear()

	def test_typesEverythingWithSounds(self):
		typer = self._typer()
		self.assertTrue(typer.start("Hi\r\nyou", 100, False, False))
		self._waitFinished()
		self.assertEqual(self.reason, FinishReason.DONE)
		self.assertEqual("".join(self.typed), "Hi\nyou")
		self.assertEqual(self.sounds, ["type", "type", "enter", "type", "type", "type"])
		self.assertIsNone(typer.pausedJob)

	def test_typosAreCorrected(self):
		autoTyper.TYPO_CHANCE, savedChance = 1.0, autoTyper.TYPO_CHANCE
		try:
			self._typer().start("ab", 100, False, True)
			self._waitFinished()
		finally:
			autoTyper.TYPO_CHANCE = savedChance
		self.assertEqual(len(self.typed), 6)
		self.assertEqual(self.typed[1::3], ["<back>", "<back>"])
		self.assertEqual(self.typed[2::3], ["a", "b"])
		self.assertEqual(self.sounds[1], "delete")

	def test_pauseAndResumeFromVerifiedPoint(self):
		typer = self._typer()
		self.onType = lambda: len(self.typed) == 3 and typer.pause()
		typer.start("abcdef", 100, False, False)
		self._waitFinished()
		self.assertEqual(self.reason, FinishReason.PAUSED)
		self.assertEqual(typer.pausedJob.nextIndex, 3)
		self.onType = None
		self.assertTrue(typer.resume(2, 1, 100, False, False))
		self._waitFinished()
		self.assertEqual(self.reason, FinishReason.DONE)
		self.assertEqual(self.typed, ["a", "b", "c", "<back>", "c", "d", "e", "f"])
		self.assertIsNone(typer.pausedJob)

	def test_windowChangePausesAndKeepsJob(self):
		windows = iter([2])
		autoTyper._user32 = types.SimpleNamespace(GetForegroundWindow=lambda: next(windows, 3))
		typer = self._typer()
		typer.start("abc", 100, False, False)
		self._waitFinished()
		self.assertEqual(self.reason, FinishReason.WINDOW_CHANGED)
		self.assertEqual(typer.pausedJob, autoTyper.PausedJob("abc", 0))

	def test_waitsForModifiersAndCancelForgetsJob(self):
		self.modifiersHeld = True
		typer = self._typer()
		typer.start("abc", 100, False, False)
		self.assertFalse(self.finished.wait(0.2))
		self.assertTrue(typer.isRunning)
		typer.cancel()
		self._waitFinished()
		self.assertEqual(self.reason, FinishReason.STOPPED)
		self.assertEqual(self.typed, [])
		self.assertIsNone(typer.pausedJob)

	def test_refusesEmptyTextSecondStartAndResumeWithoutJob(self):
		typer = self._typer()
		self.assertFalse(typer.start("\x07", 100, False, False))
		self.assertFalse(typer.resume(0, 0, 100, False, False))
		self.modifiersHeld = True
		self.assertTrue(typer.start("abc", 100, False, False))
		self.assertFalse(typer.start("abc", 100, False, False))
		typer.cancel()
		self._waitFinished()


if __name__ == "__main__":
	unittest.main()
