from enigma import eServiceReference, eServiceCenter

class ServiceReference(eServiceReference):
	def __init__(self, ref):
		if not isinstance(ref, eServiceReference):
			self.ref = eServiceReference(ref or "")
		else:
			self.ref = ref
		self.serviceHandler = eServiceCenter.getInstance()

	def __str__(self):
		return self.ref.toString()

	def getServiceName(self):
		info = self.info()
		return info and info.getName(self.ref) or ""

	def info(self):
		return self.serviceHandler.info(self.ref)

	def list(self):
		return self.serviceHandler.list(self.ref)

	def getType(self):
		return self.ref.type

	def getPath(self):
		return self.ref.getPath()

	def getFlags(self):
		return self.ref.flags

	def isRecordable(self):
		ref = self.ref
		path = ref.getPath()
		return ref.flags & eServiceReference.isGroup or (ref.type in [eServiceReference.idURI, eServiceReference.idDVB, eServiceReference.idGST] and (path == '' or path[0] != '/'))
