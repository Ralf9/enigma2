from __future__ import division
from __future__ import absolute_import
from Components.Converter.Converter import Converter
from time import localtime, strftime
from Components.Element import cached


class ClockToText(Converter, object):
	DEFAULT = 0
	WITH_SECONDS = 1
	IN_MINUTES = 2
	DATE = 3
	FORMAT = 4
	AS_LENGTH = 5
	TIMESTAMP = 6
	AS_LENGTH_WITH_HOURS = 7
	
	# add: date, date as string, weekday, ... 
	# (whatever you need!)
	
	def __init__(self, type):
		Converter.__init__(self, type)
		if type == "WithSeconds":
			self.type = self.WITH_SECONDS
			self.isAnimated = False
		elif type == "InMinutes":
			self.type = self.IN_MINUTES
		elif type == "Date":
			self.type = self.DATE
		elif type == "AsLength":
			self.type = self.AS_LENGTH
		elif type == "AsLengthWithHours":
			self.type = self.AS_LENGTH_WITH_HOURS
		elif type == "Timestamp":	
			self.type = self.TIMESTAMP
			self.isAnimated = False
		elif str(type).find("Format") != -1:
			self.type = self.FORMAT
			self.fmt_string = type[7:]
			self.isAnimated = False
		else:
			self.type = self.DEFAULT

	@cached
	def getText(self):
		time = self.source.time
		if time is None:
			return ""

		# handle durations
		if self.type == self.IN_MINUTES:
			return "%d min" % (time // 60)
		elif self.type == self.AS_LENGTH:
			return "%d:%02d" % (time // 60, time % 60)
		elif self.type == self.AS_LENGTH_WITH_HOURS:
			if time // 3600 <= 0:
				return "%d:%02d" % (time // 60, time % 60)
			return "%d:%02d:%02d" % (time // 3600, (time % 3600) // 60, time % 60)
		elif self.type == self.TIMESTAMP:
			return str(time)
		
		t = localtime(time)
		
		if self.type == self.WITH_SECONDS:
			return "%2d:%02d:%02d" % (t.tm_hour, t.tm_min, t.tm_sec)
		elif self.type == self.DEFAULT:
			return "%02d:%02d" % (t.tm_hour, t.tm_min)
		elif self.type == self.DATE:
			return strftime("%a, %x", t)
		elif self.type == self.FORMAT:
			spos = self.fmt_string.find('%')
			if spos > -1:
				s1 = self.fmt_string[:spos]
				s2 = strftime(self.fmt_string[spos:], t)
				return str(s1+s2)
			else:
				return strftime(self.fmt_string, t)
		
		else:
			return "???"

	text = property(getText)
