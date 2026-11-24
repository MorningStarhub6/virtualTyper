"""Packages the addon folder into an installable .nvda-addon file next to this script."""

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADDON_DIR = ROOT / "addon"


def readManifestValue(key):
	manifest = (ADDON_DIR / "manifest.ini").read_text(encoding="utf-8")
	match = re.search(rf"^{key}\s*=\s*(.+)$", manifest, re.MULTILINE)
	if not match:
		sys.exit(f"manifest.ini has no {key}")
	return match.group(1).strip().strip('"')


def main():
	outputPath = ROOT / f"{readManifestValue('name')}-{readManifestValue('version')}.nvda-addon"
	with zipfile.ZipFile(outputPath, "w", zipfile.ZIP_DEFLATED) as archive:
		for path in sorted(ADDON_DIR.rglob("*")):
			if path.is_dir() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
				continue
			archive.write(path, path.relative_to(ADDON_DIR).as_posix())
	print(f"Built {outputPath}")


if __name__ == "__main__":
	main()
