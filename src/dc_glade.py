#!/usr/bin/python2.5

# DialCentral - Front end for Google's Grand Central service.
# Copyright (C) 2008  Mark Bergman bergman AT merctech DOT com
# 
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
# 
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA


"""
DialCentral: A phone dialer using GrandCentral
"""

import sys
import gc
import os
import threading
import warnings
import traceback

import gtk
import gtk.glade

try:
	import hildon
except ImportError:
	hildon = None

import gtk_toolbox


class Dialcentral(object):

	__pretty_app_name__ = "DialCentral"
	__app_name__ = "dialcentral"
	__version__ = "0.9.1"
	__app_magic__ = 0xdeadbeef

	_glade_files = [
		'/usr/lib/dialcentral/dialcentral.glade',
		os.path.join(os.path.dirname(__file__), "dialcentral.glade"),
		os.path.join(os.path.dirname(__file__), "../lib/dialcentral.glade"),
	]

	_data_path = os.path.join(os.path.expanduser("~"), ".dialcentral")

	def __init__(self):
		self._connection = None
		self._osso = None
		self._phoneBackends = []
		self._phoneBackend = None
		self._clipboard = gtk.clipboard_get()

		self._deviceIsOnline = True
		self._isLoggedIn = False
		self._dialpads = None
		self._accountViews = None
		self._recentViews = None
		self._contactsViews = None

		for path in Dialcentral._glade_files:
			if os.path.isfile(path):
				self._widgetTree = gtk.glade.XML(path)
				break
		else:
			self.display_error_message("Cannot find dialcentral.glade")
			gtk.main_quit()
			return

		self._window = self._widgetTree.get_widget("mainWindow")
		self._notebook = self._widgetTree.get_widget("notebook")
		self._errorDisplay = gtk_toolbox.ErrorDisplay(self._widgetTree)
		self._credentials = gtk_toolbox.LoginWindow(self._widgetTree)

		self._app = None
		self._isFullScreen = False
		if hildon is not None:
			self._app = hildon.Program()
			self._window = hildon.Window()
			self._widgetTree.get_widget("vbox1").reparent(self._window)
			self._app.add_window(self._window)
			self._widgetTree.get_widget("usernameentry").set_property('hildon-input-mode', 7)
			self._widgetTree.get_widget("passwordentry").set_property('hildon-input-mode', 7|(1 << 29))
			self._widgetTree.get_widget("callbackcombo").get_child().set_property('hildon-input-mode', (1 << 4))
			hildon.hildon_helper_set_thumb_scrollbar(self._widgetTree.get_widget('recent_scrolledwindow'), True)
			hildon.hildon_helper_set_thumb_scrollbar(self._widgetTree.get_widget('contacts_scrolledwindow'), True)

			gtkMenu = self._widgetTree.get_widget("dialpad_menubar")
			menu = gtk.Menu()
			for child in gtkMenu.get_children():
				child.reparent(menu)
			self._window.set_menu(menu)
			gtkMenu.destroy()

			self._window.connect("key-press-event", self._on_key_press)
			self._window.connect("window-state-event", self._on_window_state_change)
		else:
			pass # warnings.warn("No Hildon", UserWarning, 2)

		if hildon is not None:
			self._window.set_title("Keypad")
		else:
			self._window.set_title("%s - Keypad" % self.__pretty_app_name__)

		callbackMapping = {
			"on_dialpad_quit": self._on_close,
		}
		self._widgetTree.signal_autoconnect(callbackMapping)

		if self._window:
			self._window.connect("destroy", gtk.main_quit)
			self._window.show_all()

		backgroundSetup = threading.Thread(target=self._idle_setup)
		backgroundSetup.setDaemon(True)
		backgroundSetup.start()

	def _idle_setup(self):
		"""
		If something can be done after the UI loads, push it here so it's not blocking the UI
		"""
		try:
			import osso
		except ImportError:
			osso = None
		self._osso = None
		if osso is not None:
			self._osso = osso.Context(Dialcentral.__app_name__, Dialcentral.__version__, False)
			device = osso.DeviceState(self._osso)
			device.set_device_state_callback(self._on_device_state_change, 0)
		else:
			pass # warnings.warn("No OSSO", UserWarning)

		try:
			import conic
		except ImportError:
			conic = None
		self._connection = None
		if conic is not None:
			self._connection = conic.Connection()
			self._connection.connect("connection-event", self._on_connection_change, Dialcentral.__app_magic__)
			self._connection.request_connection(conic.CONNECT_FLAG_NONE)
		else:
			pass # warnings.warn("No Internet Connectivity API ", UserWarning)

		import gv_backend
		import gc_backend
		import file_backend
		import evo_backend
		# import gmail_backend
		# import maemo_backend
		import null_views
		import gc_views

		try:
			os.makedirs(self._data_path)
		except OSError, e:
			if e.errno != 17:
				raise
		self._phoneBackends = [
			(gc_backend.GCDialer, os.path.join(self._data_path, "gc_cookies.txt")),
			(gv_backend.GVDialer, os.path.join(self._data_path, "gv_cookies.txt")),
		]
		backendFactory, cookieFile = None, None
		for backendFactory, cookieFile in self._phoneBackends:
			if os.path.exists(cookieFile):
				break
		else:
			backendFactory, cookieFile = self._phoneBackends[0]
		self._phoneBackend = backendFactory(cookieFile)
		gtk.gdk.threads_enter()
		try:
			self._dialpads = {
				True: gc_views.Dialpad(self._widgetTree, self._errorDisplay),
				False: null_views.Dialpad(self._widgetTree),
			}
			self._dialpads[True].set_number("")
			self._accountViews = {
				True: gc_views.AccountInfo(self._widgetTree, self._phoneBackend, self._errorDisplay),
				False: null_views.AccountInfo(self._widgetTree),
			}
			self._recentViews = {
				True: gc_views.RecentCallsView(self._widgetTree, self._phoneBackend, self._errorDisplay),
				False: null_views.RecentCallsView(self._widgetTree),
			}
			self._contactsViews = {
				True: gc_views.ContactsView(self._widgetTree, self._phoneBackend, self._errorDisplay),
				False: null_views.ContactsView(self._widgetTree),
			}
		finally:
			gtk.gdk.threads_leave()

		self._dialpads[True].dial = self._on_dial_clicked
		self._recentViews[True].number_selected = self._on_number_selected
		self._contactsViews[True].number_selected = self._on_number_selected

		fsContactsPath = os.path.join(self._data_path, "contacts")
		addressBooks = [
			self._phoneBackend,
			evo_backend.EvolutionAddressBook(),
			file_backend.FilesystemAddressBookFactory(fsContactsPath),
		]
		mergedBook = gc_views.MergedAddressBook(addressBooks, gc_views.MergedAddressBook.advanced_lastname_sorter)
		self._contactsViews[True].append(mergedBook)
		self._contactsViews[True].extend(addressBooks)
		self._contactsViews[True].open_addressbook(*self._contactsViews[True].get_addressbooks().next()[0][0:2])
		gtk.gdk.threads_enter()
		try:
			self._dialpads[self._isLoggedIn].enable()
			self._accountViews[self._isLoggedIn].enable()
			self._recentViews[self._isLoggedIn].enable()
			self._contactsViews[self._isLoggedIn].enable()
		finally:
			gtk.gdk.threads_leave()

		callbackMapping = {
			"on_paste": self._on_paste,
			"on_clearcookies_clicked": self._on_clearcookies_clicked,
			"on_notebook_switch_page": self._on_notebook_switch_page,
			"on_about_activate": self._on_about_activate,
		}
		self._widgetTree.signal_autoconnect(callbackMapping)

		self.attempt_login(2)

		return False

	def attempt_login(self, numOfAttempts = 1):
		"""
		@todo Handle user notification better like attempting to login and failed login

		@note Not meant to be called directly, but run as a seperate thread.
		"""
		assert 0 < numOfAttempts, "That was pointless having 0 or less login attempts"

		if not self._deviceIsOnline:
			warnings.warn("Attempted to login while device was offline", UserWarning, 2)
			return False

		loggedIn = False
		try:
			if self._phoneBackend.is_authed():
				loggedIn = True
			else:
				for x in xrange(numOfAttempts):
					gtk.gdk.threads_enter()
					try:
						username, password = self._credentials.request_credentials()
					finally:
						gtk.gdk.threads_leave()

					loggedIn = self._phoneBackend.login(username, password)
					if loggedIn:
						break
		except RuntimeError, e:
			warnings.warn(traceback.format_exc())
			gtk.gdk.threads_enter()
			try:
				self._errorDisplay.push_message(e.message)
			finally:
				gtk.gdk.threads_leave()

		gtk.gdk.threads_enter()
		try:
			if not loggedIn:
				self._errorDisplay.push_message("Login Failed")
			self._change_loggedin_status(loggedIn)
		finally:
			gtk.gdk.threads_leave()
		return loggedIn

	def display_error_message(self, msg):
		error_dialog = gtk.MessageDialog(None, 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE, msg)

		def close(dialog, response, editor):
			editor.about_dialog = None
			dialog.destroy()
		error_dialog.connect("response", close, self)
		error_dialog.run()

	@staticmethod
	def _on_close(*args, **kwds):
		gtk.main_quit()

	def _change_loggedin_status(self, newStatus):
		oldStatus = self._isLoggedIn

		self._dialpads[oldStatus].disable()
		self._accountViews[oldStatus].disable()
		self._recentViews[oldStatus].disable()
		self._contactsViews[oldStatus].disable()

		self._dialpads[newStatus].enable()
		self._accountViews[newStatus].enable()
		self._recentViews[newStatus].enable()
		self._contactsViews[newStatus].enable()

		if newStatus:
			if self._phoneBackend.get_callback_number() is None:
				self._phoneBackend.set_sane_callback()
			self._accountViews[True].update()

		self._isLoggedIn = newStatus

	def _on_device_state_change(self, shutdown, save_unsaved_data, memory_low, system_inactivity, message, userData):
		"""
		For shutdown or save_unsaved_data, our only state is cookies and I think the cookie manager handles that for us.
		For system_inactivity, we have no background tasks to pause

		@note Hildon specific
		"""
		if memory_low:
			self._phoneBackend.clear_caches()
			self._contactsViews[True].clear_caches()
			gc.collect()

	def _on_connection_change(self, connection, event, magicIdentifier):
		"""
		@note Hildon specific
		"""
		import conic

		status = event.get_status()
		error = event.get_error()
		iap_id = event.get_iap_id()
		bearer = event.get_bearer_type()

		if status == conic.STATUS_CONNECTED:
			self._window.set_sensitive(True)
			self._deviceIsOnline = True
			self._isLoggedIn = False
			backgroundLogin = threading.Thread(target=self.attempt_login, args=[2])
			backgroundLogin.setDaemon(True)
			backgroundLogin.start()
		elif status == conic.STATUS_DISCONNECTED:
			self._window.set_sensitive(False)
			self._deviceIsOnline = False
			self._isLoggedIn = False

	def _on_window_state_change(self, widget, event, *args):
		"""
		@note Hildon specific
		"""
		if event.new_window_state & gtk.gdk.WINDOW_STATE_FULLSCREEN:
			self._isFullScreen = True
		else:
			self._isFullScreen = False

	def _on_key_press(self, widget, event, *args):
		"""
		@note Hildon specific
		"""
		if event.keyval == gtk.keysyms.F6:
			if self._isFullScreen:
				self._window.unfullscreen()
			else:
				self._window.fullscreen()

	def _on_clearcookies_clicked(self, *args):
		self._phoneBackend.logout()
		self._accountViews[True].clear()
		self._recentViews[True].clear()
		self._contactsViews[True].clear()

		# re-run the inital grandcentral setup
		backgroundLogin = threading.Thread(target=self.attempt_login, args=[2])
		backgroundLogin.setDaemon(True)
		backgroundLogin.start()

	def _on_notebook_switch_page(self, notebook, page, page_num):
		if page_num == 1:
			self._contactsViews[self._isLoggedIn].update()
		elif page_num == 3:
			self._recentViews[self._isLoggedIn].update()

		tabTitle = self._notebook.get_tab_label(self._notebook.get_nth_page(page_num)).get_text()
		if hildon is not None:
			self._window.set_title(tabTitle)
		else:
			self._window.set_title("%s - %s" % (self.__pretty_app_name__, tabTitle))

	def _on_number_selected(self, number):
		self._dialpads[True].set_number(number)
		self._notebook.set_current_page(0)

	def _on_dial_clicked(self, number):
		"""
		@todo Potential blocking on web access, maybe we should defer parts of this or put up a dialog?
		"""
		try:
			loggedIn = self._phoneBackend.is_authed()
		except RuntimeError, e:
			warnings.warn(traceback.format_exc())
			loggedIn = False
			self._errorDisplay.push_message(e.message)
			return

		if not loggedIn:
			self._errorDisplay.push_message(
				"Backend link with grandcentral is not working, please try again"
			)
			return

		dialed = False
		try:
			assert self._phoneBackend.get_callback_number() != ""
			self._phoneBackend.dial(number)
			dialed = True
		except RuntimeError, e:
			warnings.warn(traceback.format_exc())
			self._errorDisplay.push_message(e.message)
		except ValueError, e:
			warnings.warn(traceback.format_exc())
			self._errorDisplay.push_message(e.message)

		if dialed:
			self._dialpads[True].clear()
			self._recentViews[True].clear()

	def _on_paste(self, *args):
		contents = self._clipboard.wait_for_text()
		self._dialpads[True].set_number(contents)

	def _on_about_activate(self, *args):
		dlg = gtk.AboutDialog()
		dlg.set_name(self.__pretty_app_name__)
		dlg.set_version(self.__version__)
		dlg.set_copyright("Copyright 2008 - LGPL")
		dlg.set_comments("Dialer is designed to interface with your Google Grandcentral account.  This application is not affiliated with Google or Grandcentral in any way")
		dlg.set_website("http://gc-dialer.garage.maemo.org/")
		dlg.set_authors(["<z2n@merctech.com>", "Eric Warnke <ericew@gmail.com>", "Ed Page <edpage@byu.net>"])
		dlg.run()
		dlg.destroy()


def run_doctest():
	import doctest

	failureCount, testCount = doctest.testmod()
	if not failureCount:
		print "Tests Successful"
		sys.exit(0)
	else:
		sys.exit(1)


def run_dialpad():
	gtk.gdk.threads_init()
	if hildon is not None:
		gtk.set_application_name(Dialcentral.__pretty_app_name__)
	handle = Dialcentral()
	gtk.main()


class DummyOptions(object):

	def __init__(self):
		self.test = False


if __name__ == "__main__":
	if len(sys.argv) > 1:
		try:
			import optparse
		except ImportError:
			optparse = None

		if optparse is not None:
			parser = optparse.OptionParser()
			parser.add_option("-t", "--test", action="store_true", dest="test", help="Run tests")
			(commandOptions, commandArgs) = parser.parse_args()
	else:
		commandOptions = DummyOptions()
		commandArgs = []

	if commandOptions.test:
		run_doctest()
	else:
		run_dialpad()