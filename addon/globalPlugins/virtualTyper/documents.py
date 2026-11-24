"""Saved virtual typer files: plain text files plus a JSON index, kept in NVDA's settings folder.

It has no NVDA dependencies so it can be unit tested with plain Python.
"""

import json
import os
import time
import uuid

from .textBuffer import normalizeNewlines

INDEX_FILE_NAME = "index.json"
DOCUMENTS_FOLDER_NAME = "documents"
MAX_TITLE_LENGTH = 60

#: The title follows the first line of the text and is refreshed on every save.
TITLE_AUTO = "auto"
#: The title is a date or was typed by the user, so it never changes by itself.
TITLE_FIXED = "fixed"
#: Auto saved while the title mode is "ask"; the user is asked for a title when they next save or close.
TITLE_PROVISIONAL = "provisional"


def firstLineTitle(text):
	"""Returns the first non-empty line, shortened at a word boundary, or "" if the text is blank."""
	for line in normalizeNewlines(text).split("\n"):
		line = " ".join(line.split())
		if not line:
			continue
		if len(line) > MAX_TITLE_LENGTH:
			shortened = line[:MAX_TITLE_LENGTH].rsplit(" ", 1)[0]
			line = shortened if len(shortened) >= MAX_TITLE_LENGTH // 2 else line[:MAX_TITLE_LENGTH]
		return line
	return ""


def _atomicWrite(path, text):
	tempPath = path + ".tmp"
	with open(tempPath, "w", encoding="utf-8") as tempFile:
		tempFile.write(text)
	os.replace(tempPath, path)


class DocumentStore:
	def __init__(self, folder):
		self.folder = folder
		self._documentsFolder = os.path.join(folder, DOCUMENTS_FOLDER_NAME)
		self._indexPath = os.path.join(folder, INDEX_FILE_NAME)
		#: Document records, most recently saved first.
		self.documents = []
		#: What was open when NVDA last exited: documentId, draft (unsaved text) and caret.
		self.session = {}
		self._load()

	def _load(self):
		try:
			with open(self._indexPath, encoding="utf-8") as indexFile:
				data = json.load(indexFile)
		except FileNotFoundError:
			return
		except (OSError, ValueError):
			# Keep the damaged index for inspection instead of overwriting it on the next save.
			os.replace(self._indexPath, self._indexPath + ".damaged")
			return
		documents = data.get("documents") if isinstance(data, dict) else None
		self.documents = [
			doc
			for doc in documents or []
			if isinstance(doc, dict)
			and isinstance(doc.get("id"), str)
			and isinstance(doc.get("file"), str)
			and isinstance(doc.get("title"), str)
			and os.path.isfile(self._path(doc))
		]
		session = data.get("session") if isinstance(data, dict) else None
		self.session = session if isinstance(session, dict) else {}

	def _path(self, doc):
		return os.path.join(self._documentsFolder, os.path.basename(doc["file"]))

	def _writeIndex(self):
		os.makedirs(self.folder, exist_ok=True)
		_atomicWrite(
			self._indexPath,
			json.dumps({"documents": self.documents, "session": self.session}, ensure_ascii=False, indent=1),
		)

	def get(self, docId):
		return next((doc for doc in self.documents if doc["id"] == docId), None)

	def read(self, doc):
		with open(self._path(doc), encoding="utf-8") as documentFile:
			return documentFile.read()

	def save(self, text, title, titleSource, docId=None, caret=0, maxDocuments=50):
		"""Writes a document, moves it to the top of the list and returns its record."""
		doc = self.get(docId) if docId else None
		if doc is None:
			newId = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
			doc = {"id": newId, "file": newId + ".txt", "created": time.time()}
		else:
			self.documents.remove(doc)
		doc.update(title=title, titleSource=titleSource, modified=time.time(), caret=caret)
		os.makedirs(self._documentsFolder, exist_ok=True)
		self.documents.insert(0, doc)
		try:
			_atomicWrite(self._path(doc), text)
		except OSError:
			if not os.path.isfile(self._path(doc)):
				self.documents.remove(doc)
			raise
		self._prune(maxDocuments)
		self._writeIndex()
		return doc

	def rename(self, docId, title):
		doc = self.get(docId)
		if doc is not None:
			doc["title"] = title
			doc["titleSource"] = TITLE_FIXED
			self._writeIndex()

	def delete(self, docId):
		doc = self.get(docId)
		if doc is None:
			return
		self.documents.remove(doc)
		self._removeFile(doc)
		self._writeIndex()

	def saveSession(self, session):
		self.session = session
		self._writeIndex()

	def _prune(self, maxDocuments):
		"""Deletes the least recently saved documents beyond the limit. The newest one is always kept."""
		while len(self.documents) > max(1, maxDocuments):
			self._removeFile(self.documents.pop())

	def _removeFile(self, doc):
		try:
			os.remove(self._path(doc))
		except FileNotFoundError:
			pass
