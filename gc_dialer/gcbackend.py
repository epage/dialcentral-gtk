#!/usr/bin/python

"""
Grandcentral Dialer backend code
Eric Warnke <ericew@gmail.com>
Copyright 2008 GPLv2
"""


import os
import re
import urllib
import time

from browser_emu import MozillaEmulator


class GCDialer(object):
	"""
	This class encapsulates all of the knowledge necessary to interace with the grandcentral servers
	the functions include login, setting up a callback number, and initalting a callback
	"""

	_gcDialingStrRe	= re.compile("This may take a few seconds", re.M)	# string from Grandcentral.com on successful dial
	_validateRe	= re.compile("^[0-9]{10,}$")
	_accessTokenRe	= re.compile(r"""<input type="hidden" name="a_t" [^>]*value="(.*)"/>""")
	_isLoginPageRe	= re.compile(r"""<form method="post" action="https://www.grandcentral.com/mobile/account/login">""")
	_callbackRe	= re.compile(r"""name="default_number" value="(\d+)" />\s+(.*)\s$""", re.M)
	_accountNumRe	= re.compile(r"""<img src="/images/mobile/inbox_logo.gif" alt="GrandCentral" />\s*(.{14})\s*&nbsp""", re.M)
	_inboxRe	= re.compile(r"""<td>.*?(voicemail|received|missed|call return).*?</td>\s+<td>\s+<font size="2">\s+(.*?)\s+&nbsp;\|&nbsp;\s+<a href="/mobile/contacts/.*?">(.*?)\s?</a>\s+<br/>\s+(.*?)\s?<a href=""", re.S)

	_forwardselectURL	= "http://www.grandcentral.com/mobile/settings/forwarding_select"
	_loginURL		= "https://www.grandcentral.com/mobile/account/login"
	_setforwardURL		= "http://www.grandcentral.com/mobile/settings/set_forwarding?from=settings"
	_clicktocallURL		= "http://www.grandcentral.com/mobile/calls/click_to_call?a_t=%s&destno=%s"
	_inboxallURL		= "http://www.grandcentral.com/mobile/messages/inbox?types=all"

	def __init__(self, cookieFile = None):
		# Important items in this function are the setup of the browser emulation and cookie file
		self._msg = ""

		self._browser = MozillaEmulator(None, 0)
		if cookieFile is None:
			cookieFile = os.path.join(os.path.expanduser("~"), ".gc_dialer_cookies.txt")
		self._browser.cookies.filename = cookieFile
		if os.path.isfile(cookieFile):
			self._browser.cookies.load()

		self._accessToken = None
		self._accountNum = None
		self._callbackNumbers = {}
		self._lastAuthed = 0.0

	def isAuthed(self, force = False):
		"""
		Attempts to detect a current session and pull the auth token ( a_t ) from the page.
		@note Once logged in try not to reauth more than once a minute.
		@returns If authenticated
		"""

		if time.time() - self._lastAuthed < 60 and not force:
			return True

		try:	
			forwardSelectionPage = self._browser.download(GCDialer._forwardselectURL)
			self._browser.cookies.save()
			if GCDialer._isLoginPageRe.search(forwardSelectionPage) is None:
				self._grabToken(forwardSelectionPage)
				self._lastAuthed = time.time()
				return True
		except:
			pass
		return False

	def login(self, username, password):
		"""
		Attempt to login to grandcentral
		@returns Whether login was successful or not
		"""
		try:
			if self.isAuthed():
				return True
			loginPostData = urllib.urlencode( {'username' : username , 'password' : password } )
			loginSuccessOrFailurePage = self._browser.download(GCDialer._loginURL, loginPostData)
			return self.isAuthed()
		except:
			pass
		return False

	def dial(self, number):
		"""
		This is the main function responsible for initating the callback
		"""
		self._msg = ""

		# If the number is not valid throw exception
		if self.validate(number) is False:
			raise ValueError('number is not valid')

		# No point if we don't have the magic cookie
		if not self.isAuthed():
			self._msg = "Not authenticated"
			return False

		# Strip leading 1 from 11 digit dialing
		if len(number) == 11 and number[0] == 1:
			number = number[1:]

		try:
			callSuccessPage = self._browser.download(
				GCDialer._clicktocallURL % (self._accessToken, number),
				None, {'Referer' : 'http://www.grandcentral.com/mobile/messages'} )

			if GCDialer._gcDialingStrRe.search(callSuccessPage) is not None:
				return True
			else:
				self._msg = "Grand Central returned an error"
				return False
		except:
			pass
	
		self._msg = "Unknown Error"
		return False

	def clear_caches(self):
		"""
		@todo Fill this in
		"""
		pass

	def reset(self):
		self._lastAuthed = 0.0
		self._browser.cookies.clear()
		self._browser.cookies.save()

	def getAccountNumber(self):
		"""
		@returns The grand central phone number
		"""
		return self._accountNum

	def validate(self, number):
		"""
		@returns If This number be called ( syntax validation only )
		"""
		return GCDialer._validateRe.match(number) is not None

	def setSaneCallback(self):
		"""
		Try to set a sane default callback number on these preferences
		1) 1747 numbers ( Gizmo )
		2) anything with gizmo in the name
		3) anything with computer in the name
		4) the first value
		"""
		print "setSaneCallback"
		numbers = self.getCallbackNumbers()

		for number, description in numbers.iteritems():
			if not re.compile(r"""1747""").match(number) is None:
				self.setCallbackNumber(number)
				return

		for number, description in numbers.iteritems():
			if not re.compile(r"""gizmo""", re.I).search(description) is None:
				self.setCallbackNumber(number)
				return

		for number, description in numbers.iteritems():
			if not re.compile(r"""computer""", re.I).search(description) is None:
				self.setCallbackNumber(number)
				return

		for number, description in numbers.iteritems():
			self.setCallbackNumber(number)
			return

	def getCallbackNumbers(self):
		"""
		@returns a dictionary mapping call back numbers to descriptions
		@note These results are cached for 30 minutes.
		"""
		print "getCallbackNumbers"
		if time.time() - self._lastAuthed < 1800 or self.isAuthed():
			return self._callbackNumbers

		return {}

	def setCallbackNumber(self, callbacknumber):
		"""
		Set the number that grandcental calls
		@param callbacknumber should be a proper 10 digit number
		"""
		print "setCallbackNumber %s" % (callbacknumber)
		try:
			callbackPostData = urllib.urlencode({'a_t' : self._accessToken, 'default_number' : callbacknumber })
			callbackSetPage = self._browser.download(GCDialer._setforwardURL, callbackPostData)
			self._browser.cookies.save()
		except:
			pass

	def getCallbackNumber(self):
		"""
		@returns Current callback number or None
		"""
		for c in self._browser.cookies:
			if c.name == "pda_forwarding_number":
				return c.value
		return None

	def get_recent(self):
		"""
		@returns Iterable of (Phone Number, Description)
		"""
		try:
			recentCallsPage = self._browser.download(GCDialer._inboxallURL)
			for match in self._inboxRe.finditer(recentCallsPage):
				yield (match.group(4), "%s on %s from/to %s - %s" % (match.group(1).capitalize(), match.group(2), match.group(3), match.group(4)))
		except:
			pass

	def _grabToken(self, data):
		"Pull the magic cookie from the datastream"
		atGroup = GCDialer._accessTokenRe.search(data)
		try:
			self._accessToken = atGroup.group(1)
		except:
			pass

		anGroup = GCDialer._accountNumRe.search(data)
		try:
			self._accountNum = anGroup.group(1)
		except:
			pass

		self._callbackNumbers = {}
		try:
			for match in GCDialer._callbackRe.finditer(data):
				self._callbackNumbers[match.group(1)] = match.group(2)
		except:
			pass
