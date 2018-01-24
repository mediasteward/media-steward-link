# -*- coding: utf-8 -*-
#
# Media Steward Link
# Copyright (C) 2018  Matthew C. Ruschmann <https://matthew.ruschmann.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import sys
import requests
from string import Template

import xbmc
import xbmcgui
import xbmcaddon

CANCEL_CHECK_LOOP_PERIOD = 0.2
CODE_CHECK_LOOP_ITERATIONS = 25
BASE_URL = "https://stew.ruschmann.net"

toaster = xbmcgui.Dialog()
addon = xbmcaddon.Addon()


def json_request(url, notice=toaster.ok):
    try:
        r = requests.get(url)
    except Exception as e:
        notice("Media Steward", addon.getLocalizedString(983010))  # "Unable to connect to Media Steward"
        xbmc.log(e, level=xbmc.LOGNOTICE)
        return None
    else:
        if r.status_code == 200 and r.headers['content-type'] == 'application/json':
            try:
                j = r.json()
            except Exception as e:
                notice("Media Steward", addon.getLocalizedString(983011))  # "Invalid response from Media Steward"
                xbmc.log(e, level=xbmc.LOGNOTICE)
                return None
            else:
                return j
        else:
            # "Server returned ${<status>} error"
            notice("Media Steward", Template(addon.getLocalizedString(983012)).safe_substitute(status=r.status_code))
            xbmc.log(str(r.headers), level=xbmc.LOGNOTICE)
            return None


def register_new():
    restart = False
    j = json_request(BASE_URL + "/register/new")
    if j is not None:
        monitor = xbmc.Monitor()
        count = 0
        code = j['code']
        uuid = j['uuid']
        expiration_seconds = j['expiration_seconds']
        dialog = xbmcgui.DialogProgress()
        dialog.create(addon.getLocalizedString(983013),  # "Activating Media Steward..."
                      addon.getLocalizedString(983014),  # "Please enter your activation code at the activation site."
                      Template(addon.getLocalizedString(983015)).safe_substitute(site=BASE_URL+"/activate"),
                      Template(addon.getLocalizedString(983016)).safe_substitute(code=code))
        dialog.update(100)
        closed = dialog.iscanceled()
        activated = False
        invalid = False
        status = ''
        while not monitor.abortRequested() and not closed:
            count += 1
            if count % CODE_CHECK_LOOP_ITERATIONS == 0:
                j = json_request(BASE_URL + "/register/check/" + code)
                if j is not None:
                    status = j['status']
                    if status == 'activated':
                        addon.setSetting('uuid', uuid)
                        activated = True
                        restart = True
                    elif status == 'valid':
                        seconds_remaining = j['seconds_remaining']
                        dialog.update(max(int(round(100 * seconds_remaining / expiration_seconds)), 0))
                    else:
                        invalid = True
            closed = dialog.iscanceled() or activated or invalid
            if not closed:
                monitor.waitForAbort(CANCEL_CHECK_LOOP_PERIOD)
        dialog.close()
        if invalid:
            if status == 'invalid':
                toaster.ok("Media Steward", addon.getLocalizedString(983017))  # "Activation code is now invalid"
            elif status == 'expired':
                toaster.ok("Media Steward", addon.getLocalizedString(983018))  # "Activation code has expired"
    return restart


if __name__ == '__main__':
    if len(sys.argv) > 1:
        choice = toaster.select(addon.getLocalizedString(983019),  # "Set UUID for Media Steward"
                                [addon.getLocalizedString(983020),  # "Retrieve new activation code"
                                 addon.getLocalizedString(983021)])  # "Manually enter UUID"
        if choice == 0:
            restart_now = register_new()
        elif choice == 1:
            uuid_user = toaster.input(addon.getLocalizedString(983022),  # "Enter new 32-character UUID"
                                      addon.getSetting('uuid'), xbmcgui.INPUT_ALPHANUM)
            if len(uuid_user) == 32 and uuid_user.isalnum():
                addon.setSetting('uuid', uuid_user.upper())
                restart_now = True
            else:
                toaster.ok("Media Steward", addon.getLocalizedString(983023))  # "Invalid UUID"
                restart_now = False
        else:
            restart_now = False
    else:
        restart_now = True

    if restart_now:
        addon.setSetting('reconnect', 'true')
