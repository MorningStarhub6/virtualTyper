import keyboardHandler

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_ESCAPE = 0x1B
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_N = 0x4E
VK_Y = 0x59
VK_F1 = 0x70
VK_F2 = 0x71
VK_F24 = 0x87

#: Keys that keep their normal system function while the virtual typer is open: toggle keys, print screen, sleep, media and volume keys.
PASS_THROUGH_KEYS = frozenset([0x14, 0x2C, 0x5F, 0x90, 0x91, *range(0xA6, 0xB8)])


class Modifiers:
	__slots__ = ("shift", "control", "alt", "windows", "nvda")

	def __init__(self, gesture):
		self.shift = self.control = self.alt = self.windows = self.nvda = False
		for vk, extended in gesture.generalizedModifiers:
			if vk == keyboardHandler.VK_WIN:
				self.windows = True
			elif vk == VK_SHIFT:
				self.shift = True
			elif vk == VK_CONTROL:
				self.control = True
			elif vk == VK_MENU:
				self.alt = True
			elif keyboardHandler.isNVDAModifierKey(vk, extended):
				self.nvda = True

	@property
	def plain(self):
		"""True when no modifier other than Shift is held."""
		return not (self.control or self.alt or self.windows or self.nvda)
