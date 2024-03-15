from __future__ import absolute_import
from Components.MenuList import MenuList
from Tools.Directories import SCOPE_CURRENT_SKIN, resolveFilename
from enigma import GRADIENT_TYPE_SIMPLE, RADIUS_TYPE_ALL, RADIUS_TYPE_BOTTOM, RT_HALIGN_LEFT, RT_NO_ELLIPSIS, RT_VALIGN_CENTER, eListboxPythonMultiContent, gFont
from skin import TemplatedListFonts, componentSizes
from Tools.LoadPixmap import LoadPixmap
from Tools.Log import Log

def ChoiceEntryComponent(key = "", text = ["--"]):
	COMPONENT_FILLER_COUNT = "fillerCount"
	COMPONENT_FADE_DIVIDER = "fadeDivider"
	COMPONENT_DIVIDER_WIDTH = "dividerWidth"
	COMPONENT_DIVIDER_HEIGHT = "dividerHeight"
	res = [ text ]
	"""
	<component type="ChoiceList" itemHeight="30" textWidth="800" textHeight="25" textX="45" textY="0" pixmapWidth="35" pixmapHeight="25" fadeDivider="0|1" dividerWidth="800", dividerHeight="10" />
	"""
	sizes = componentSizes[componentSizes.CHOICELIST]
	tx = sizes.get(componentSizes.TEXT_X, 45)
	ty = sizes.get(componentSizes.TEXT_Y, 0)
	tw = sizes.get(componentSizes.TEXT_WIDTH, 800)
	th = sizes.get(componentSizes.TEXT_HEIGHT, 25)
	pxx = sizes.get(componentSizes.PIXMAP_X, 5)
	pxy = sizes.get(componentSizes.PIXMAP_Y, 0)
	pxw = sizes.get(componentSizes.PIXMAP_WIDTH, 35)
	pxh = sizes.get(componentSizes.PIXMAP_HEIGHT, 25)
	dw = sizes.get(COMPONENT_DIVIDER_WIDTH, tw)
	dh = sizes.get(COMPONENT_DIVIDER_HEIGHT, th/12)
	if COMPONENT_FILLER_COUNT in sizes:
		Log.i("fillerCount is obsolete and can be removed from <component type=\"ChoiceList\" ... />")
	fadeDivider = sizes.get(COMPONENT_FADE_DIVIDER, 0)
	if text[0] == "--":
		entry = [eListboxPythonMultiContent.TYPE_FILL_ALPHABLEND, 0, (th-dh)/2, dw, dh]
		if fadeDivider:
			entry.extend([None, 0xFE000000, GRADIENT_TYPE_SIMPLE, -90.0])
		res.append(tuple(entry))
	else:
		res.append((eListboxPythonMultiContent.TYPE_TEXT, tx, ty, tw, th, 0, RT_HALIGN_LEFT|RT_VALIGN_CENTER, text[0]))
		png = (key != "False") and LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/buttons/key_" + key + ".png")) or None
		if png is not None:
			res.append((eListboxPythonMultiContent.TYPE_PIXMAP_ALPHABLEND, pxx, pxy, pxw, pxh, png))

	return res

class ChoiceList(MenuList):
	def __init__(self, list, selection = 0, enableWrapAround=False):
		MenuList.__init__(self, list, enableWrapAround, eListboxPythonMultiContent)

		tlf = TemplatedListFonts()
		self.l.setFont(0, gFont(tlf.face(tlf.BIG), tlf.size(tlf.BIG)))
		itemHeight = componentSizes.itemHeight(componentSizes.CHOICELIST, 30)
		self.l.setItemHeight(itemHeight)
		self.selection = selection

	def postWidgetCreate(self, instance):
		MenuList.postWidgetCreate(self, instance)
		self.moveToIndex(self.selection)
