from __future__ import absolute_import
from Components.Sources.Source import Source
from Components.Element import cached
from enigma import iRecordableService

class RecordState(Source):
	def __init__(self, session):
		Source.__init__(self)
		self.records_running = 0
		self._record_name = ""
		self.session = session
		session.nav.record_event.append(self.gotRecordEvent)
		self.session.nav.RecordTimer.on_state_change.append(self.onTimerEvent)
		self.onTimerEvent(fire=False)
		self.gotRecordEvent(None, None) # get initial state

	def onTimerEvent(self, entry=None, fire=True):
		if not entry:
			for timer in self.session.nav.RecordTimer.timer_list:
				if timer.isRunning() and not timer.justplay:
					entry = timer
		if not entry:
			return
		prev_record_name = self._record_name
		self._record_name = ""
		if entry.isRunning() and not entry.justplay:
			self._record_name = entry.name
		if fire and self._record_name != prev_record_name:
			self.changed((self.CHANGED_ALL,))

	def gotRecordEvent(self, service, event):
		prev_records = self.records_running
		if event in (iRecordableService.evEnd, iRecordableService.evStart, None):
			recs = self.session.nav.getRecordings()
			self.records_running = len(recs)
			if self.records_running != prev_records:
				self.changed((self.CHANGED_ALL,))

	def destroy(self):
		self.session.nav.record_event.remove(self.gotRecordEvent)
		self.session.nav.RecordTimer.on_state_change.remove(self.onTimerEvent)
		Source.destroy(self)

	@cached
	def getBoolean(self):
		return self.records_running and True or False
	boolean = property(getBoolean)

	@cached
	def getValue(self):
		return self.records_running
	value = property(getValue)

	@cached
	def getText(self):
		return self._record_name
	text = property(getText)
