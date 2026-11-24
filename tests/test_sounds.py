import array
import os
import unittest

import nvdaStubs

nvdaStubs.install()

import config  # noqa: E402
from virtualTyper import sounds  # noqa: E402

FakeWavePlayer = nvdaStubs.FakeWavePlayer


class TestPacks(unittest.TestCase):
	def test_bundledPacksAreFound(self):
		self.assertEqual(sounds.listPacks(), ["keyboard17", "keyboard18"])
		self.assertEqual(sounds.packDisplayName("keyboard18"), "Keyboard 18")

	def test_packHasAllKinds(self):
		pack = sounds._loadPack("keyboard18", 100)
		self.assertEqual(len(pack["type"]), 10)
		for kind in ("space", "enter", "delete"):
			self.assertEqual(len(pack[kind]), 1)
		self.assertEqual(pack["type"][0][0], (2, 44100))

	def test_volumeScalesSamples(self):
		path = os.path.join(sounds.SOUNDS_DIR, "keyboard18", "type1.wav")
		_, full = sounds._loadWave(path, 100)
		_, half = sounds._loadWave(path, 50)
		fullSamples, halfSamples = array.array("h"), array.array("h")
		fullSamples.frombytes(full)
		halfSamples.frombytes(half)
		loudest = max(range(len(fullSamples)), key=lambda i: abs(fullSamples[i]))
		self.assertEqual(halfSamples[loudest], int(fullSamples[loudest] * 0.5))


class TestKeyboardSounds(unittest.TestCase):
	def setUp(self):
		FakeWavePlayer.instances.clear()
		self.player = sounds.KeyboardSounds()

	def tearDown(self):
		config.conf["virtualTyper"]["soundPack"] = "keyboard18"

	def test_playUsesAPoolOfPlayers(self):
		for _ in range(6):
			self.player.play("type")
		self.assertEqual(len(FakeWavePlayer.instances), sounds.PLAYERS_PER_FORMAT)
		self.assertEqual(sum(len(p.fed) for p in FakeWavePlayer.instances), 6)
		self.assertEqual(FakeWavePlayer.instances[0].kwargs["purpose"], "sounds")

	def test_variantsDoNotRepeatBackToBack(self):
		picks = [self.player._choose("type", list(range(5))) for _ in range(200)]
		self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])))
		self.assertEqual(set(picks), set(range(5)))

	def test_offPlaysNothing(self):
		config.conf["virtualTyper"]["soundPack"] = ""
		self.player.play("space")
		self.assertEqual(FakeWavePlayer.instances, [])

	def test_missingPackIsQuiet(self):
		self.player.preview("noSuchPack", 80)
		self.assertEqual(FakeWavePlayer.instances, [])

	def test_terminateClosesPlayers(self):
		self.player.play("enter")
		self.player.terminate()
		self.assertTrue(all(p.closed for p in FakeWavePlayer.instances))


if __name__ == "__main__":
	unittest.main()
