import addonHandler
import wx
from gui import guiHelper, nvdaControls
from gui.settingsDialogs import SettingsPanel

from .addonConfig import MAX_DOCUMENTS, TITLE_MODES, getConfig
from .sounds import keyboardSounds, listPacks, packDisplayName

addonHandler.initTranslation()

_TITLE_MODE_LABELS = {
	# Translators: A choice for how new virtual typer files are titled.
	"date": _("Date and time"),
	# Translators: A choice for how new virtual typer files are titled.
	"firstLine": _("First line of the text"),
	# Translators: A choice for how new virtual typer files are titled.
	"ask": _("Ask me when saving"),
}


class VirtualTyperSettingsPanel(SettingsPanel):
	# Translators: Title of the Virtual Typer category in the NVDA settings dialog.
	title = _("Virtual Typer")

	def makeSettings(self, settingsSizer):
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		conf = getConfig()

		self.autoSaveCheckBox = helper.addItem(
			# Translators: Label of a Virtual Typer setting.
			wx.CheckBox(self, label=_("Save files &automatically while typing")),
		)
		self.autoSaveCheckBox.SetValue(conf["autoSave"])
		self.maxDocumentsEdit = helper.addLabeledControl(
			# Translators: Label of a Virtual Typer setting.
			_("&Number of files to keep (the oldest are deleted):"),
			nvdaControls.SelectOnFocusSpinCtrl,
			min=1,
			max=MAX_DOCUMENTS,
			initial=conf["maxDocuments"],
		)
		self.titleModeChoice = helper.addLabeledControl(
			# Translators: Label of a Virtual Typer setting.
			_("&Title for new files:"),
			wx.Choice,
			choices=[_TITLE_MODE_LABELS[mode] for mode in TITLE_MODES],
		)
		self.titleModeChoice.SetSelection(TITLE_MODES.index(conf["titleMode"]))

		self.speedEdit = helper.addLabeledControl(
			# Translators: Label of the auto typing speed setting.
			_("Auto typing &speed (characters per second):"),
			nvdaControls.SelectOnFocusSpinCtrl,
			min=1,
			max=100,
			initial=conf["charsPerSecond"],
		)
		self.naturalRhythmCheckBox = helper.addItem(
			# Translators: Label of a Virtual Typer setting.
			wx.CheckBox(self, label=_("Type with a natural &rhythm (uneven speed, pauses after punctuation)")),
		)
		self.naturalRhythmCheckBox.SetValue(conf["naturalRhythm"])
		self.typosCheckBox = helper.addItem(
			# Translators: Label of a Virtual Typer setting.
			wx.CheckBox(self, label=_("Make occasional typing &mistakes and correct them")),
		)
		self.typosCheckBox.SetValue(conf["typos"])

		self._packs = [""] + listPacks()
		self.soundPackChoice = helper.addLabeledControl(
			# Translators: Label of the keyboard sound pack setting.
			_("&Keyboard sounds:"),
			wx.Choice,
			# Translators: The choice that turns keyboard sounds off.
			choices=[_("Off")] + [packDisplayName(pack) for pack in self._packs[1:]],
		)
		currentPack = conf["soundPack"]
		self.soundPackChoice.SetSelection(self._packs.index(currentPack) if currentPack in self._packs else 0)
		self.soundPackChoice.Bind(wx.EVT_CHOICE, self._onSoundPackChanged)
		self.soundVolumeEdit = helper.addLabeledControl(
			# Translators: Label of the keyboard sound volume setting.
			_("Keyboard sound &volume:"),
			nvdaControls.SelectOnFocusSpinCtrl,
			min=0,
			max=100,
			initial=conf["soundVolume"],
		)
		self.soundsInTyperCheckBox = helper.addItem(
			# Translators: Label of a Virtual Typer setting.
			wx.CheckBox(self, label=_("Also play keyboard sounds when typing in the virtual &typer")),
		)
		self.soundsInTyperCheckBox.SetValue(conf["soundsInTyper"])

	def _onSoundPackChanged(self, event):
		keyboardSounds.preview(self._packs[self.soundPackChoice.GetSelection()], self.soundVolumeEdit.GetValue())

	def onSave(self):
		conf = getConfig()
		conf["autoSave"] = self.autoSaveCheckBox.GetValue()
		conf["maxDocuments"] = self.maxDocumentsEdit.GetValue()
		conf["titleMode"] = TITLE_MODES[self.titleModeChoice.GetSelection()]
		conf["charsPerSecond"] = self.speedEdit.GetValue()
		conf["naturalRhythm"] = self.naturalRhythmCheckBox.GetValue()
		conf["typos"] = self.typosCheckBox.GetValue()
		conf["soundPack"] = self._packs[self.soundPackChoice.GetSelection()]
		conf["soundVolume"] = self.soundVolumeEdit.GetValue()
		conf["soundsInTyper"] = self.soundsInTyperCheckBox.GetValue()
