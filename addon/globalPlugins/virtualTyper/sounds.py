"""Keyboard sound packs, played through a small pool of players so fast key clicks can overlap."""

import array
import os
import random
import re
import threading
import wave

import config
import nvwave
from logHandler import log

from .addonConfig import getConfig

SOUNDS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "sounds"))
PLAYERS_PER_FORMAT = 4
_TYPE_SOUND = re.compile(r"^type\d+$")


def listPacks():
	try:
		names = os.listdir(SOUNDS_DIR)
	except OSError:
		return []
	return sorted(
		name
		for name in names
		if os.path.isdir(os.path.join(SOUNDS_DIR, name))
		and any(_TYPE_SOUND.match(os.path.splitext(f)[0]) for f in os.listdir(os.path.join(SOUNDS_DIR, name)))
	)


def packDisplayName(pack):
	"""Turns a folder name such as keyboard18 into Keyboard 18."""
	spaced = re.sub(r"(?<=[^\d\s])(?=\d)", " ", pack.replace("_", " "))
	return spaced[:1].upper() + spaced[1:]


def soundKindForCharacter(ch):
	if ch == " ":
		return "space"
	if ch == "\n":
		return "enter"
	return "type"


def _loadWave(path, volume):
	with wave.open(path, "rb") as waveFile:
		if waveFile.getsampwidth() != 2:
			raise ValueError(f"{path} is not 16 bit audio")
		audioFormat = (waveFile.getnchannels(), waveFile.getframerate())
		data = waveFile.readframes(waveFile.getnframes())
	if volume < 100:
		samples = array.array("h")
		samples.frombytes(data)
		factor = volume / 100
		data = array.array("h", [int(sample * factor) for sample in samples]).tobytes()
	return audioFormat, data


def _loadPack(pack, volume):
	"""Returns {kind: [(format, data), ...]} where kind is type, space, enter or delete."""
	folder = os.path.join(SOUNDS_DIR, pack)
	sounds = {}
	for fileName in sorted(os.listdir(folder)):
		name, extension = os.path.splitext(fileName)
		if extension.lower() != ".wav":
			continue
		kind = "type" if _TYPE_SOUND.match(name) else name.lower()
		try:
			sounds.setdefault(kind, []).append(_loadWave(os.path.join(folder, fileName), volume))
		except (OSError, EOFError, ValueError, wave.Error):
			log.warning(f"Virtual Typer: could not load sound {fileName} from {pack}", exc_info=True)
	return sounds


class KeyboardSounds:
	"""Plays the configured sound pack. Safe to call from any thread."""

	def __init__(self):
		self._lock = threading.Lock()
		self._cacheKey = None
		self._sounds = {}
		self._players = {}
		self._nextPlayer = {}
		self._lastChoice = {}

	def play(self, kind):
		conf = getConfig()
		if conf["soundPack"]:
			self._play(conf["soundPack"], conf["soundVolume"], kind)

	def preview(self, pack, volume):
		if pack:
			self._play(pack, volume, "type")

	def _play(self, pack, volume, kind):
		try:
			with self._lock:
				sounds = self._getSounds(pack, volume)
				choices = sounds.get(kind) or sounds.get("type")
				if not choices:
					return
				audioFormat, data = self._choose(kind, choices)
				player = self._getPlayer(audioFormat)
				player.stop()
				player.feed(data)
		except Exception:
			log.debugWarning("Virtual Typer: could not play a keyboard sound", exc_info=True)

	def _getSounds(self, pack, volume):
		if self._cacheKey != (pack, volume):
			self._cacheKey = (pack, volume)
			try:
				self._sounds = _loadPack(pack, volume)
			except OSError:
				log.warning(f"Virtual Typer: sound pack {pack} was not found", exc_info=True)
				self._sounds = {}
		return self._sounds

	def _choose(self, kind, choices):
		"""Picks a random variant, avoiding the one played last time so repeated keys sound natural."""
		if len(choices) == 1:
			return choices[0]
		last = self._lastChoice.get(kind)
		if last is None or last >= len(choices):
			index = random.randrange(len(choices))
		else:
			index = random.randrange(len(choices) - 1)
			if index >= last:
				index += 1
		self._lastChoice[kind] = index
		return choices[index]

	def _getPlayer(self, audioFormat):
		players = self._players.get(audioFormat)
		if players is None:
			channels, samplesPerSec = audioFormat
			players = self._players[audioFormat] = [
				nvwave.WavePlayer(
					channels=channels,
					samplesPerSec=samplesPerSec,
					bitsPerSample=16,
					outputDevice=config.conf["audio"]["outputDevice"],
					wantDucking=False,
					purpose=nvwave.AudioPurpose.SOUNDS,
				)
				for _index in range(PLAYERS_PER_FORMAT)
			]
		index = self._nextPlayer.get(audioFormat, 0)
		self._nextPlayer[audioFormat] = (index + 1) % len(players)
		return players[index]

	def terminate(self):
		with self._lock:
			for players in self._players.values():
				for player in players:
					try:
						player.close()
					except Exception:
						log.debugWarning("Virtual Typer: could not close a sound player", exc_info=True)
			self._players.clear()


keyboardSounds = KeyboardSounds()
