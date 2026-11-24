import os
import tempfile
import unittest

import nvdaStubs

nvdaStubs.install()

from virtualTyper.documents import TITLE_AUTO, TITLE_FIXED, DocumentStore, firstLineTitle  # noqa: E402


class TestFirstLineTitle(unittest.TestCase):
	def test_firstNonEmptyLine(self):
		self.assertEqual(firstLineTitle("\n   \n  Shopping   list \nmilk"), "Shopping list")
		self.assertEqual(firstLineTitle(" \n\t"), "")

	def test_longLinesAreShortenedAtAWord(self):
		title = firstLineTitle("word " * 30)
		self.assertLessEqual(len(title), 60)
		self.assertTrue(title.endswith("word"))


class TestDocumentStore(unittest.TestCase):
	def setUp(self):
		self.folder = tempfile.mkdtemp(prefix="virtualTyperStore")

	def test_saveReadAndReload(self):
		store = DocumentStore(self.folder)
		doc = store.save("line one\nline two", "line one", TITLE_AUTO, caret=4)
		self.assertEqual(store.read(doc), "line one\nline two")
		reloaded = DocumentStore(self.folder)
		self.assertEqual([d["title"] for d in reloaded.documents], ["line one"])
		self.assertEqual(reloaded.documents[0]["caret"], 4)

	def test_filesUseWindowsLineEndingsOnDisk(self):
		store = DocumentStore(self.folder)
		doc = store.save("a\nb", "a", TITLE_AUTO)
		with open(os.path.join(self.folder, "documents", doc["file"]), "rb") as savedFile:
			self.assertEqual(savedFile.read(), b"a\r\nb")

	def test_mostRecentFirstAndUpdateInPlace(self):
		store = DocumentStore(self.folder)
		first = store.save("one", "one", TITLE_AUTO)
		store.save("two", "two", TITLE_AUTO)
		store.save("one again", "one again", TITLE_AUTO, docId=first["id"])
		self.assertEqual([d["title"] for d in store.documents], ["one again", "two"])

	def test_pruneDeletesOldestFiles(self):
		store = DocumentStore(self.folder)
		oldest = store.save("1", "1", TITLE_AUTO, maxDocuments=2)
		store.save("2", "2", TITLE_AUTO, maxDocuments=2)
		store.save("3", "3", TITLE_AUTO, maxDocuments=2)
		self.assertEqual([d["title"] for d in store.documents], ["3", "2"])
		self.assertFalse(os.path.exists(os.path.join(self.folder, "documents", oldest["file"])))

	def test_renameDeleteAndSession(self):
		store = DocumentStore(self.folder)
		doc = store.save("text", "text", TITLE_AUTO)
		store.rename(doc["id"], "Renamed")
		self.assertEqual(store.get(doc["id"])["titleSource"], TITLE_FIXED)
		store.saveSession({"documentId": doc["id"], "draft": "unsaved", "caret": 2})
		store.delete(doc["id"])
		reloaded = DocumentStore(self.folder)
		self.assertEqual(reloaded.documents, [])
		self.assertEqual(reloaded.session["draft"], "unsaved")

	def test_missingFilesAndDamagedIndex(self):
		store = DocumentStore(self.folder)
		doc = store.save("text", "text", TITLE_AUTO)
		os.remove(os.path.join(self.folder, "documents", doc["file"]))
		self.assertEqual(DocumentStore(self.folder).documents, [])
		with open(os.path.join(self.folder, "index.json"), "w", encoding="utf-8") as indexFile:
			indexFile.write("{not json")
		self.assertEqual(DocumentStore(self.folder).documents, [])
		self.assertTrue(os.path.exists(os.path.join(self.folder, "index.json.damaged")))


if __name__ == "__main__":
	unittest.main()
