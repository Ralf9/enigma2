# -*- coding: utf-8 -*-

from Components.Converter.Converter import Converter
from Components.Element import cached
from Components.Language import language
from Tools.Log import Log

class EventName(Converter, object):
	#types
	NAME = 0
	SHORT_DESCRIPTION = 1
	EXTENDED_DESCRIPTION = 2
	FULL_DESCRIPTION = 3
	ID = 4
	NAME_SHORT_DESCRIPTION = 5
	SHORT_EXTENDED_DESCRIPTION = 6
	ALL = 7

	def __init__(self, type):
		Converter.__init__(self, type)

		args = type.split(',')
		type = args.pop(0)

		#set params
		self._noShortDescNewline = "noShortDescEnter" in args or "noShortDescNewline" in args
		self._keepTitle =  "noRemoveTitle" in args or "keepTitle" in args
		self._singleShortDesc = "only1ShortDescValues" in args or "singleShortDesc" in args
		self._noExtDescDoubleNewline = "noExtDescDoubleEnter" in args or "noExtDescDoubleNewline" in args
		self._noRepeatText =  "noRepeatText" in args

		self.type = {
			"Description": self.SHORT_DESCRIPTION,
			"ExtendedDescription": self.EXTENDED_DESCRIPTION,
			"FullDescription": self.FULL_DESCRIPTION,
			"ID": self.ID,
			"NameShortDescription": self.NAME_SHORT_DESCRIPTION,
			"ShortExtendedDescription": self.SHORT_EXTENDED_DESCRIPTION,
			"All": self.ALL
		}.get(type, self.NAME)

	@cached
	def getText(self):
		event = self.source.event
		if event is None:
			return ""

		if self.type == self.NAME:
			return event.getEventName()

		elif self.type == self.SHORT_DESCRIPTION:
			return self._getShortDesc(event)

		elif self.type == self.EXTENDED_DESCRIPTION:
			desc = self._getExtendedDesc(event)
			if desc:
				if self._noExtDescDoubleNewline:
					desc = desc.replace("\n\n","\n").replace("\xc2\x8a\xc2\x8a","\n")
				return desc
			else:
				return _("No extended description available")

		elif self.type == self.FULL_DESCRIPTION:
			desc = self._getShortDesc(event)
			if desc:
				desc = "%s\n\n" %(desc,)
			desc = "%s%s" %(desc, self._getExtendedDesc(event))
			return desc

		elif self.type == self.ID:
			return str(event.getEventId())

		elif self.type == self.NAME_SHORT_DESCRIPTION:
			name = event.getEventName()
			desc  = self._getShortDesc(event)
			if desc and desc != name:
				return "%s - %s" % (name, desc)
			else:
				return name

		elif self.type == self.SHORT_EXTENDED_DESCRIPTION:
			desc = self._getShortDesc(event)
			ext = self._getExtendedDesc(event)
			if desc:
				desc = "%s\n" % (desc,)
			return "%s%s" % (desc, ext)

		elif self.type == self.ALL :
			name = self._filter(event.getEventName())
			desc = self._getShortDesc(event)
			if desc:
				desc = "%s\n\n" % (desc,)
			ext = self._getExtendedDesc(event)
			desc = "%s%s" % (desc, ext)
			return "%s\n\n%s" % (name, desc)

	text = property(getText)

	def _filter(self, text):
		return text.lstrip(" ").lstrip("\n").lstrip("\xc2\x8a").replace("\\n","\n")

	def _getExtendedDesc(self, event):
		return self._filter(event.getExtendedDescription())

	def _getShortDesc(self, event):
		name = self._filter(event.getEventName())
		desc = self._filter(event.getShortDescription())
		desc_list = desc.split("\n")

		#remove eventname if first entry in ShortDesc
		if not self._keepTitle and desc_list[0] == name:
			desc_list.pop(0)

		#return only 1 values/lines from ShortDesc
		if self._singleShortDesc:
			desc_list = desc_list[:1]

		if self._noShortDescNewline:
			desc = ", ".join(desc_list).strip()
		else:
			desc = "\n".join(desc_list).strip()
		if self._noRepeatText:
			Log.i("noRepeatText is not supported! Sorry!")

		return desc
