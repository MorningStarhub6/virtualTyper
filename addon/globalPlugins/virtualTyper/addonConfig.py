import config

CONFIG_SECTION = "virtualTyper"
TITLE_MODES = ("date", "firstLine", "ask")
DEFAULT_SOUND_PACK = "keyboard18"
MAX_DOCUMENTS = 50

CONFIG_SPEC = {
	"charsPerSecond": "integer(default=20, min=1, max=100)",
	"naturalRhythm": "boolean(default=true)",
	"typos": "boolean(default=false)",
	"autoSave": "boolean(default=true)",
	"maxDocuments": f"integer(default={MAX_DOCUMENTS}, min=1, max={MAX_DOCUMENTS})",
	"titleMode": 'option("date", "firstLine", "ask", default="firstLine")',
	"soundPack": f'string(default="{DEFAULT_SOUND_PACK}")',
	"soundVolume": "integer(default=80, min=0, max=100)",
	"soundsInTyper": "boolean(default=false)",
}


def getConfig():
	return config.conf[CONFIG_SECTION]
