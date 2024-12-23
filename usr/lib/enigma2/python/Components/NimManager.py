from __future__ import print_function
from __future__ import absolute_import
from Tools.HardwareInfo import HardwareInfo
from Tools.BoundFunction import boundFunction

from Components.config import config, ConfigSubsection, ConfigSelection, ConfigFloat, \
	ConfigSatlist, ConfigYesNo, ConfigInteger, ConfigSubList, ConfigNothing, \
	ConfigSubDict, ConfigOnOff, ConfigDateTime, ConfigText, NoSave, ConfigSet

from enigma import eDVBSatelliteEquipmentControl as secClass, \
	eDVBSatelliteDiseqcParameters as diseqcParam, \
	eDVBSatelliteSwitchParameters as switchParam, \
	eDVBSatelliteRotorParameters as rotorParam, \
	eDVBResourceManager, eDVBDB, eEnv, iDVBFrontend

from time import localtime, mktime
from datetime import datetime
from os.path import exists

import xml.etree.cElementTree

from Tools.Log import Log

from ast import literal_eval
import six
from six.moves import range

def getConfigSatlist(orbpos, satlist):
	default_orbpos = None
	for x in satlist:
		if x[0] == orbpos:
			default_orbpos = orbpos
			break
	return ConfigSatlist(satlist, default_orbpos)

def tryOpen(filename):
	try:
		procFile = open(filename)
	except IOError:
		return None
	return procFile

class SecConfigure:
	def getConfiguredSats(self):
		return self.configuredSatellites

	def addSatellite(self, sec, orbpos):
		sec.addSatellite(orbpos)
		self.configuredSatellites.add(orbpos)

	def addLNBSimple(self, sec, slotid, input, diseqcmode, toneburstmode = diseqcParam.NO, diseqcpos = diseqcParam.SENDNO, orbpos = 0, longitude = 0, latitude = 0, loDirection = 0, laDirection = 0, turningSpeed = rotorParam.FAST, useInputPower=True, inputPowerDelta=50, fastDiSEqC = False, setVoltageTone = True, diseqc13V = False, degreePerSecond = 0.5):
		if orbpos is None or orbpos == 3601:
			return
		#simple defaults
		sec.addLNB()
		sec.setLNBTunerInput(input)

		tunermask = 1 << slotid
		if input == -1:
			if slotid in self.equal:
				for slot in self.equal[slotid]:
					tunermask |= (1 << slot)
			if slotid in self.linked:
				for slot in self.linked[slotid]:
					tunermask |= (1 << slot)

		sec.setLNBSatCR(-1)
		sec.setLNBNum(1)
		sec.setLNBLOFL(9750000)
		sec.setLNBLOFH(10600000)
		sec.setLNBThreshold(11700000)
		sec.setLNBIncreasedVoltage(False)
		sec.setRepeats(0)
		sec.setFastDiSEqC(fastDiSEqC)
		sec.setSeqRepeat(0)
		sec.setCommandOrder(0)

		#user values
		sec.setDiSEqCMode(diseqcmode)
		sec.setToneburst(toneburstmode)
		sec.setCommittedCommand(diseqcpos)
		sec.setUncommittedCommand(0) # SENDNO
		#print "set orbpos to:" + str(orbpos)

		if 0 <= diseqcmode < 3:
			Log.i("add sat " + str(orbpos))
			self.addSatellite(sec, orbpos)
			if setVoltageTone:
				if diseqc13V:
					sec.setVoltageMode(switchParam.HV_13)
				else:
					sec.setVoltageMode(switchParam.HV)
				sec.setToneMode(switchParam.HILO)
			else:
				sec.setVoltageMode(switchParam._14V)
				sec.setToneMode(switchParam.OFF)
		elif (diseqcmode == 3): # diseqc 1.2
			if slotid in self.satposdepends:
				for slot in self.satposdepends[slotid]:
					tunermask |= (1 << slot)
			sec.setLatitude(latitude)
			sec.setLaDirection(laDirection)
			sec.setLongitude(longitude)
			sec.setLoDirection(loDirection)
			sec.setUseInputpower(useInputPower)
			sec.setInputpowerDelta(inputPowerDelta)
			sec.setRotorTurningSpeed(turningSpeed)
			sec.setDegreePerSecond(int(degreePerSecond*10))

			Log.i("add rotor satellites")
			for x in self.NimManager.satList:
				self.addSatellite(sec, int(x[0]))
				if diseqc13V:
					sec.setVoltageMode(switchParam.HV_13)
				else:
					sec.setVoltageMode(switchParam.HV)
				sec.setToneMode(switchParam.HILO)
				sec.setRotorPosNum(0) # USALS

		sec.setLNBSlotMask(tunermask)

	def setSatposDepends(self, sec, nim1, nim2):
		Log.i("tuner " + str(nim1) + " depends on satpos of " + str(nim2))
		sec.setTunerDepends(nim1, nim2)

	def linkInternally(self, slotid):
		nim = self.NimManager.getNim(slotid)
		nim.setInternalLink()

	def linkNIMs(self, sec, nim1, nim2):
		if abs(nim2  - nim1) == 1:
			Log.i("internal link tuner " + str(nim1) + " to tuner " + str(nim2))
			self.linkInternally(nim1)
		else:
			Log.i("external link tuner " + str(nim1) + " to tuner " + str(nim2))
		sec.setTunerLinked(nim1, nim2)

	def getRoot(self, slotid, connto):
		visited = []
		while (self.NimManager.getNimConfig(connto).sat.configMode.value in ("satposdepends", "equal", "loopthrough")):
			connto = int(self.NimManager.getNimConfig(connto).connectedTo.value)
			if connto in visited: # prevent endless loop
				return slotid
			visited.append(connto)
		return connto

	def update(self):
		sec = secClass.getInstance()
		self.configuredSatellites = set()
		for slotid in self.NimManager.getNimListOfType("DVB-S"):
			if self.NimManager.nimInternallyConnectableTo(slotid) is not None:
				self.NimManager.nimRemoveInternalLink(slotid)
		sec.clear() ## this do unlinking NIMs too !!

		Log.i("sec config cleared")

		self.linked = { }
		self.satposdepends = { }
		self.equal = { }

		nim_slots = self.NimManager.nim_slots

		used_nim_slots = [ ]

		multi_tuner_slot_base = -1
		multi_tuner_slot_channel = 0

		for slot in nim_slots:
			enabled = 0

			# handling for tuners with multiple channels
			if slot.inputs:
				if multi_tuner_slot_base == -1 or slot.channel <= multi_tuner_slot_channel:
					multi_tuner_slot_base = slot.slot
					multi_tuner_slot_channel = 0
				else:
					multi_tuner_slot_channel += 1
				def isEnabled(type):
					for inp in range(len(slot.inputs)):
						if nim_slots[multi_tuner_slot_base+inp].isEnabled(type):
							return True
					return False
				enabledFunc = isEnabled
			else:
				multi_tuner_slot_base = -1
				multi_tuner_slot_channel = 0
				enabledFunc = slot.isEnabled

			if enabledFunc("DVB-S2"):
				enabled |= iDVBFrontend.feSatellite2
			if enabledFunc("DVB-S"):
				enabled |= iDVBFrontend.feSatellite
			if enabledFunc("DVB-T2"):
				enabled |= iDVBFrontend.feTerrestrial2
			if enabledFunc("DVB-T"):
				enabled |= iDVBFrontend.feTerrestrial
			if enabledFunc("DVB-C"):
				enabled |= iDVBFrontend.feCable

			used_nim_slots.append((slot.slot, slot.description, enabled, slot.frontend_id is None and -1 or slot.frontend_id, slot.input_name or "", multi_tuner_slot_base, multi_tuner_slot_base+slot.channels-1))

		# this have to be called before tuners can be linked to other tuners!!!!!!!!
		eDVBResourceManager.getInstance().setFrontendSlotInformations(used_nim_slots)

		# please do not mix this loop with the following one...
		# this code must be run before the next loop
		for slot in nim_slots:
			x = slot.slot
			nim = slot.config

			# FIXMEE
			# no support for satpos depends, equal to and loopthough setting for nims with
			# with multiple inputs and multiple channels
			if slot.isEnabled("DVB-S") and not slot.inputs:
				# save what nim we link to/are equal to/satposdepends to.
				# this is stored in the *value* (not index!) of the config list
				if nim.sat.configMode.value == "equal":
					connto = self.getRoot(x, int(nim.connectedTo.value))
					if connto not in self.equal:
						self.equal[connto] = []
					self.equal[connto].append(x)
				elif nim.sat.configMode.value == "loopthrough":
					self.linkNIMs(sec, x, int(nim.connectedTo.value))
					connto = self.getRoot(x, int(nim.connectedTo.value))
					if connto not in self.linked:
						self.linked[connto] = []
					self.linked[connto].append(x)
				elif nim.sat.configMode.value == "satposdepends":
					self.setSatposDepends(sec, x, int(nim.connectedTo.value))
					connto = self.getRoot(x, int(nim.connectedTo.value))
					if connto not in self.satposdepends:
						self.satposdepends[connto] = []
					self.satposdepends[connto].append(x)

		multi_tuner_slot_base = -1
		multi_tuner_slot_channel = 0

		for sl in nim_slots:

			# handling for tuners with multiple channels
			if sl.inputs:
				inputs = len(sl.inputs)
				if multi_tuner_slot_base == -1 or sl.channel <= multi_tuner_slot_channel:
					multi_tuner_slot_base = sl.slot
					multi_tuner_slot_channel = 0
				else:
					multi_tuner_slot_channel += 1
			else:
				inputs = 1
				multi_tuner_slot_base = -1
				multi_tuner_slot_channel = 0

			slot_id = sl.slot

			for num in range(inputs):
				if multi_tuner_slot_base != -1:
					slot = nim_slots[multi_tuner_slot_base+num]
					input = num
				else:
					slot = sl
					input = -1

				nim = slot.config

				if slot.isEnabled("DVB-S"):

					if multi_tuner_slot_base != -1:
						Log.i("Slot " + str(slot.slot) + " Channel " + str(sl.channel) + " Input " + chr(ord('A')+num) + " Configmode " + str(nim.sat.configMode.value))
					else:
						Log.i("Slot " + str(slot_id) + " Configmode " + str(nim.sat.configMode.value))

					if nim.sat.configMode.value in ( "loopthrough", "satposdepends", "nothing" ):
						pass
					else:
						if nim.sat.configMode.value == "equal":
							pass
						elif nim.sat.configMode.value == "simple":		#simple config
							Log.i("DiSEqC Mode " + str(nim.diseqcMode.value))
							if nim.diseqcMode.value == "single":			#single
								if nim.simpleSingleSendDiSEqC.value:
									self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcA.orbital_position, toneburstmode = diseqcParam.NO, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.AA, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
								else:
									self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcA.orbital_position, toneburstmode = diseqcParam.NO, diseqcmode = diseqcParam.NONE, diseqcpos = diseqcParam.SENDNO, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
							elif nim.diseqcMode.value == "toneburst_a_b":		#Toneburst A/B
								self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcA.orbital_position, toneburstmode = diseqcParam.A, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.SENDNO, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
								self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcB.orbital_position, toneburstmode = diseqcParam.B, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.SENDNO, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
							elif nim.diseqcMode.value == "diseqc_a_b":		#DiSEqC A/B
								fastDiSEqC = nim.simpleDiSEqCOnlyOnSatChange.value
								setVoltageTone = nim.simpleDiSEqCSetVoltageTone.value
								self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcA.orbital_position, toneburstmode = diseqcParam.NO, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.AA, fastDiSEqC = fastDiSEqC, setVoltageTone = setVoltageTone, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
								self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcB.orbital_position, toneburstmode = diseqcParam.NO, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.AB, fastDiSEqC = fastDiSEqC, setVoltageTone = setVoltageTone, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
							elif nim.diseqcMode.value == "diseqc_a_b_c_d":		#DiSEqC A/B/C/D
								fastDiSEqC = nim.simpleDiSEqCOnlyOnSatChange.value
								setVoltageTone = nim.simpleDiSEqCSetVoltageTone.value
								self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcA.orbital_position, toneburstmode = diseqcParam.NO, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.AA, fastDiSEqC = fastDiSEqC, setVoltageTone = setVoltageTone, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
								self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcB.orbital_position, toneburstmode = diseqcParam.NO, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.AB, fastDiSEqC = fastDiSEqC, setVoltageTone = setVoltageTone, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
								self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcC.orbital_position, toneburstmode = diseqcParam.NO, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.BA, fastDiSEqC = fastDiSEqC, setVoltageTone = setVoltageTone, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
								self.addLNBSimple(sec, slotid = slot_id, input = input, orbpos = nim.diseqcD.orbital_position, toneburstmode = diseqcParam.NO, diseqcmode = diseqcParam.V1_0, diseqcpos = diseqcParam.BB, fastDiSEqC = fastDiSEqC, setVoltageTone = setVoltageTone, diseqc13V = nim.diseqc13V.value, degreePerSecond = nim.degreePerSecond.float)
							elif nim.diseqcMode.value == "positioner":		#Positioner
								if nim.latitudeOrientation.value == "north":
									laValue = rotorParam.NORTH
								else:
									laValue = rotorParam.SOUTH
								if nim.longitudeOrientation.value == "east":
									loValue = rotorParam.EAST
								else:
									loValue = rotorParam.WEST
								inputPowerDelta=nim.powerThreshold.value
								useInputPower=False
								turning_speed=0
								if nim.powerMeasurement.value:
									useInputPower=True
									turn_speed_dict = { "fast": rotorParam.FAST, "slow": rotorParam.SLOW }
									if nim.turningSpeed.value in turn_speed_dict:
										turning_speed = turn_speed_dict[nim.turningSpeed.value]
									else:
										beg_time = localtime(nim.fastTurningBegin.value)
										end_time = localtime(nim.fastTurningEnd.value)
										turning_speed = ((beg_time.tm_hour+1) * 60 + beg_time.tm_min + 1) << 16
										turning_speed |= (end_time.tm_hour+1) * 60 + end_time.tm_min + 1
								self.addLNBSimple(sec, slotid = slot_id, input = input, diseqcmode = 3,
									longitude = nim.longitude.float,
									loDirection = loValue,
									latitude = nim.latitude.float,
									laDirection = laValue,
									turningSpeed = turning_speed,
									useInputPower = useInputPower,
									inputPowerDelta = inputPowerDelta,
									diseqc13V = nim.diseqc13V.value)
						elif nim.sat.configMode.value == "advanced": #advanced config
							self.updateAdvanced(sec, slot.slot, input, slot_id if sl.inputs else None)
		Log.i("sec config completed")

	def updateAdvanced(self, sec, slotid, input, slotid_child=None):

		if slotid_child is not None:
			channel = slotid_child - slotid
			#print "updateAdvanced", slotid, "hw input", input, "channel", channel, "child slot", slotid_child

		lnbSat = {}
		for x in range(1,37):
			lnbSat[x] = []

		#wildcard for all satellites ( for rotor )
		for x in range(3601, 3605):
			lnb = int(config.Nims[slotid].advanced.sat[x].lnb.value)
			if lnb != 0:
				Log.i("add rotor satellites to lnb" + str(lnb))
				for x in self.NimManager.satList:
					lnbSat[lnb].append(x[0])

		for x in self.NimManager.satList:
			lnb = int(config.Nims[slotid].advanced.sat[x[0]].lnb.value)
			if lnb != 0:
				Log.i("add " + str(x[0]) + " to " + str(lnb))
				lnbSat[lnb].append(x[0])

		for x in range(1,37):
			if len(lnbSat[x]) > 0:
				currLnb = config.Nims[slotid].advanced.lnb[x]
				scr_idx = -1

				if currLnb.lof.value == "unicable" and slotid_child is not None:
					if currLnb.unicable.value == "unicable_user":
						Log.i("warning Slot " + str(slotid) + " Channel " + str(channel) + " LNB " + str(x) + " unicable user defined is not yet working with multi channel tuners... skip")
						continue
					elif currLnb.unicable.value == "unicable_lnb":
						manufacturer = currLnb.unicableLnb
					else:
						manufacturer = currLnb.unicableMatrix

					vcos = manufacturer.scrs.value
					num_vco = len(vcos)
					if num_vco < 1:
						Log.i("warning Slot " + str(slotid) + " Channel " + str(channel) + " LNB " + str(x) + " not enough SCRs configured... no unicable possible with this channel... skip")
						continue
					elif num_vco <= channel:
						Log.i("warning Slot " + str(slotid) + " Channel " + str(channel) + " LNB " + str(x) + " not enough SCRs configured... maybe no unicable possible with this channel!")

					vco = vcos[channel % num_vco]

					cnt = 0
					for v in manufacturer.vco:
						if v.value == vco:
							scr_idx = cnt
							break
						cnt += 1

					if scr_idx == -1:
						Log.i("warning Slot " + str(slotid) + " Channel " + str(channel) + " LNB " + str(x) + " could not found SCR IDX for VCO " + str(vco) + " ... no unicable possible with this channel... skip")
						continue

					Log.i("use SCR" + str(scr_idx+1) + " " + str(vco) + "Mhz")

				sec.addLNB()
				sec.setLNBTunerInput(input)

				if x < 33:
					sec.setLNBNum(x)
				else:
					sec.setLNBNum(1)

				if slotid_child is not None:
					tunermask = 1 << slotid_child
				else:
					tunermask = 1 << slotid

					if slotid in self.equal:
						for slot in self.equal[slotid]:
							tunermask |= (1 << slot)
					if slotid in self.linked:
						for slot in self.linked[slotid]:
							tunermask |= (1 << slot)

				dm = currLnb.diseqcMode.value

				if currLnb.lof.value != "unicable":
					sec.setLNBSatCR(-1)

				if currLnb.lof.value == "universal_lnb":
					sec.setLNBLOFL(9750000)
					sec.setLNBLOFH(10600000)
					sec.setLNBThreshold(11700000)
				elif currLnb.lof.value == "unicable":

					def setupUnicable(configManufacturer, ProductDict, scr_idx):
						manufacturer = ProductDict
						if scr_idx == -1:
							scr_idx = manufacturer.scr.index

						sec.setLNBSatCR(scr_idx)
						sec.setLNBSatCRvco(manufacturer.vco[scr_idx].value * 1000)
						sec.setLNBSatCRpositions(manufacturer.positions[0].value)
						sec.setLNBSatCRmode(manufacturer.mode.value)
						sec.setLNBLOFL(manufacturer.lofl[0].value * 1000)
						sec.setLNBLOFH(manufacturer.lofh[0].value * 1000)
						sec.setLNBThreshold(manufacturer.loft[0].value * 1000)
						sec.setLNBPowerOnDelay(manufacturer.poweron_delay.value)

					if currLnb.unicable.value == "unicable_user":
						sec.setLNBLOFL(currLnb.lofl.value * 1000)
						sec.setLNBLOFH(currLnb.lofh.value * 1000)
						sec.setLNBThreshold(currLnb.threshold.value * 1000)
						sec.setLNBSatCR(currLnb.satcruser.index)
						sec.setLNBSatCRvco(currLnb.satcrvcouser[currLnb.satcruser.index].value*1000)
						sec.setLNBSatCRpositions(1) # HACK
						sec.setLNBSatCRmode(currLnb.satcruser_mode.index)
						sec.setLNBPowerOnDelay(0)
					elif currLnb.unicable.value == "unicable_matrix":
						setupUnicable(currLnb.unicableMatrix.manufacturer, currLnb.unicableMatrix, scr_idx)
					elif currLnb.unicable.value == "unicable_lnb":
						setupUnicable(currLnb.unicableLnb.manufacturer, currLnb.unicableLnb, scr_idx)
					if currLnb.unicable_use_pin.value:
						sec.setLNBSatCRpin(currLnb.unicable_pin.value)
					else:
						sec.setLNBSatCRpin(-1)

					if slotid_child is None:
						try:
							if config.Nims[slotid].advanced.unicableconnected.value:
								self.linkNIMs(sec, slotid, int(config.Nims[slotid].advanced.unicableconnectedTo.value))
							else:
								config.Nims[slotid].advanced.unicableconnectedTo.save_forced = False
						except:
							pass

						try:
							if dm == "1_2" and config.Nims[slotid].advanced.unicabledepends.value:
								self.setSatposDepends(sec, slotid, int(config.Nims[slotid].advanced.unicabledependsOn.value))
							else:
								config.Nims[slotid].advanced.unicabledependsOn.save_forced = False
						except:
							pass

				elif currLnb.lof.value == "c_band":
					sec.setLNBLOFL(5150000)
					sec.setLNBLOFH(5150000)
					sec.setLNBThreshold(5150000)
				elif currLnb.lof.value == "user_defined":
					sec.setLNBLOFL(currLnb.lofl.value * 1000)
					sec.setLNBLOFH(currLnb.lofh.value * 1000)
					sec.setLNBThreshold(currLnb.threshold.value * 1000)

#				if currLnb.output_12v.value == "0V":
#					pass # nyi in drivers
#				elif currLnb.output_12v.value == "12V":
#					pass # nyi in drivers

				if currLnb.increased_voltage.value:
					sec.setLNBIncreasedVoltage(True)
				else:
					sec.setLNBIncreasedVoltage(False)

				if dm == "none":
					sec.setDiSEqCMode(diseqcParam.NONE)
				elif dm == "1_0":
					sec.setDiSEqCMode(diseqcParam.V1_0)
				elif dm == "1_1":
					sec.setDiSEqCMode(diseqcParam.V1_1)
				elif dm == "1_2":
					sec.setDiSEqCMode(diseqcParam.V1_2)

					if slotid in self.satposdepends:
						for slot in self.satposdepends[slotid]:
							tunermask |= (1 << slot)

				if dm != "none":
					if currLnb.toneburst.value == "none":
						sec.setToneburst(diseqcParam.NO)
					elif currLnb.toneburst.value == "A":
						sec.setToneburst(diseqcParam.A)
					elif currLnb.toneburst.value == "B":
						sec.setToneburst(diseqcParam.B)

					# Committed Diseqc Command
					cdc = currLnb.commitedDiseqcCommand.value

					c = { "none": diseqcParam.SENDNO,
						"AA": diseqcParam.AA,
						"AB": diseqcParam.AB,
						"BA": diseqcParam.BA,
						"BB": diseqcParam.BB }

					if cdc in c:
						sec.setCommittedCommand(c[cdc])
					else:
						sec.setCommittedCommand(int(cdc))

					sec.setFastDiSEqC(currLnb.fastDiseqc.value)

					sec.setSeqRepeat(currLnb.sequenceRepeat.value)

					if currLnb.diseqcMode.value == "1_0":
						currCO = currLnb.commandOrder1_0.value
						sec.setRepeats(0)
					else:
						currCO = currLnb.commandOrder.value

						udc = int(currLnb.uncommittedDiseqcCommand.value)
						if udc > 0:
							sec.setUncommittedCommand(0xF0|(udc-1))
						else:
							sec.setUncommittedCommand(0) # SENDNO

						sec.setRepeats({"none": 0, "one": 1, "two": 2, "three": 3}[currLnb.diseqcRepeats.value])

					# 0 "committed, toneburst",
					# 1 "toneburst, committed",
					# 2 "committed, uncommitted, toneburst",
					# 3 "toneburst, committed, uncommitted",
					# 4 "uncommitted, committed, toneburst"
					# 5 "toneburst, uncommitted, commmitted"
					order_map = {"ct": 0, "tc": 1, "cut": 2, "tcu": 3, "uct": 4, "tuc": 5}
					sec.setCommandOrder(order_map[currCO])

				if dm == "1_2":
					latitude = currLnb.latitude.float
					sec.setLatitude(latitude)
					longitude = currLnb.longitude.float
					sec.setLongitude(longitude)
					if currLnb.latitudeOrientation.value == "north":
						sec.setLaDirection(rotorParam.NORTH)
					else:
						sec.setLaDirection(rotorParam.SOUTH)
					if currLnb.longitudeOrientation.value == "east":
						sec.setLoDirection(rotorParam.EAST)
					else:
						sec.setLoDirection(rotorParam.WEST)

					if currLnb.powerMeasurement.value:
						sec.setUseInputpower(True)
						sec.setInputpowerDelta(currLnb.powerThreshold.value)
						turn_speed_dict = { "fast": rotorParam.FAST, "slow": rotorParam.SLOW }
						if currLnb.turningSpeed.value in turn_speed_dict:
							turning_speed = turn_speed_dict[currLnb.turningSpeed.value]
						else:
							beg_time = localtime(currLnb.fastTurningBegin.value)
							end_time = localtime(currLnb.fastTurningEnd.value)
							turning_speed = ((beg_time.tm_hour + 1) * 60 + beg_time.tm_min + 1) << 16
							turning_speed |= (end_time.tm_hour + 1) * 60 + end_time.tm_min + 1
						sec.setRotorTurningSpeed(turning_speed)
					else:
						sec.setUseInputpower(False)
						sec.setDegreePerSecond(int(currLnb.degreePerSecond.float*10))

				sec.setLNBSlotMask(tunermask)

				sec.setLNBPrio(int(currLnb.prio.value))

				# finally add the orbital positions
				for y in lnbSat[x]:
					self.addSatellite(sec, y)
					if x > 32:
						satpos = x > 32 and (3604-(36 - x)) or y
					else:
						satpos = y
					currSat = config.Nims[slotid].advanced.sat[satpos]
					if currSat.voltage.value == "polarization":
						if config.Nims[slotid].diseqc13V.value:
							sec.setVoltageMode(switchParam.HV_13)
						else:
							sec.setVoltageMode(switchParam.HV)
					elif currSat.voltage.value == "13V":
						sec.setVoltageMode(switchParam._14V)
					elif currSat.voltage.value == "18V":
						sec.setVoltageMode(switchParam._18V)

					if currSat.tonemode.value == "band":
						sec.setToneMode(switchParam.HILO)
					elif currSat.tonemode.value == "on":
						sec.setToneMode(switchParam.ON)
					elif currSat.tonemode.value == "off":
						sec.setToneMode(switchParam.OFF)

					if not currSat.usals.value and x < 34:
						sec.setRotorPosNum(currSat.rotorposition.value)
					else:
						sec.setRotorPosNum(0) #USALS

	def __init__(self, nimmgr):
		self.NimManager = nimmgr
		self.configuredSatellites = set()
		self.update()

class NIM(object):
	SUPPORTED_TYPES = ("DVB-S", "DVB-C", "DVB-T", "DVB-T2", "DVB-S2", None)

	def __init__(self, slot, type, description, has_outputs = True, internally_connectable = None, multi_type = {}, frontend_id = None, i2c = None, is_empty = False, input_name = None, inputs = None):
		self.slot = slot
		if type not in NIM.SUPPORTED_TYPES:
			print("warning: unknown NIM type %s, not using." % type)
			type = None

		self.description = description
		self.has_outputs = has_outputs
		self.internally_connectable = internally_connectable
		if type and not multi_type:
			multi_type = { '0' : type }
		self._types = multi_type
		self.i2c = i2c
		self.frontend_id = frontend_id
		self.__is_empty = is_empty
		self.input_name = input_name
		try:
			self.channel = int(input_name[1]) - 1
		except:
			self.channel = 0

		caps = 0 if self.frontend_id is None else eDVBResourceManager.getInstance().getFrontendCapabilities(self.frontend_id)
		self.can_auto_fec_s2 = self.description != "Alps BSBE2"
		self.can_modulation_auto = len(multi_type) > 1 or self.description.startswith("Si216") or self.description in ('BCM45308X', 'BCM45208', 'BCM73625 (G3)', 'BCM3158', 'STiD135')
		self.can_s_s2_auto_delsys = self.description.startswith("Si216") or self.description in ('STiD135')
		self.can_pls_s2 = self.can_multistream_s2 = (caps & iDVBFrontend.canDVBS2Multistream) or self.description in ('Si2166D', 'Si2169D', 'STiD135')

		self.inputs = inputs

	def isEnabled(self, what):
		ret = self.isCompatible(what)
		if ret:
			if self.inputs is not None and self.channel >= len(self.inputs):
				return False
			elif what in ('DVB-S', 'DVB-S2'):
				return self.config.sat.configMode.value != "nothing"
			elif what in ('DVB-T', 'DVB-T2'):
				return self.config.terrest.configMode.value != "nothing"
			elif what in ('DVB-C'):
				return self.config.cable.configMode.value != "nothing"
		return ret

	def isCompatible(self, what):
		if not self.isSupported():
			return False
		compatible = {
				None: (None,),
				"DVB-S": ("DVB-S", None),
				"DVB-C": ("DVB-C", None),
				"DVB-T": ("DVB-T", None),
				"DVB-T2": ("DVB-T", "DVB-T2", None),
				"DVB-S2": ("DVB-S", "DVB-S2", None)
			}
		for ntype in six.itervalues(self._types):
			if what in compatible[ntype]:
				return True
		return False

	def getTypes(self):
		return self._types
	types = property(getTypes)

	def getType(self):
		if not self._types:
			return None
		type = list(self._types.values())[0]
		if len(self._types) > 1:
			import traceback
			print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\nNIM Slot", self.getSlotInputName(True), "supports multiple types", self._types, "\nthis function is deprecated and just for backward compatibility it should not be used anymore\nplease report to plugin author... ", type, "is returned for this nim now")
			traceback.print_stack(limit = 2)
		return type
	type = property(getType)

	def connectableTo(self):
		connectable = {
				"DVB-S": ("DVB-S", "DVB-S2"),
				"DVB-C": ("DVB-C",),
				"DVB-T": ("DVB-T",),
				"DVB-T2": ("DVB-T", "DVB-T2"),
				"DVB-S2": ("DVB-S", "DVB-S2")
			}
		connectables = []
		for ntype in six.itervalues(self._types):
			connectables += connectable[ntype]
		return connectables

	def getSlotInputName(self, for_input_desc=False):
		name = self.input_name
		if name is None:
			name = chr(ord('A') + self.slot)
		return name [:-1] if self.inputs and len(self.inputs) == 1 and for_input_desc else name

	slot_input_name = property(getSlotInputName)

	def getSlotName(self):
		# get a friendly description for a slot name.
		# we name them "Tuner A/B/C/...", because that's what's usually written on the back
		# of the device.
		descr = _("Tuner ")
		return descr + self.getSlotInputName(True)

	slot_name = property(getSlotName)

	def getSlotID(self):
		return chr(ord('A') + self.slot)

	def getI2C(self):
		return self.i2c

	def hasOutputs(self):
		return self.has_outputs

	def internallyConnectableTo(self):
		return self.internally_connectable

	def setInternalLink(self):
		if self.internally_connectable is not None:
			print("setting internal link on frontend id", self.frontend_id)
			with open("/proc/stb/frontend/%d/rf_switch" % self.frontend_id, "w") as f:
				f.write("internal")

	def removeInternalLink(self):
		if self.internally_connectable is not None:
			print("removing internal link on frontend id", self.frontend_id)
			with open("/proc/stb/frontend/%d/rf_switch" % self.frontend_id, "w") as f:
				f.write("external")

	def isMultiType(self):
		return (len(self._types) > 1)

	def isEmpty(self):
		return self.__is_empty

	# empty tuners are supported!
	def isSupported(self):
		return (self.frontend_id is not None) or self.__is_empty

	# returns dict {<slotid>: <type>}
	def getMultiTypeList(self):
		return self._types

	slot_id = property(getSlotID)

	def getFriendlyType(self):
		return _("empty") if not self._types else " / ".join(list(self._types.values()))

	friendly_type = property(getFriendlyType)

	def getFriendlyFullDescription(self):
		nim_text = self.slot_name + ": "

		if self.empty:
			nim_text += _("(empty)")
		elif not self.isSupported():
			nim_text += self.description + " (" + _("not supported") + ")"
		else:
			nim_text += self.description + " (" + self.friendly_type + ")"

		return nim_text

	friendly_full_description = property(getFriendlyFullDescription)
	config = property(lambda self: config.Nims[self.slot])
	empty = property(lambda self: not self._types)

class NimManager:
	config_mode_str = {
		"nothing" : _("inactive"),
		"multi" : _("multiple"),
		"enabled" : _("active"),
		"simple" : _("simple"),
		"advanced" : _("advanced"),
		"equal" : _("equal to"),
		"satposdepends" : _("additional cable of motorized LNB"),
		"loopthrough" : "", # description is dynamically generated by connectedToChanged function (InitNimManager)
		}

	def getConfigModeTuple(self, mode):
		return (mode, NimManager.config_mode_str[mode])

	def getConfiguredSats(self):
		if self.sec:
			return self.sec.getConfiguredSats()
		else:
			return set()

	def getTransponders(self, pos):
		if pos in self.transponders:
			return self.transponders[pos]
		else:
			return []

	def getTranspondersCable(self, nim):
		nimConfig = config.Nims[nim]
		if nimConfig.cable.configMode.value != "nothing" and nimConfig.cable.scan_type.value == "provider":
			return self.transponderscable[self.cablesList[nimConfig.cable.scan_provider.index][0]]
		return [ ]

	def getTranspondersTerrestrial(self, region):
		return self.transpondersterrestrial[region]

	def getCableDescription(self, nim):
		return self.cablesList[config.Nims[nim].scan_provider.index][0]

	def getCableFlags(self, nim):
		return self.cablesList[config.Nims[nim].scan_provider.index][1]

	def getTerrestrialDescription(self, nim):
		return self.terrestrialsList[config.Nims[nim].terrest.provider.index][0]

	def getTerrestrialFlags(self, nim):
		return self.terrestrialsList[config.Nims[nim].terrest.provider.index][1]

	def getSatDescription(self, pos):
		return self.satellites[pos]

	def sortFunc(self, x):
		orbpos = x[0]
		if orbpos > 1800:
			return orbpos - 3600
		else:
			return orbpos + 1800

	def readTransponders(self):
		# read initial networks from file. we only read files which we are interested in,
		# which means only these where a compatible tuner exists.
		self.satellites = { }
		self.transponders = { }
		self.transponderscable = { }
		self.transpondersterrestrial = { }
		db = eDVBDB.getInstance()
		if self.hasNimType("DVB-S"):
			print("Reading satellites.xml")
			db.readSatellites(self.satList, self.satellites, self.transponders)
			self.satList.sort(key = self.sortFunc) # sort by orbpos
			#print "SATLIST", self.satList
			#print "SATS", self.satellites
			#print "TRANSPONDERS", self.transponders

		if self.hasNimType("DVB-C"):
			print("Reading cables.xml")
			db.readCables(self.cablesList, self.transponderscable)
#			print "CABLIST", self.cablesList
#			print "TRANSPONDERS", self.transponders

		if self.hasNimType("DVB-T"):
			print("Reading terrestrial.xml")
			db.readTerrestrials(self.terrestrialsList, self.transpondersterrestrial)
#			print "TERLIST", self.terrestrialsList
#			print "TRANSPONDERS", self.transpondersterrestrial

	def enumerateNIMs(self):
		# enum available NIMs. This is currently very dreambox-centric and uses the /proc/bus/nim_sockets interface.
		# the result will be stored into nim_slots.
		# the content of /proc/bus/nim_sockets looks like:
		# NIM Socket 0:
		#          Type: DVB-S
		#          Name: BCM4501 DVB-S2 NIM (internal)
		# NIM Socket 1:
		#          Type: DVB-S
		#          Name: BCM4501 DVB-S2 NIM (internal)
		# NIM Socket 2:
		#          Type: DVB-T
		#          Name: Philips TU1216
		# NIM Socket 3:
		#          Type: DVB-S
		#          Name: Alps BSBE1 702A

		#
		# Type will be either "DVB-S", "DVB-S2", "DVB-T", "DVB-C", "DVB-T2" or None.

		# nim_slots is an array which has exactly one entry for each slot, even for empty ones.
		self.nim_slots = [ ]

		nimfile = tryOpen("/proc/bus/nim_sockets")

		if nimfile is None:
			return

		current_slot = None

		entries = {}
		for line in nimfile.readlines():
			if line == "":
				break
			if line.strip().startswith("NIM Socket"):
				parts = line.strip().split(" ")
				current_slot = int(parts[2][:-1])
				entries[current_slot] = {}
			elif line.strip().startswith("Type:"):
				entries[current_slot]["type"] = str(line.strip()[6:])
				entries[current_slot]["isempty"] = False
			elif line.strip().startswith("Input_Name:"):
				entries[current_slot]["input_name"] = str(line.strip()[12:])
			elif line.strip().startswith("Name:"):
				entries[current_slot]["name"] = str(line.strip()[6:])
				entries[current_slot]["isempty"] = False
			elif line.strip().startswith("Has_Outputs:"):
				input = str(line.strip()[len("Has_Outputs:") + 1:])
				entries[current_slot]["has_outputs"] = (input == "yes")
			elif line.strip().startswith("Internally_Connectable:"):
				input = int(line.strip()[len("Internally_Connectable:") + 1:])
				entries[current_slot]["internally_connectable"] = input
			elif line.strip().startswith("Frontend_Device:"):
				input = int(line.strip()[len("Frontend_Device:") + 1:])
				entries[current_slot]["frontend_device"] = input
			elif  line.strip().startswith("Mode"):
				# "Mode 0: DVB-T" -> ["Mode 0", " DVB-T"]
				split = line.strip().split(":")
				# "Mode 0" -> ["Mode, "0"]
				split2 = split[0].split(" ")
				modes = entries[current_slot].get("multi_type", {})
				modes[split2[1]] = split[1].strip()
				entries[current_slot]["multi_type"] = modes
			elif line.strip().startswith("I2C_Device:"):
				input = int(line.strip()[len("I2C_Device:") + 1:])
				entries[current_slot]["i2c"] = input
			elif line.strip().startswith("empty"):
				entries[current_slot]["type"] = None
				entries[current_slot]["name"] = _("N/A")
				entries[current_slot]["isempty"] = True
		nimfile.close()

		channel = -1
		for id, entry in entries.items():
			if not ("name" in entry and "type" in entry):
				entry["name"] =  _("N/A")
				entry["type"] = None
			if not ("i2c" in entry):
				entry["i2c"] = None
			entry["inputs"] = None
			if "frontend_device" in entry: # check if internally connectable
				if exists("/proc/stb/frontend/%d/rf_switch" % entry["frontend_device"]):
					entry["internally_connectable"] = id -1 if entries[id]["input_name"][-1] == '2' else id + 1
				else:
					entry["internally_connectable"] = None
				inputChoicesFile = tryOpen("/proc/stb/frontend/%d/input_choices" % entry["frontend_device"])
				if inputChoicesFile:
					choices = inputChoicesFile.readline()
					if choices:
						entry["inputs"] = choices[:-1].split(' ')
			else:
				entry["frontend_device"] = entry["internally_connectable"] = None
			if not ("multi_type" in entry):
				entry["multi_type"] = {}
			nim = NIM(slot = id, description = entry["name"], type = entry["type"], internally_connectable = entry["internally_connectable"], multi_type = entry["multi_type"], frontend_id = entry["frontend_device"], i2c = entry["i2c"], is_empty = entry["isempty"], input_name = entry.get("input_name", None), inputs = entry["inputs"] )
			# calculate and set number of channels
			if channel != -1 and nim.channel <= channel:
				slot_start = id - 1 - channel
				for slot in range(slot_start, slot_start + channel + 1):
					self.nim_slots[slot].channels = channel + 1
			channel = nim.channel
			self.nim_slots.append(nim)
		# set number of channels for last slot
		slot_start = id - channel
		for slot in range(slot_start, slot_start + channel + 1):
			self.nim_slots[slot].channels = channel + 1

	def hasNimType(self, chktype):
		ret = False
		for slot in self.nim_slots:
			if slot.isCompatible(chktype):
				return True
		return ret

	def getNimType(self, slotid):
		return self.nim_slots[slotid].type

	def getNimTypes(self, slotid):
		return list(self.nim_slots[slotid].types.values())

	def getNimDescription(self, slotid):
		return self.nim_slots[slotid].friendly_full_description

	def getNimName(self, slotid):
		return self.nim_slots[slotid].description

	def getNimSlotInputName(self, slotid, for_input_desc=False):
		# returns just "A", "B", ...
		return self.nim_slots[slotid].getSlotInputName(for_input_desc)

	def getNimSlotName(self, slotid):
		# returns a friendly description string ("Tuner A", "Tuner B" etc.)
		return self.nim_slots[slotid].slot_name

	def getNim(self, slotid):
		return self.nim_slots[slotid]

	def getI2CDevice(self, slotid):
		return self.nim_slots[slotid].getI2C()

	def getNimListOfType(self, type, exception = -1):
		# returns a list of indexes for NIMs compatible to the given type, except for 'exception'
		result = []
		for x in self.nim_slots:
			if x.isCompatible(type) and x.slot != exception:
				result.append(x.slot)
		return result

	def getNimListForSlot(self, slotid):
		nimList = []
		types = self.getNimTypes(slotid)
		if "DVB-S2" in types:
			nimList.extend(self.getNimListOfType("DVB-S", slotid))
		elif type == "DVB-T2":
			nimList.extend(self.getNimListOfType("DVB-T", slotid))
		return nimList

	def __init__(self):
		self.satList = [ ]
		self.cablesList = []
		self.terrestrialsList = []
		self.sec = None
		self.enumerateNIMs()
		self.readTransponders()

	# get a list with the friendly full description
	def nimList(self):
		result = [ ]
		for slot in self.nim_slots:
			if slot.inputs is None or slot.channel == 0:
				result.append(slot.friendly_full_description)
		return result

	def getSlotCount(self):
		return len(self.nim_slots)

	def hasOutputs(self, slotid):
		return self.nim_slots[slotid].hasOutputs()

	def nimInternallyConnectableTo(self, slotid):
		return self.nim_slots[slotid].internallyConnectableTo()

	def nimRemoveInternalLink(self, slotid):
		self.nim_slots[slotid].removeInternalLink()

	def canConnectTo(self, slotid):
		slots = []

		if self.nim_slots[slotid].inputs is not None:
			return slots

		internally_connectable = self.nimInternallyConnectableTo(slotid)
		if internally_connectable is not None:
			slots.append(internally_connectable)
		if "DVB-S" in self.nim_slots[slotid].connectableTo():
			for slot in self.getNimListOfType("DVB-S", exception = slotid):
				if self.hasOutputs(slot) and slot not in slots:
					slots.append(slot)

		# remove nims, that have a conntectedTo reference on
		for testnim in slots[:]:
			nim = self.nim_slots[testnim]

			# FIXMEE
			# no support for satpos depends, equal to and loopthough setting for nims with
			# with multiple inputs and multiple channels
			if not nim.isEnabled('DVB-S') or nim.inputs is not None:
				slots.remove(testnim)
			else:
				nimConfig = self.getNimConfig(testnim)

				if nimConfig.sat.configMode.value == "loopthrough" and int(nimConfig.connectedTo.value) == slotid:
					slots.remove(testnim)

				if nimConfig.sat.configMode.value == "advanced":
					is_unicable = False
					for x in range(3601, 3605):
						lnb = int(nimConfig.advanced.sat[x].lnb.value)
						if lnb != 0 and nimConfig.advanced.lnb[lnb].lof.value == "unicable":
							is_unicable = True
					if not is_unicable:
						for sat in nimConfig.advanced.sat.values():
							lnb_num = int(sat.lnb.value)
							if lnb_num != 0 and nimConfig.advanced.lnb[lnb_num].lof.value == "unicable":
								is_unicable = True
					if is_unicable:
						slots.remove(testnim)
						if not nimConfig.advanced.unicableconnected.value or int(nimConfig.advanced.unicableconnectedTo.value) != slotid:
							slots.append((testnim, 1))
						continue

			if testnim in slots:
				slots.remove(testnim)
				slots.append((testnim, 0))

		slots.sort()

		return slots

	def canEqualTo(self, slotid):
		nimList = self.getNimListForSlot(slotid)
		for nim in nimList[:]:
			mode = self.getNimConfig(nim)
			Nim = self.nim_slots[nim]
			# FIXMEE
			# no support for satpos depends, equal to and loopthough setting for nims with
			# with multiple inputs and multiple channels
			if slotid == nim or not Nim.isEnabled('DVB-S') or Nim.inputs is not None or \
				mode.sat.configMode.value in ("loopthrough", "satposdepends"):
				nimList.remove(nim)
			else:
				is_unicable = False
				if mode.sat.configMode.value == "advanced":
					for x in range(3601, 3605):
						lnb = int(mode.advanced.sat[x].lnb.value)
						if lnb != 0 and mode.advanced.lnb[lnb].lof.value == "unicable":
							is_unicable = True
							break;
					if not is_unicable:
						for sat in mode.advanced.sat.values():
							lnb_num = int(sat.lnb.value)
							if lnb_num != 0 and mode.advanced.lnb[lnb_num].lof.value == "unicable":
								is_unicable = True
								break;
				if is_unicable:
					# FIXMEE no equal to for unicable .. because each tuner need a own SCR...
					nimList.remove(nim)
		return nimList

	def canDependOn(self, slotid):
		positionerList = []
		nimList = self.getNimListForSlot(slotid)
		for nim in nimList[:]:
			mode = self.getNimConfig(nim)
			nimHaveRotor = mode.sat.configMode.value == "simple" and mode.diseqcMode.value == "positioner"
			if not nimHaveRotor and mode.sat.configMode.value == "advanced":
				for x in range(3601, 3605):
					lnb = int(mode.advanced.sat[x].lnb.value)
					if lnb != 0:
						nimHaveRotor = lnb
						break
				if not nimHaveRotor:
					for sat in mode.advanced.sat.values():
						lnb_num = int(sat.lnb.value)
						diseqcmode = lnb_num and mode.advanced.lnb[lnb_num].diseqcMode.value or ""
						if diseqcmode == "1_2":
							nimHaveRotor = lnb_num
							break
			# FIXMEE
			# no support for satpos depends, equal to and loopthough setting for nims with
			# with multiple inputs and multiple channels
			if nimHaveRotor and self.nim_slots[nim].inputs is None:
				if nimHaveRotor == True:
					positionerList.append((nim, 0))
				elif nimHaveRotor > 0:
					if mode.advanced.lnb[nimHaveRotor].lof.value == "unicable":
						if not mode.advanced.unicabledepends.value or int(mode.advanced.unicabledependsOn.value) != slotid:
							positionerList.append((nim, 1))
					else:
						positionerList.append((nim, 0))

		return positionerList

	def getNimConfig(self, slotid):
		return config.Nims[slotid]

	def getSatName(self, pos):
		for sat in self.satList:
			if sat[0] == pos:
				return sat[1]
		return _("N/A")

	def getSatList(self):
		return self.satList

	# returns True if something is configured to be connected to this nim
	# if slotid == -1, returns if something is connected to ANY nim
	def somethingConnected(self, slotid = -1):
		if (slotid == -1):
			connected = False
			for id in range(self.getSlotCount()):
				if self.somethingConnected(id):
					connected = True
			return connected
		else:
			nim = config.Nims[slotid]

			return (self.nim_slots[slotid].isCompatible("DVB-S") and nim.sat.configMode.value != "nothing") or \
				(self.nim_slots[slotid].isCompatible("DVB-C") and nim.cable.configMode.value != "nothing") or \
				(self.nim_slots[slotid].isCompatible("DVB-T") and nim.terrest.configMode.value != "nothing")

	def getSatListForNim(self, slotid):
		result = []
		if self.nim_slots[slotid].isEnabled("DVB-S"):
			nim = config.Nims[slotid]
			#print "slotid:", slotid

			#print "self.satellites:", self.satList[config.Nims[slotid].diseqcA.index]
			#print "diseqcA:", config.Nims[slotid].diseqcA.value
			configMode = nim.sat.configMode.value

			if configMode == "equal":
				slotid = int(nim.connectedTo.value)
				nim = config.Nims[slotid]
				configMode = nim.sat.configMode.value

			elif configMode in ("loopthrough", "satposdepends"):
				# satposdepends is not completely correct, but better than crashing in the channel search configuration
				slotid = self.sec.getRoot(slotid, int(nim.connectedTo.value))
				nim = config.Nims[slotid]
				configMode = nim.sat.configMode.value

			if configMode == "simple":
				dm = nim.diseqcMode.value
				if dm in ("single", "toneburst_a_b", "diseqc_a_b", "diseqc_a_b_c_d"):
					if nim.diseqcA.orbital_position != 3601:
						result.append(self.satList[nim.diseqcA.index-1])
				if dm in ("toneburst_a_b", "diseqc_a_b", "diseqc_a_b_c_d"):
					if nim.diseqcB.orbital_position != 3601:
						result.append(self.satList[nim.diseqcB.index-1])
				if dm == "diseqc_a_b_c_d":
					if nim.diseqcC.orbital_position != 3601:
						result.append(self.satList[nim.diseqcC.index-1])
					if nim.diseqcD.orbital_position != 3601:
						result.append(self.satList[nim.diseqcD.index-1])
				if dm == "positioner":
					for x in self.satList:
						result.append(x)
			elif configMode == "advanced":
				for x in range(3601, 3605):
					if int(nim.advanced.sat[x].lnb.value) != 0:
						for x in self.satList:
							result.append(x)
				if not result:
					for x in self.satList:
						if int(nim.advanced.sat[x[0]].lnb.value) != 0:
							result.append(x)
		return result

	def getRotorSatListForNim(self, slotid):
		result = []
		if self.nim_slots[slotid].isCompatible("DVB-S"):
			#print "slotid:", slotid
			#print "self.satellites:", self.satList[config.Nims[slotid].diseqcA.value]
			#print "diseqcA:", config.Nims[slotid].diseqcA.value
			configMode = config.Nims[slotid].sat.configMode.value
			if configMode == "simple":
				if config.Nims[slotid].diseqcMode.value == "positioner":
					for x in self.satList:
						result.append(x)
			elif configMode == "advanced":
				nim = config.Nims[slotid]
				for x in range(3601, 3605):
					if int(nim.advanced.sat[x].lnb.value) != 0:
						for x in self.satList:
							result.append(x)
				if not result:
					for x in self.satList:
						lnbnum = int(nim.advanced.sat[x[0]].lnb.value)
						if lnbnum != 0:
							lnb = nim.advanced.lnb[lnbnum]
							if lnb.diseqcMode.value == "1_2":
								result.append(x)
		return result


def InitSecParams():
	config.sec = ConfigSubsection()

	x = ConfigInteger(default=25, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_CONT_TONE_DISABLE_BEFORE_DISEQC, configElement.value))
	config.sec.delay_after_continuous_tone_disable_before_diseqc = x

	x = ConfigInteger(default=10, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_FINAL_CONT_TONE_CHANGE, configElement.value))
	config.sec.delay_after_final_continuous_tone_change = x

	x = ConfigInteger(default=10, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_FINAL_VOLTAGE_CHANGE, configElement.value))
	config.sec.delay_after_final_voltage_change = x

	x = ConfigInteger(default=120, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_BETWEEN_DISEQC_REPEATS, configElement.value))
	config.sec.delay_between_diseqc_repeats = x

	x = ConfigInteger(default=50, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_LAST_DISEQC_CMD, configElement.value))
	config.sec.delay_after_last_diseqc_command = x

	x = ConfigInteger(default=50, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_TONEBURST, configElement.value))
	config.sec.delay_after_toneburst = x

	x = ConfigInteger(default=20, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_VOLTAGE_CHANGE_BEFORE_SWITCH_CMDS, configElement.value))
	config.sec.delay_after_change_voltage_before_switch_command = x

	x = ConfigInteger(default=1000, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_ENABLE_VOLTAGE_BEFORE_SWITCH_CMDS, configElement.value))
	config.sec.delay_after_enable_voltage_before_switch_command = x

	x = ConfigInteger(default=500, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_VOLTAGE_CHANGE_BEFORE_MEASURE_IDLE_INPUTPOWER, configElement.value))
	config.sec.delay_after_voltage_change_before_measure_idle_inputpower = x

	x = ConfigInteger(default=900, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_ENABLE_VOLTAGE_BEFORE_MOTOR_CMD, configElement.value))
	config.sec.delay_after_enable_voltage_before_motor_command = x

	x = ConfigInteger(default=500, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_MOTOR_STOP_CMD, configElement.value))
	config.sec.delay_after_motor_stop_command = x

	x = ConfigInteger(default=500, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_VOLTAGE_CHANGE_BEFORE_MOTOR_CMD, configElement.value))
	config.sec.delay_after_voltage_change_before_motor_command = x

	x = ConfigInteger(default=70, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_BEFORE_SEQUENCE_REPEAT, configElement.value))
	config.sec.delay_before_sequence_repeat = x

	x = ConfigInteger(default=360, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.MOTOR_RUNNING_TIMEOUT, configElement.value))
	config.sec.motor_running_timeout = x

	x = ConfigInteger(default=1, limits = (0, 5))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.MOTOR_COMMAND_RETRIES, configElement.value))
	config.sec.motor_command_retries = x

	x = ConfigInteger(default=50, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_DISEQC_RESET_CMD, configElement.value))
	config.sec.delay_after_diseqc_reset_cmd = x

	x = ConfigInteger(default=150, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_DISEQC_PERIPHERIAL_POWERON_CMD, configElement.value))
	config.sec.delay_after_diseqc_peripherial_poweron_cmd = x

	x = ConfigInteger(default=10, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_VOLTAGE_CHANGE_BEFORE_UNICABLE_CMD, configElement.value))
	config.sec.delay_after_voltage_change_before_unicable_cmd = x

	x = ConfigInteger(default=5, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_UNICABLE_CMD, configElement.value))
	config.sec.delay_after_unicable_cmd = x

	x = ConfigInteger(default=10, limits = (0, 9999))
	x.save_forced = False
	x.addNotifier(lambda configElement: secClass.setParam(secClass.DELAY_AFTER_UNICABLE_FINAL_VOLTAGE_CHANGE, configElement.value))
	config.sec.delay_after_unicable_final_voltage_change = x

# TODO add support for satpos depending nims to advanced nim configuration
# so a second/third/fourth cable from a motorized lnb can used behind a
# diseqc 1.0 / diseqc 1.1 / toneburst switch
# the C(++) part should can handle this
# the configElement should be only visible when diseqc 1.2 is disabled


def getMaxScr(format):
	return 32 if format == "EN50607" else 8

def getDefaultScr(format):
	if format == "EN50607":
		return (
			(984, (950, 2150)),
			(1020, (950, 2150)),
			(1056, (950, 2150)),
			(1092, (950, 2150)),
			(1128, (950, 2150)),
			(1164, (950, 2150)),
			(1210, (950, 2150)),
			(1256, (950, 2150)),
			(1292, (950, 2150)),
			(1328, (950, 2150)),
			(1364, (950, 2150)),
			(1420, (950, 2150)),
			(1458, (950, 2150)),
			(1494, (950, 2150)),
			(1530, (950, 2150)),
			(1566, (950, 2150)),
			(1602, (950, 2150)),
			(1638, (950, 2150)),
			(1680, (950, 2150)),
			(1716, (950, 2150)),
			(1752, (950, 2150)),
			(1788, (950, 2150)),
			(1824, (950, 2150)),
			(1860, (950, 2150)),
			(1896, (950, 2150)),
			(1932, (950, 2150)),
			(2004, (950, 2150)),
			(2040, (950, 2150)),
			(2076, (950, 2150)),
			(2112, (950, 2150)),
			(2148, (950, 2150)),
			(2096, (950, 2150)),
		)
	else:
		return (
			(1284, (950, 2150)),
			(1400, (950, 2150)),
			(1516, (950, 2150)),
			(1632, (950, 2150)),
			(1748, (950, 2150)),
			(1864, (950, 2150)),
			(1980, (950, 2150)),
			(2096, (950, 2150)),
		)

class UnicableProducts(object):
	def __init__(self):
		self._lnbs = {}
		self._matrices = {}
		self._lnbManufacturers = []
		self._matrixManufacturers = []

	def parseLnbs(self, xmlRoot):
		self._parseUnicableProducts(xmlRoot, self._lnbs)
		self._lnbManufacturers = list(self._lnbs.keys())
		self._lnbManufacturers.sort()

	def getLnbs(self):
		return self._lnbs
	lnbs = property(getLnbs)

	def getLnbManufacturers(self):
		return self._lnbManufacturers
	lnbManufacturers = property(getLnbManufacturers)

	def getManufacturerLnbs(self, manufacturer):
		return self._lnbs.get(manufacturer, [])

	def parseMatrices(self, xmlRoot):
		self._parseUnicableProducts(xmlRoot, self._matrices)
		self._matrixManufacturers = list(self._matrices.keys())
		self._matrixManufacturers.sort()

	def getMatrices(self):
		return self._matrices
	matrices = property(getMatrices)

	def getMatrixManufacturers(self):
		return self._matrixManufacturers
	matrixManufacturers = property(getMatrixManufacturers)

	def getManufacturerMatrices(self, manufacturer):
		return self._matrices.get(manufacturer, [])

	def createProductsConfig(self, products, vco_null_check, configElement=None, create_scrs=False):
		if products:
			productKeys = sorted(products.keys())

		if configElement is None:
			configElement = ConfigSubsection()
			configElement.product = ConfigText() if products is None else ConfigSelection(choices = productKeys, default = productKeys[0])
			configElement.mode = ConfigInteger(default=0)
			configElement.poweron_delay = ConfigInteger(default=0, limits=(0,5000))
			configElement.vco = ConfigSubList()
			configElement.positions = ConfigSubList()
			configElement.lofl = ConfigSubList()
			configElement.lofh = ConfigSubList()
			configElement.loft = ConfigSubList()

			if products is None:
				return configElement
		else:
			def resetConfigSubList(sublist):
				del sublist[:]
				sublist.stored_values = {}
				sublist.index = 0

			if isinstance(configElement.product, ConfigText) or configElement.product.value not in productKeys:
				configElement.product = ConfigSelection(choices = productKeys, default = productKeys[0])
			resetConfigSubList(configElement.vco)
			resetConfigSubList(configElement.positions)
			resetConfigSubList(configElement.lofl)
			resetConfigSubList(configElement.lofh)
			resetConfigSubList(configElement.loft)

		scrlist = []
		vcolist = products[configElement.product.value]
		lof_tuple = vcolist[len(vcolist)-1]

		configElement.mode.value = 1 if lof_tuple[4] == "EN50607" else 0
		configElement.poweron_delay.value = lof_tuple[5]

		for cnt in range(1,1+len(vcolist)-1):
			vcofreq = int(vcolist[cnt-1])
			if vcofreq == 0 and vco_null_check:
				scrlist.append(("%d" %cnt,"SCR %d " %cnt +_("not used")))
			else:
				scrlist.append(("%d" %cnt,"SCR %d" %cnt))
			configElement.vco.append(NoSave(ConfigInteger(default=vcofreq, limits = (vcofreq, vcofreq))))

		# we override cancel here because the original cancel does not set the old
		# value when value is not in choices.. in this case self.default is set
		# so we temporaray override self.default here for the scr config element
		def cancel(self):
			stored_default = self.default
			self.default = self.saved_value
			ConfigSelection.cancel(self)
			self.default = stored_default

		sv = configElement.scr.saved_value if hasattr(configElement, "scr") else None
		if not sv:
			sv = None
		save_forced = True if sv is None else configElement.scr.save_forced
		configElement.scr = ConfigSelection(scrlist, default = scrlist[0][0])
		configElement.scr.save_forced = save_forced
		configElement.scr.cancel = boundFunction(cancel, configElement.scr)
		if sv is not None:
			configElement.scr.value = sv
			configElement.scr.saved_value = sv

		if create_scrs:
			sv = configElement.scrs.saved_value if hasattr(configElement, "scrs") else None
			if not sv:
				sv = None
			save_forced = True if sv is None else configElement.scrs.save_forced
			scrs = None if sv is None else literal_eval(sv)
			choices = [ int(x) for x in vcolist[:-1] ]
			configElement.scrs = ConfigSet(default = [ int(vcolist[0]) ], choices = choices, resort = False)
			configElement.scrs.save_forced = save_forced
			if sv is not None:
				configElement.scrs.saved_value = sv
			if scrs is not None and set(scrs).issubset(set(choices)):
				configElement.scrs.value = scrs
			elif not set(configElement.scrs.value).issubset(set(choices)):
				configElement.scrs.value = configElement.scrs.default
		else:
			configElement.scrs = ConfigNothing()

		positions = int(lof_tuple[0])
		configElement.positions.append(ConfigInteger(default=positions, limits = (positions, positions)))

		lofl = int(lof_tuple[1])
		configElement.lofl.append(ConfigInteger(default=lofl, limits = (lofl, lofl)))

		lofh = int(lof_tuple[2])
		configElement.lofh.append(ConfigInteger(default=lofh, limits = (lofh, lofh)))

		loft = int(lof_tuple[3])
		configElement.loft.append(ConfigInteger(default=loft, limits = (loft, loft)))

		print("manufacturer", configElement.manufacturer.value, "product", configElement.product.value)

		return configElement

	def _parseUnicableProducts(self, xmlRoot, productDict):
		for manufacturer in xmlRoot.getchildren():
			m={}
			for product in manufacturer.getchildren():
				scr=[]
				lscr = []
				format = product.get("format", "EN50494").upper()
				poweron_delay = product.get("bootuptime",0)
				if format in ('JESS', 'UNICABLE2', 'SCD2', 'EN50607', 'EN 50607'):
					format = "EN50607"
				else:
					format = "EN50494"
				for i in range(1,getMaxScr(format) + 1):
					lscr.append("scr%s" %(i,))
				lscr = tuple(lscr)
				for i in range(len(lscr)):
					myscr = product.get(lscr[i],"0")
					if(myscr != "0"):
						scr.append(myscr)
				lof=[]
				lof.append(int(product.get("positions",1)))
				lof.append(int(product.get("lofl",9750)))
				lof.append(int(product.get("lofh",10600)))
				lof.append(int(product.get("threshold",11700)))
				lof.append(format)
				lof.append(poweron_delay)
				scr.append(tuple(lof))
				m.update({product.get("name"):tuple(scr)})
			productDict.update({manufacturer.get("name"):m})

unicableProducts = UnicableProducts()

def configLOFChanged(configElement):
	global nimmanager
	nimmgr = nimmanager
	if configElement.value == "unicable":
		x = configElement.slot_id
		lnb = configElement.lnb_id
		nim = config.Nims[x]
		lnbs = nim.advanced.lnb
		section = lnbs[lnb]
		create_scrs = nimmgr.nim_slots[x].inputs is not None

		if isinstance(section.unicable, ConfigNothing):
			unicable_choices = {
				"unicable_lnb": _("Unicable LNB"),
				"unicable_matrix": _("Unicable Matrix")}
			# FIXMEE user defined unicable is not usable with multi channel / multi input tuners (aka FBC tuners yet)
			if not create_scrs:
				unicable_choices["unicable_user"] = "Unicable "+_("User defined")
			unicable_choices_default = "unicable_lnb"
			section.unicable = ConfigSelection(unicable_choices, unicable_choices_default)
			section.unicable.slot_id = x
			section.unicable.lnb_id = lnb
			section.unicable_use_pin = ConfigYesNo(default = False)
			section.unicable_pin = ConfigInteger(default=0, limits=(0, 255))

		if section.unicable.value == "unicable_matrix":
			print("MATRIX")
			matrixConfig = section.unicableMatrix if hasattr(section, "unicableMatrix") else None
			manufacturer = unicableProducts.getMatrixManufacturers()[0]

			if matrixConfig:
				manufacturer = matrixConfig.manufacturer.value
			else:
				matrixConfig = unicableProducts.createProductsConfig(None, True, matrixConfig)
				section.unicableMatrix = matrixConfig
				matrixConfig.manufacturer = ConfigSelection(unicableProducts.getMatrixManufacturers(), default=manufacturer)
				manufacturer = matrixConfig.manufacturer.value

			unicableMatrix = unicableProducts.createProductsConfig(unicableProducts.getManufacturerMatrices(manufacturer), True, matrixConfig, create_scrs)

			if not matrixConfig:
				section.unicableMatrix = unicableMatrix
				if not hasattr(section.unicableMatrix, "manufacturer"):
					section.unicableMatrix.manufacturer = ConfigSelection(unicableProducts.getMatrixManufacturers(), default=manufacturer)

		elif section.unicable.value == "unicable_lnb":
			print("LNB")
			lnbConfig = section.unicableLnb if hasattr(section, "unicableLnb") else None
			manufacturer = unicableProducts.getLnbManufacturers()[0]

			if lnbConfig:
				manufacturer = lnbConfig.manufacturer.value
			else:
				lnbConfig = unicableProducts.createProductsConfig(None, True, lnbConfig)
				section.unicableLnb = lnbConfig
				lnbConfig.manufacturer = ConfigSelection(unicableProducts.getLnbManufacturers(), default=manufacturer)
				manufacturer = lnbConfig.manufacturer.value

			unicableLnb = unicableProducts.createProductsConfig(unicableProducts.getManufacturerLnbs(manufacturer), False, lnbConfig, create_scrs)

			if not lnbConfig:
				section.unicableLnb = unicableLnb
				if not hasattr(section.unicableLnb, "manufacturer"):
					section.unicableLnb.manufacturer = ConfigSelection(unicableProducts.getLnbManufacturers(), default=manufacturer)

		elif section.unicable.value == "unicable_user":
			print("USER")
			advanced_lnb_satcruser_choices = []
			for i in range(1, getMaxScr("EN50607") + 1):
				advanced_lnb_satcruser_choices.append((str(i), "SatCR %s" %(i,)))

			if not hasattr(section, "satcruser"):
				mode_choices = [ ("EN50494", _("Unicable 1")), ("EN50607", _("Unicable 2 / JESS")) ]
				section.satcruser_mode = ConfigSelection(mode_choices, default="EN50494")
				section.satcruser = ConfigSelection(advanced_lnb_satcruser_choices, default="1")
				tmp = ConfigSubList()
				for entry in getDefaultScr("EN50607"):
					tmp.append(ConfigInteger(default=entry[0], limits=entry[1])) #TODO properly pass format
				section.satcrvcouser = tmp

		if not hasattr(nim.advanced, "unicableconnected"):
			nim.advanced.unicableconnected = ConfigYesNo(default=False)
			nim.advanced.unicableconnectedTo = ConfigSelection([(str(id), nimmgr.getNimDescription(id)) for id in nimmgr.getNimListOfType("DVB-S") if id != x])

		if not hasattr(nim.advanced, "unicabledepends"):
			nim.advanced.unicabledepends = ConfigYesNo(default=False)
			nim.advanced.unicabledependsOn = ConfigSelection([(str(id), nimmgr.getNimDescription(id)) for id in nimmgr.getNimListOfType("DVB-S") if id != x])

def InitNimManager(nimmgr, slot_no = None):
	global unicableProducts
	hw = HardwareInfo()
	addNimConfig = False
	try:
		config.Nims
		assert slot_no is not None, "FATAL: you must call InitNimManager(nimmgr, slot_no = X) to reinitialize SINGLE nim slots"
	except:
		addNimConfig = True

	if addNimConfig:
		InitSecParams()
		config.Nims = ConfigSubList()
		for x in range(len(nimmgr.nim_slots)):
			config.Nims.append(ConfigSubsection())

	lnb_choices = {
		"universal_lnb": _("Universal LNB"),
		"unicable": _("Unicable"),
		"c_band": _("C-Band"),
		"user_defined": _("User defined")}

	lnb_choices_default = "universal_lnb"

	try:
		doc = xml.etree.cElementTree.parse(eEnv.resolve("${sysconfdir}/enigma2/unicable.xml"))
	except IOError:
		doc = xml.etree.cElementTree.parse(eEnv.resolve("${datadir}/enigma2/unicable.xml"))
	root = doc.getroot()

	entry = root.find("lnb")
	unicableProducts.parseLnbs(entry)
	entry = root.find("matrix")
	unicableProducts.parseMatrices(entry)

	prio_list = [ ("-1", _("Auto")) ]
	prio_list += [(str(prio), str(prio)) for prio in list(range(65))+list(range(14000,14065))+list(range(19000,19065))]

	advanced_lnb_csw_choices = [("none", _("None")), ("AA", _("AA")), ("AB", _("AB")), ("BA", _("BA")), ("BB", _("BB"))]
	advanced_lnb_csw_choices += [(str(0xF0|y), "Input " + str(y+1)) for y in range(0, 16)]

	advanced_lnb_ucsw_choices = [("0", _("None"))] + [(str(y), "Input " + str(y)) for y in range(1, 17)]

	diseqc_mode_choices = [
		("single", _("Single")), ("toneburst_a_b", _("Toneburst A/B")),
		("diseqc_a_b", _("DiSEqC A/B")), ("diseqc_a_b_c_d", _("DiSEqC A/B/C/D")),
		("positioner", _("Positioner"))]

	positioner_mode_choices = [("usals", _("USALS")), ("manual", _("manual"))]

	diseqc_satlist_choices = [(3601, _('nothing connected'), 1)] + nimmgr.satList

	longitude_orientation_choices = [("east", _("East")), ("west", _("West"))]
	latitude_orientation_choices = [("north", _("North")), ("south", _("South"))]
	turning_speed_choices = [("fast", _("Fast")), ("slow", _("Slow")), ("fast epoch", _("Fast epoch"))]

	advanced_satlist_choices = nimmgr.satList + [
		(3601, _('All Satellites')+' 1', 1), (3602, _('All Satellites')+' 2', 1),
		(3603, _('All Satellites')+' 3', 1), (3604, _('All Satellites')+' 4', 1)]
	advanced_lnb_choices = [("0", "not available")] + [(str(y), "LNB " + str(y)) for y in range(1, 33)]
	advanced_voltage_choices = [("polarization", _("Polarization")), ("13V", _("13 V")), ("18V", _("18 V"))]
	advanced_tonemode_choices = [("band", _("Band")), ("on", _("On")), ("off", _("Off"))]
	advanced_lnb_toneburst_choices = [("none", _("None")), ("A", _("A")), ("B", _("B"))]
	advanced_lnb_allsat_diseqcmode_choices = [("1_2", _("1.2"))]
	advanced_lnb_diseqcmode_choices = [("none", _("None")), ("1_0", _("1.0")), ("1_1", _("1.1")), ("1_2", _("1.2"))]
	advanced_lnb_commandOrder1_0_choices = [("ct", "committed, toneburst"), ("tc", "toneburst, committed")]
	advanced_lnb_commandOrder_choices = [
		("ct", "committed, toneburst"), ("tc", "toneburst, committed"),
		("cut", "committed, uncommitted, toneburst"), ("tcu", "toneburst, committed, uncommitted"),
		("uct", "uncommitted, committed, toneburst"), ("tuc", "toneburst, uncommitted, commmitted")]
	advanced_lnb_diseqc_repeat_choices = [("none", _("None")), ("one", _("One")), ("two", _("Two")), ("three", _("Three"))]
	advanced_lnb_fast_turning_btime = mktime(datetime(1970, 1, 1, 7, 0).timetuple());
	advanced_lnb_fast_turning_etime = mktime(datetime(1970, 1, 1, 19, 0).timetuple());

	def configDiSEqCModeChanged(configElement):
		section = configElement.section
		if configElement.value == "1_2" and isinstance(section.longitude, ConfigNothing):
			section.longitude = ConfigFloat(default = [5,100], limits = [(0,359),(0,999)])
			section.longitudeOrientation = ConfigSelection(longitude_orientation_choices, "east")
			section.latitude = ConfigFloat(default = [50,767], limits = [(0,359),(0,999)])
			section.latitudeOrientation = ConfigSelection(latitude_orientation_choices, "north")
			section.powerMeasurement = ConfigYesNo(default=True)
			section.powerThreshold = ConfigInteger(default=15, limits=(0, 100))
			section.turningSpeed = ConfigSelection(turning_speed_choices, "fast")
			section.degreePerSecond = ConfigFloat(default = [0,5], limits=[(0,360),(0,9)])
			section.fastTurningBegin = ConfigDateTime(default=advanced_lnb_fast_turning_btime, formatstring = _("%H:%M"), increment = 600)
			section.fastTurningEnd = ConfigDateTime(default=advanced_lnb_fast_turning_etime, formatstring = _("%H:%M"), increment = 600)

	def configLNBChanged(configElement):
		x = configElement.slot_id
		nim = config.Nims[x]
		if isinstance(configElement.value, tuple):
			lnb = int(configElement.value[0])
		else:
			lnb = int(configElement.value)
		lnbs = nim.advanced.lnb
		if lnb and lnb not in lnbs:
			section = lnbs[lnb] = ConfigSubsection()
			section.lofl = ConfigInteger(default=9750, limits = (0, 99999))
			section.lofh = ConfigInteger(default=10600, limits = (0, 99999))
			section.threshold = ConfigInteger(default=11700, limits = (0, 99999))
#			section.output_12v = ConfigSelection(choices = [("0V", _("0 V")), ("12V", _("12 V"))], default="0V")
			section.increased_voltage = ConfigYesNo(False)
			section.toneburst = ConfigSelection(advanced_lnb_toneburst_choices, "none")
			section.longitude = ConfigNothing()
			if lnb > 32:
				tmp = ConfigSelection(advanced_lnb_allsat_diseqcmode_choices, "1_2")
				tmp.section = section
				configDiSEqCModeChanged(tmp)
			else:
				tmp = ConfigSelection(advanced_lnb_diseqcmode_choices, "none")
				tmp.section = section
				tmp.addNotifier(configDiSEqCModeChanged)
			section.diseqcMode = tmp
			section.commitedDiseqcCommand = ConfigSelection(advanced_lnb_csw_choices)
			section.fastDiseqc = ConfigYesNo(False)
			section.sequenceRepeat = ConfigYesNo(False)
			section.commandOrder1_0 = ConfigSelection(advanced_lnb_commandOrder1_0_choices, "ct")
			section.commandOrder = ConfigSelection(advanced_lnb_commandOrder_choices, "ct")
			section.uncommittedDiseqcCommand = ConfigSelection(advanced_lnb_ucsw_choices)
			section.diseqcRepeats = ConfigSelection(advanced_lnb_diseqc_repeat_choices, "none")
			section.prio = ConfigSelection(prio_list, "-1")
			section.unicable = ConfigNothing()
			tmp = ConfigSelection(lnb_choices, lnb_choices_default)
			tmp.slot_id = x
			tmp.lnb_id = lnb
			tmp.addNotifier(configLOFChanged, initial_call = False)
			section.lof = tmp

	def configModeChanged(configMode):
		slot_id = configMode.slot_id
		nim = config.Nims[slot_id]
		if configMode.value == "advanced" and isinstance(nim.advanced, ConfigNothing):
			# advanced config:
			nim.advanced = ConfigSubsection()
			nim.advanced.sat = ConfigSubDict()
			nim.advanced.sats = getConfigSatlist(192, advanced_satlist_choices)
			nim.advanced.lnb = ConfigSubDict()
			nim.advanced.lnb[0] = ConfigNothing()
			for x in nimmgr.satList:
				tmp = ConfigSubsection()
				tmp.voltage = ConfigSelection(advanced_voltage_choices, "polarization")
				tmp.tonemode = ConfigSelection(advanced_tonemode_choices, "band")
				tmp.usals = ConfigYesNo(True)
				tmp.rotorposition = ConfigInteger(default=1, limits=(1, 255))
				lnb = ConfigSelection(advanced_lnb_choices, "0")
				lnb.slot_id = slot_id
				lnb.addNotifier(configLNBChanged, initial_call = False)
				lnb.save_forced = False
				tmp.lnb = lnb
				nim.advanced.sat[x[0]] = tmp
			for x in range(3601, 3605):
				tmp = ConfigSubsection()
				tmp.voltage = ConfigSelection(advanced_voltage_choices, "polarization")
				tmp.tonemode = ConfigSelection(advanced_tonemode_choices, "band")
				tmp.usals = ConfigYesNo(default=True)
				tmp.rotorposition = ConfigInteger(default=1, limits=(1, 255))
				lnbnum = 33+x-3601
				lnb = ConfigSelection([("0", "not available"), (str(lnbnum), "LNB %d"%(lnbnum))], "0")
				lnb.slot_id = slot_id
				lnb.addNotifier(configLNBChanged, initial_call = False)
				lnb.save_forced = False
				tmp.lnb = lnb
				nim.advanced.sat[x] = tmp

	def scpcSearchRangeChanged(configElement):
		fe_id = configElement.fe_id
		with open("/proc/stb/frontend/%d/use_scpc_optimized_search_range" %(fe_id), "w") as f:
			f.write(configElement.value)

	def toneAmplitudeChanged(configElement):
		fe_id = configElement.fe_id
		slot_id = configElement.slot_id
		if nimmgr.nim_slots[slot_id].description == 'Alps BSBE2':
			with open("/proc/stb/frontend/%d/tone_amplitude" %(fe_id), "w") as f:
				f.write(configElement.value)

	def connectedToChanged(slot_id, nimmgr, configElement):
		configMode = nimmgr.getNimConfig(slot_id).sat.configMode
		if configMode.value == 'loopthrough':
			internally_connectable = nimmgr.nimInternallyConnectableTo(slot_id)
			dest_slot = configElement.value
			if internally_connectable is not None and int(internally_connectable) == int(dest_slot):
				configMode.choices.updateItemDescription(configMode.index, _("internally loopthrough to"))
			else:
				configMode.choices.updateItemDescription(configMode.index, _("externally loopthrough to"))

	for slot in nimmgr.nim_slots:
		x = slot.slot

		# only re-init specific nim slot when InitNimManager is called again
		if slot_no is not None and x != slot_no:
			continue

		nim = config.Nims[x]
		addMultiType = False
		try:
			nim.multiType
		except:
			addMultiType = True
		if addMultiType:
			typeList = []
			for key, value in six.iteritems(slot.types):
				typeList.append((key, value))
			nim.multiType = ConfigSelection(typeList, "0")
			nim.multiType.enabled = len(typeList) > 1
			nim.multiType.slot_id = x

	getConfigModeTuple=nimmgr.getConfigModeTuple

	empty_slots = 0
	for slot in nimmgr.nim_slots:
		x = slot.slot

		# only re-init specific nim slot when InitNimManager is called again
		if slot_no is not None and x != slot_no:
			continue

		nim = config.Nims[x]
		isEmpty = True

		nim.configMode = ConfigSelection(choices={
			"nothing" : NimManager.config_mode_str["nothing"],
			"multi" : NimManager.config_mode_str["multi"],
			"enabled" : NimManager.config_mode_str["enabled"],
			"simple" : NimManager.config_mode_str["simple"],
			"advanced" : NimManager.config_mode_str["advanced"],
			"equal" : NimManager.config_mode_str["equal"],
			"satposdepends" : NimManager.config_mode_str["satposdepends"],
			"loopthrough" : "", # description is dynamically generated by connectedToChanged function (InitNimManager)
		}, default = "multi")

		if slot.isCompatible("DVB-S"):
			isEmpty = False
			nim.toneAmplitude = ConfigSelection([("11", "340mV"), ("10", "360mV"), ("9", "600mV"), ("8", "700mV"), ("7", "800mV"), ("6", "900mV"), ("5", "1100mV")], "7")
			nim.toneAmplitude.fe_id = x - empty_slots
			nim.toneAmplitude.slot_id = x
			nim.toneAmplitude.addNotifier(toneAmplitudeChanged)
			nim.scpcSearchRange = ConfigSelection([("0", _("no")), ("1", _("yes"))], "0")
			nim.scpcSearchRange.slot_id = x
			fe_id =  x - empty_slots
			if exists('/proc/stb/frontend/%d/use_scpc_optimized_search_range' % fe_id):
				nim.scpcSearchRange.fe_id = fe_id
				nim.scpcSearchRange.addNotifier(scpcSearchRangeChanged)
			else:
				nim.scpcSearchRange.fe_id = None
			nim.diseqc13V = ConfigYesNo(False)
			nim.diseqcMode = ConfigSelection(diseqc_mode_choices, "diseqc_a_b")
			nim.connectedTo = ConfigSelection([(str(id), nimmgr.getNimDescription(id)) for id in nimmgr.getNimListOfType("DVB-S") if id != x])
			nim.simpleSingleSendDiSEqC = ConfigYesNo(False)
			nim.simpleDiSEqCSetVoltageTone = ConfigYesNo(True)
			nim.simpleDiSEqCOnlyOnSatChange = ConfigYesNo(False)
			nim.diseqcA = getConfigSatlist(192, diseqc_satlist_choices)
			nim.diseqcB = getConfigSatlist(130, diseqc_satlist_choices)
			nim.diseqcC = ConfigSatlist(list = diseqc_satlist_choices)
			nim.diseqcD = ConfigSatlist(list = diseqc_satlist_choices)
			nim.positionerMode = ConfigSelection(positioner_mode_choices, "usals")
			nim.longitude = ConfigFloat(default=[5,100], limits=[(0,359),(0,999)])
			nim.longitudeOrientation = ConfigSelection(longitude_orientation_choices, "east")
			nim.latitude = ConfigFloat(default=[50,767], limits=[(0,359),(0,999)])
			nim.latitudeOrientation = ConfigSelection(latitude_orientation_choices, "north")
			nim.positionerExclusively = ConfigYesNo(True)
			nim.powerMeasurement = ConfigYesNo(True)
			nim.powerThreshold = ConfigInteger(default=hw.get_device_name() == "dm8000" and 15 or 50, limits=(0, 100))
			nim.turningSpeed = ConfigSelection(turning_speed_choices, "fast")
			nim.degreePerSecond = ConfigFloat(default = [0,5], limits=[(0,360),(0,9)])
			btime = datetime(1970, 1, 1, 7, 0);
			nim.fastTurningBegin = ConfigDateTime(default = mktime(btime.timetuple()), formatstring = _("%H:%M"), increment = 900)
			etime = datetime(1970, 1, 1, 19, 0);
			nim.fastTurningEnd = ConfigDateTime(default = mktime(etime.timetuple()), formatstring = _("%H:%M"), increment = 900)
			config_mode_choices = [ getConfigModeTuple("nothing"), getConfigModeTuple("simple"), getConfigModeTuple("advanced") ]
			# FIXMEE
			# no support for satpos depends, equal to and loopthough setting for nims with
			# with multiple inputs and multiple channels
			if slot.inputs is None:
				for val in six.itervalues(slot.types):
					if len(nimmgr.getNimListOfType(val, exception = x)) > 0:
						config_mode_choices.append(getConfigModeTuple("equal"))
						config_mode_choices.append(getConfigModeTuple("satposdepends"))
						config_mode_choices.append(getConfigModeTuple("loopthrough"))
			nim.advanced = ConfigNothing()
			nim.sat = ConfigSubsection()
			nim.sat.configMode = ConfigSelection(config_mode_choices, "nothing")
			nim.sat.configMode.slot_id = x
			nim.sat.configMode.connectedToChanged = boundFunction(connectedToChanged, x, nimmgr)
			#Migrate old settings if existing
			if nim.configMode.value != "multi":
				if not slot.isMultiType() or slot.types[nim.multiType.value].startswith("DVB-S"):
					Log.w("Migrating old DVB-S settings!")
					nim.sat.configMode.value = nim.configMode.value
			nim.sat.configMode.addNotifier(configModeChanged, initial_call = True)
			nim.connectedTo.addNotifier(boundFunction(connectedToChanged, x, nimmgr), initial_call = True)
		if slot.isCompatible("DVB-C"):
			isEmpty = False
			nim.cable = ConfigSubsection()
			nim.cable.configMode = ConfigSelection(
				choices = [ getConfigModeTuple("enabled"), getConfigModeTuple("nothing") ],
				default = "enabled" if not slot.isMultiType() or slot.types[nim.multiType.value] == "DVB-C" else "nothing")
			result = [ ]
			n = 0
			for x in nimmgr.cablesList:
				result.append((str(n), x[0]))
				n += 1
			possible_scan_types = [("bands", _("Frequency bands")), ("steps", _("Frequency steps"))]
			if n:
				possible_scan_types.append(("provider", _("Provider")))
				nim.cable.scan_provider = ConfigSelection(default = "0", choices = result)
			nim.cable.scan_type = ConfigSelection(default = "bands", choices = possible_scan_types)
			nim.cable.scan_band_EU_VHF_I = ConfigYesNo(default = True)
			nim.cable.scan_band_EU_MID = ConfigYesNo(default = True)
			nim.cable.scan_band_EU_VHF_III = ConfigYesNo(default = True)
			nim.cable.scan_band_EU_UHF_IV = ConfigYesNo(default = True)
			nim.cable.scan_band_EU_UHF_V = ConfigYesNo(default = True)
			nim.cable.scan_band_EU_SUPER = ConfigYesNo(default = True)
			nim.cable.scan_band_EU_HYPER = ConfigYesNo(default = True)
			nim.cable.scan_band_US_LOW = ConfigYesNo(default = False)
			nim.cable.scan_band_US_MID = ConfigYesNo(default = False)
			nim.cable.scan_band_US_HIGH = ConfigYesNo(default = False)
			nim.cable.scan_band_US_SUPER = ConfigYesNo(default = False)
			nim.cable.scan_band_US_HYPER = ConfigYesNo(default = False)
			nim.cable.scan_band_US_ULTRA = ConfigYesNo(default = False)
			nim.cable.scan_band_US_JUMBO = ConfigYesNo(default = False)
			nim.cable.scan_frequency_steps = ConfigInteger(default = 1000, limits = (1000, 10000))
			nim.cable.scan_mod_qam16 = ConfigYesNo(default = False)
			nim.cable.scan_mod_qam32 = ConfigYesNo(default = False)
			nim.cable.scan_mod_qam64 = ConfigYesNo(default = True)
			nim.cable.scan_mod_qam128 = ConfigYesNo(default = False)
			nim.cable.scan_mod_qam256 = ConfigYesNo(default = True)
			nim.cable.scan_sr_6900 = ConfigYesNo(default = True)
			nim.cable.scan_sr_6875 = ConfigYesNo(default = True)
			nim.cable.scan_sr_ext1 = ConfigInteger(default = 0, limits = (0, 7230))
			nim.cable.scan_sr_ext2 = ConfigInteger(default = 0, limits = (0, 7230))
			#Migrate old settings if existing
			if nim.configMode.value != "multi":
				if not slot.isMultiType() or slot.types[nim.multiType.value] == "DVB-C":
					Log.w("Migrating old DVB-C settings!")
					nim.cable.configMode.value = nim.configMode.value
		if slot.isCompatible("DVB-T"):
			isEmpty = False
			nim.terrest = ConfigSubsection()
			nim.terrest.configMode = ConfigSelection(
				choices = [ getConfigModeTuple("enabled"), getConfigModeTuple("nothing") ],
				default = "enabled" if not slot.isMultiType() or slot.types[nim.multiType.value].startswith("DVB-T") else "nothing")
			provider = []
			n = 0
			for x in nimmgr.terrestrialsList:
				provider.append((str(n), x[0]))
				n += 1
			nim.terrest.provider = ConfigSelection(choices = provider)
			nim.terrest.use5V = ConfigOnOff()
			#Migrate old settings
			if nim.configMode.value != "multi":
				nim.terrestrial = NoSave(ConfigSelection(choices = provider, default="1"))
				nim.terrestrial_5V = NoSave(ConfigOnOff(default=False))
				if not slot.isMultiType() or slot.types[nim.multiType.value].startswith("DVB-T"):
					Log.w("Migrating old DVB-T settings!")
					nim.terrest.configMode.value = nim.configMode.value
				nim.terrest.provider.value = nim.terrestrial.value
				nim.terrest.use5V.value = nim.terrestrial_5V.value

		if isEmpty:
			empty_slots += 1
			nim.configMode = ConfigSelection(choices = { "nothing": _("disabled") }, default="nothing");
		elif not slot.types:
			print("pls add support for this frontend type!", slot.type)
		elif nim.configMode.value != "multi":
			nim.configMode.value = "multi"
			nim.save()
			config.save()

	nimmgr.sec = SecConfigure(nimmgr)

nimmanager = NimManager()
InitNimManager(nimmanager)
