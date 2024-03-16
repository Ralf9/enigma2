# the implementation here is a bit crappy.
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from enigma import eLCD
from Tools.Directories import fileExists, resolveFilename, SCOPE_CONFIG, SCOPE_DEFAULTDIR
from Tools.Log import Log

import time

PERCENTAGE_START = 0
PERCENTAGE_END = 100

profile_start = time.time()

profile_data = {}
total_time = 1
profile_file = None

try:

	pfile = resolveFilename(SCOPE_CONFIG, "profile")
	if not fileExists(pfile):
		pfile = resolveFilename(SCOPE_DEFAULTDIR, "Dream/profile")
	profile_old = open(pfile, "r").readlines()

	t = None
	for line in profile_old:
		(t, id) = line[:-1].split('\t')
		t = float(t)
		total_time = t
		profile_data[id] = t
except:
	print("no profile data available")

try:
	profile_file = open(resolveFilename(SCOPE_CONFIG, "profile"), "w")
except IOError:
	print("WARNING: couldn't open profile file!")

def profile(id):
	now = time.time() - profile_start
	if profile_file:
		profile_file.write("%.2f\t%s\n" % (now, id))

		if id in profile_data and total_time:
			t = profile_data[id]
			perc = t * (PERCENTAGE_END - PERCENTAGE_START) // total_time + PERCENTAGE_START
			print("profile: %s: %d" % (id, perc))
			try:
				eLCD.getInstance().setBootProgress(int(perc))
			except IOError:
				pass

def profile_final():
	global profile_file
	if profile_file is not None:
		profile_file.close()
		profile_file = None
