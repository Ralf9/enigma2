from __future__ import division
from __future__ import absolute_import
from enigma import eLabel, eWidget, eSlider, ePoint, eSize
import skin
from Components.HTMLComponent import HTMLComponent
from Components.GUIComponent import GUIComponent
import math

class ScrollLabel(HTMLComponent, GUIComponent):
	def __init__(self, text=""):
		GUIComponent.__init__(self)
		self.message = text
		self.instance = None
		self.long_text = None
		self.scrollbar = None
		self.pages = 1
		self.total = 1
		self._pageLines = 1
		self._skinSize = eSize(0,0)
		self._currentPage = 1
		self._isDeleted = False

	def applySkin(self, desktop, parent):
		if self.skinAttributes is None:
			return False
		skin.applyAllAttributes(self.long_text, desktop, self.skinAttributes, parent.scale)
		widget_attribs = [ ]
		scrollbar_attribs = [ ]
		for (attrib, value) in self.skinAttributes:
			if attrib.find("borderColor") != -1 or attrib.find("borderWidth") != -1:
				scrollbar_attribs.append((attrib,value))
			if attrib.find("transparent") != -1 or attrib.find("backgroundColor") != -1:
				widget_attribs.append((attrib,value))
		skin.applyAllAttributes(self.instance, desktop, widget_attribs, parent.scale)
		skin.applyAllAttributes(self.scrollbar, desktop, scrollbar_attribs, parent.scale)

		self.long_text.setDefaultAnimationEnabled(True)
		s = self.long_text.size()

		self.instance.resize(s)
		self._skinSize = s

		self.instance.move(self.long_text.position())
		self.pageHeight = s.height()

		scrollbarwidth, scrollbarborderwidth = self.scrollbar.updateScrollLabelProperties(20, 1)

		self.scrollbar.move(ePoint(s.width()-scrollbarwidth,0))
		self.scrollbar.resize(eSize(scrollbarwidth, s.height()))
		self.scrollbar.setOrientation(eSlider.orVertical, False, True)
		self.scrollbar.setRange(0,100)
		self.scrollbar.setBorderWidth(scrollbarborderwidth)
		self.long_text.move(ePoint(0,0))
		self.long_text.resize(eSize(s.width()-scrollbarwidth-10, s.height()))
		self.setText(self.message)

		return True

	def _recalc(self):
		line_height = self.long_text.calculateLineHeight()
		if self.pageHeight <= 0 or line_height <= 0:
			self.pages = 1
			self.total = 1
			self._pageLines = 1
			return
		self._pageLines = ((self._skinSize.height() - self.long_text.getPadding().y() * 2) // line_height)
		text_height = self.long_text.calculateSize().height()
		self.pages = int( math.ceil(float(text_height) / float(self.pageHeight)) )
		self.total = self.pages * self._pageLines

	def _textChanged(self):
		if self._isDeleted:
			return
		self._currentPage = 1
		self.pages = 1
		self.total = 0
		if not self.long_text or not self.instance:
			self.updateScrollbar()
			return

		self.long_text.setText(self.message)
		self._recalc()

		self._currentPage = 1
		self.updateScrollbar()

	def setText(self, text):
		self.message = text
		self._textChanged()

	def appendText(self, text):
		self.setText(self.message + text)

	def updateScrollbar(self):
		if self._isDeleted or not self.scrollbar:
			return
		if self.long_text and self.pages > 1:
			self.scrollbar.show()
			vis = self._pageLines * 100 // self.total
			if self._currentPage != self.pages:
				start = (self._currentPage - 1) * 100 // self.pages
			else: # avoid unwanted offset on odd total pages (3x33 = 99 instead of 100)
				start = 100 - vis
			self.scrollbar.setStartEnd(start, start+vis)
		else:
			self.scrollbar.hide()

	def getText(self):
		return self.message

	text = property(getText, setText)

	def GUIcreate(self, parent):
		self.instance = eWidget(parent)
		self.scrollbar = eSlider(self.instance)
		self.long_text = eLabel(self.instance)

	def GUIdelete(self):
		self._isDeleted = True
		self.long_text = None
		self.scrollbar = None
		self.instance = None

	def _pageChanged(self):
		if self.pages < 1:
			return
		startLine = (self._currentPage - 1) * self._pageLines
		self.long_text.setOffset(startLine, self._pageLines)
		self.updateScrollbar()

	def pageUp(self):
		self._currentPage = max(1, self._currentPage - 1)
		self._pageChanged()

	def pageDown(self):
		self._currentPage = min(self.pages, self._currentPage + 1)
		self._pageChanged()

	def lastPage(self):
		self._currentPage = self.pages
		self._pageChanged()

	def produceHTML(self):
		return self.getText()
