"""Converts the source sound files in ../sounds into WAV sound packs inside the add-on.

Source files are named <pack><kind>.<ext>, for example keyboard18type3.ogg or keyboard18space.ogg.
Kinds are type1, type2, ..., space, enter and delete. Requires ffmpeg on the PATH.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "sounds"
OUTPUT_DIR = ROOT / "addon" / "sounds"
NAME_PATTERN = re.compile(r"^(?P<pack>.+?)(?P<kind>type\d+|space|enter|delete)$", re.IGNORECASE)
SOURCE_EXTENSIONS = (".ogg", ".wav", ".mp3", ".flac")


def main():
	if not shutil.which("ffmpeg"):
		sys.exit("ffmpeg was not found on the PATH")
	converted = 0
	for source in sorted(SOURCE_DIR.iterdir()):
		match = NAME_PATTERN.match(source.stem)
		if source.suffix.lower() not in SOURCE_EXTENSIONS or not match:
			print(f"Skipping {source.name}")
			continue
		target = OUTPUT_DIR / match["pack"].lower() / f"{match['kind'].lower()}.wav"
		target.parent.mkdir(parents=True, exist_ok=True)
		subprocess.run(
			[
				"ffmpeg", "-y", "-v", "error", "-i", str(source),
				"-ac", "2", "-ar", "44100", "-sample_fmt", "s16",
				"-map_metadata", "-1", "-fflags", "+bitexact", str(target),
			],
			check=True,
		)
		converted += 1
	print(f"Converted {converted} files into {OUTPUT_DIR}")


if __name__ == "__main__":
	main()
