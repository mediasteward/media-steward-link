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

import socket
import ssl
import select
import struct
import errno
import zlib
import json
import math
import time
from string import Template
import msgs

import xbmc
import xbmcgui
import xbmcaddon

TCP_HOST = 'link.mediasteward.net'
TCP_PORT = 59348

SHORT_WAIT_SECONDS = 20.0
LONG_WAIT_SECONDS = 120.0
IDLE_SECONDS = 1.0
RECONNECT_CHECK_SECONDS = 5.0


def send_raw_data(raw_data):
    global conn
    total_sent = 0
    while total_sent < len(raw_data):
        sent = conn.send(raw_data[total_sent:])
        if sent == 0:
            RuntimeError("socket disconnected during send")
        total_sent += sent


def send(message, message_id=0):
    compressed_message = zlib.compress(message)
    sent = 'none'
    pkt = 0
    first = 0
    last = 0
    while not sent == 'done':
        try:
            if sent == 'none':
                if message_id < 0:
                    num_packets = 1
                    send_raw_data(struct.pack('>l', message_id))
                else:
                    num_packets = int(math.ceil(float(len(compressed_message)) / float(msgs.MAX_MESSAGE_SIZE)))
                    send_raw_data(struct.pack('>l', 1))
                sent = 'id'
            for pkt in range(pkt, num_packets):
                if sent == 'id':
                    if pkt + 1 < num_packets:
                        send_raw_data(struct.pack('>l', msgs.MAX_MESSAGE_SIZE))
                        first = pkt * msgs.MAX_MESSAGE_SIZE
                        last = (pkt + 1) * msgs.MAX_MESSAGE_SIZE
                    else:
                        send_raw_data(struct.pack('>l', len(compressed_message)))
                        first = 0
                        last = len(compressed_message)
                    sent = 'size'
                if sent == 'size':
                    send_raw_data(compressed_message[first:last])
                    sent = 'id'
            sent = 'done'
        except ssl.SSLWantReadError:
            select.select([conn], [], [], IDLE_SECONDS)
        except ssl.SSLWantWriteError:
            select.select([], [conn], [], IDLE_SECONDS)


def soft_close():
    global conn, state
    if conn is not None:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception as e:
            xbmc.log("Media Steward shutdown failed: %s" % str(e), level=xbmc.LOGDEBUG)
    hard_close()


def hard_close():
    global conn, state
    if conn is not None:
        xbmc.log("Media Steward disconnecting", level=xbmc.LOGNOTICE)
        conn.close()
        conn = None
    state = 'disconnected'


if __name__ == '__main__':
    monitor = xbmc.Monitor()
    addon = xbmcaddon.Addon()
    conn = None
    data = b''
    header = b''
    bytes_remaining = 0
    packets_remaining = 0
    control_message_flag = False
    short_retry = False  # only do a short retry when previously connected
    state = 'connect'
    context = ssl.create_default_context()

    # defaults to make PEP8 happy
    wait_seconds = SHORT_WAIT_SECONDS
    start = time.time()
    last_reconnect_check = start

    # The main loop performs actions based on the current state. It continues
    # looping until an abort is requested by Kodi.
    while not monitor.abortRequested():

        if state == 'connect':
            uuid = addon.getSetting('uuid')
            if len(uuid) == 32 and uuid.isalnum():
                # TODO do not use blocking socket during connect
                # attempt to connect
                err_no = -1234567890
                # create a new socket
                if addon.getSetting('ssl-validation') == 'false':
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                conn = context.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM),
                                           server_hostname=TCP_HOST)
                xbmc.log("Media Steward connecting to %s" % TCP_HOST, level=xbmc.LOGNOTICE)
                try:
                    conn.connect((TCP_HOST, TCP_PORT))
                except ssl.CertificateError as err:
                    xbmc.log("Media Steward cert error: %s, will retry in %d seconds" % (str(err), LONG_WAIT_SECONDS),
                             level=xbmc.LOGERROR)
                    if addon.getSetting('hide-connection') == 'false':
                        toast = xbmcgui.Dialog()
                        toast.notification("Media Steward", str(err), icon=xbmcgui.NOTIFICATION_ERROR)
                    wait_seconds = LONG_WAIT_SECONDS
                    soft_close()
                    start = time.time()
                except ssl.SSLError as err:
                    xbmc.log("Media Steward ssl error: %s, will retry in %d seconds" % (str(err), LONG_WAIT_SECONDS),
                             level=xbmc.LOGERROR)
                    if addon.getSetting('hide-connection') == 'false':
                        toast = xbmcgui.Dialog()
                        toast.notification("Media Steward", str(err), icon=xbmcgui.NOTIFICATION_ERROR)
                    wait_seconds = LONG_WAIT_SECONDS
                    soft_close()
                    start = time.time()
                except socket.error as err:
                    if err.errno == errno.EISCONN:
                        # this should not happen, but handle it if it does
                        xbmc.log("Media Steward already connected to %s" % TCP_HOST, level=xbmc.LOGWARNING)
                        conn.settimeout(IDLE_SECONDS)
                        state = 'idle'
                        bytes_remaining = 4
                        short_retry = True
                    else:
                        short_retry = False  # do not short retry again until connected
                        # on failed connection
                        if not short_retry:
                            wait = str(int(round(LONG_WAIT_SECONDS / 60)))
                            if addon.getSetting('hide-connection') == 'false':
                                text = Template(addon.getLocalizedString(983030)).safe_substitute(host=TCP_HOST,
                                                                                                  wait=wait)
                                toast = xbmcgui.Dialog()
                                toast.notification("Media Steward", text, icon=xbmcgui.NOTIFICATION_WARNING)
                            wait_seconds = LONG_WAIT_SECONDS
                        else:
                            wait_seconds = SHORT_WAIT_SECONDS
                        xbmc.log("Media Steward connection failed: errno=%d. Connection failed, "
                                 "waiting %d seconds before trying again" % (err.errno, wait_seconds),
                                 level=xbmc.LOGNOTICE)
                        # start a new connection just in case the existing socket is bad
                        hard_close()
                        start = time.time()
                else:
                    try:
                        # on successful connection
                        xbmc.log("Media Steward connected to %s" % TCP_HOST, level=xbmc.LOGNOTICE)
                        conn.settimeout(IDLE_SECONDS)
                        announce = {'version': addon.getAddonInfo('version'), 'uuid': uuid}
                        send(json.dumps(announce).encode('utf-8'), message_id=msgs.MSG_ID_ANNOUNCE)
                    except socket.error as err:
                        xbmc.log("Media Steward exception 'sending announce': %s, disconnecting" % str(err),
                                 level=xbmc.LOGNOTICE)
                        soft_close()
                    except RuntimeError as err:
                        xbmc.log("Media Steward exception 'sending announce': %s, disconnecting" % str(err),
                                 level=xbmc.LOGNOTICE)
                        soft_close()
                    else:
                        state = 'idle'
                        bytes_remaining = 4
                        short_retry = True
            else:
                state = 'uuid'
                toast = xbmcgui.Dialog()
                # "Please acquire valid UUID."
                toast.notification("Media Steward", addon.getLocalizedString(983031), icon=xbmcgui.NOTIFICATION_ERROR)

        if state == 'idle':
            try:
                # check the number of packets
                receive_buffer = conn.recv(bytes_remaining)
                header += receive_buffer
                bytes_remaining -= len(receive_buffer)
            except ssl.SSLWantReadError:
                select.select([conn], [], [], IDLE_SECONDS)
            except ssl.SSLWantWriteError:
                select.select([], [conn], [], IDLE_SECONDS)
            except socket.timeout:
                pass
            except ssl.SSLError as err:
                if err.message == 'The read operation timed out':
                    pass
                else:
                    xbmc.log("Media Steward SSL exception in 'idle': %s,disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    soft_close()
            except socket.error as err:
                if err.errno == errno.EAGAIN:
                    # no bytes to receive now, continue
                    pass
                else:
                    # failed receive
                    xbmc.log("Media Steward exception in 'idle': %s, disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    soft_close()
            else:
                # on successful receive
                if bytes_remaining < 0:
                    # received more bytes than we wanted, should never happen
                    xbmc.log("Media Steward incorrect header size during %s" % state, level=xbmc.LOGWARNING)
                    soft_close()
                elif bytes_remaining == 0:
                    # great! we got what we wanted
                    packets_remaining = struct.unpack('>l', header)[0]
                    xbmc.log("Media Steward received number of packets %d" % packets_remaining, level=xbmc.LOGNOTICE)
                    header = b''
                    bytes_remaining = 4
                    if packets_remaining == msgs.MSG_ID_VERIFICATION:
                        # this is a control message
                        packets_remaining = 1
                        control_message_flag = True
                        state = 'sizing'
                    elif packets_remaining > msgs.MAX_NUMBER_OF_PACKETS or packets_remaining < 1:
                        # this should not happen, something has gone wrong
                        soft_close()
                    else:
                        # request message
                        control_message_flag = False
                        state = 'sizing'
                elif len(receive_buffer) == 0:
                    # disconnect signal from the other end
                    xbmc.log("Media Steward disconnecting gracefully", level=xbmc.LOGNOTICE)
                    soft_close()
                elif bytes_remaining > 0:
                    pass
                else:
                    # this should never happen
                    xbmc.log("Media Steward disconnecting due to error in number of packets", level=xbmc.LOGNOTICE)
                    soft_close()

        if state == 'sizing':
            try:
                # check for size of message
                receive_buffer = conn.recv(bytes_remaining)
                header += receive_buffer
                bytes_remaining -= len(receive_buffer)
            except ssl.SSLWantReadError:
                select.select([conn], [], [], IDLE_SECONDS)
            except ssl.SSLWantWriteError:
                select.select([], [conn], [], IDLE_SECONDS)
            except socket.timeout:
                pass
            except ssl.SSLError as err:
                if err.message == 'The read operation timed out':
                    pass
                else:
                    xbmc.log("Media Steward SSL exception in 'sizing': %s, disconnecting" % str(err),
                             level=xbmc.LOGNOTICE)
                    soft_close()
            except socket.error as err:
                if err.errno == errno.EAGAIN:
                    # no bytes to receive now, continue
                    pass
                else:
                    # failed receive
                    xbmc.log("Media Steward exception in 'sizing': %s, disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    soft_close()
            else:
                # on successful receive
                if bytes_remaining < 0:
                    # received more bytes than we wanted, should never happen
                    xbmc.log("Media Steward incorrect header size during sizing", level=xbmc.LOGWARNING)
                    soft_close()
                elif bytes_remaining == 0:
                    # great! we got what we wanted
                    bytes_remaining = struct.unpack('>l', header)[0]
                    xbmc.log("Media Steward received number of bytes %d" % bytes_remaining, level=xbmc.LOGNOTICE)
                    header = b''
                    if bytes_remaining < 1 or bytes_remaining > msgs.MAX_MESSAGE_SIZE:
                        soft_close()
                    else:
                        state = 'message'
                elif len(receive_buffer) == 0:
                    # disconnect signal from the other end
                    xbmc.log("Media Steward disconnecting gracefully", level=xbmc.LOGNOTICE)
                    soft_close()
                    conn = None
                elif bytes_remaining > 0:
                    pass
                else:
                    # this should never happen
                    xbmc.log("Media Steward disconnecting due to error in sizing", level=xbmc.LOGNOTICE)
                    soft_close()

        if state == 'message':
            try:
                # receive the message
                receive_buffer = conn.recv(bytes_remaining)
                data += receive_buffer
                bytes_remaining -= len(receive_buffer)
            except ssl.SSLWantReadError:
                select.select([conn], [], [], IDLE_SECONDS)
            except ssl.SSLWantWriteError:
                select.select([], [conn], [], IDLE_SECONDS)
            except socket.timeout:
                pass
            except ssl.SSLError as err:
                if err.message == 'The read operation timed out':
                    pass
                else:
                    xbmc.log("Media Steward SSL exception in 'message': %s, disconnecting" % str(err),
                             level=xbmc.LOGNOTICE)
                    soft_close()
            except socket.error as err:
                if err.errno == errno.EAGAIN:
                    # no bytes to receive now, continue
                    pass
                else:
                    # failed receive
                    xbmc.log("Media Steward exception in 'message': %s, disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    soft_close()
            else:
                # on successful receive
                if bytes_remaining < 0:
                    xbmc.log("Media Steward incorrect message size", level=xbmc.LOGWARNING)
                    soft_close()
                elif bytes_remaining == 0:
                    xbmc.log("Media Steward received message", level=xbmc.LOGNOTICE)
                    packets_remaining -= 1
                    if packets_remaining <= 0:
                        state = 'processing'
                    else:
                        state = 'sizing'
                    bytes_remaining = 4
                elif len(receive_buffer) == 0:
                    xbmc.log("Media Steward disconnecting gracefully", level=xbmc.LOGNOTICE)
                    soft_close()
                elif bytes_remaining > 0:
                    pass
                else:
                    xbmc.log("Media Steward disconnecting due to error in message", level=xbmc.LOGNOTICE)
                    soft_close()

        if state == 'processing':
            if control_message_flag:
                response = json.loads(zlib.decompress(data).decode('utf-8'))
                xbmc.log("Media Steward received announce %s" % response, level=xbmc.LOGNOTICE)
                if 'valid-version' not in response or not response['valid-version']:
                    xbmc.log("Media Steward disconnecting due to invalid version", level=xbmc.LOGERROR)
                    toast = xbmcgui.Dialog()
                    # "Outdated addon version. Please update."
                    toast.notification("Media Steward", addon.getLocalizedString(983032),
                                       icon=xbmcgui.NOTIFICATION_ERROR)
                    soft_close()
                    break  # ends the main loop, user must upgrade and restart
                elif 'valid-uuid' not in response or not response['valid-uuid']:
                    xbmc.log("Media Steward disconnecting due to invalid uuid", level=xbmc.LOGERROR)
                    toast = xbmcgui.Dialog()
                    # "Invalid UUID. Please change settings."
                    toast.notification("Media Steward", addon.getLocalizedString(983033),
                                       icon=xbmcgui.NOTIFICATION_ERROR)
                    data = b''
                    soft_close()
                    state = 'uuid'
                else:
                    data = b''
                    state = 'idle'
            else:
                try:
                    response = xbmc.executeJSONRPC(zlib.decompress(data))
                    xbmc.log("Media Steward sending %s" % response, level=xbmc.LOGNOTICE)
                    send(response)
                except socket.error as err:
                    xbmc.log("Media Steward exception 'processing': %s, disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    data = b''
                    soft_close()
                except RuntimeError as err:
                    xbmc.log("Media Steward exception 'sending announce': %s, disconnecting" % str(err),
                             level=xbmc.LOGNOTICE)
                    data = b''
                    soft_close()
                else:
                    data = b''
                    state = 'idle'

        if state == 'disconnected':
            if monitor.waitForAbort(IDLE_SECONDS):
                break
            if time.time() - start > wait_seconds:
                state = 'connect'
        elif state == 'uuid':
            if monitor.waitForAbort(IDLE_SECONDS):
                break

        if time.time() > last_reconnect_check + RECONNECT_CHECK_SECONDS:
            last_reconnect_check = time.time()
            if xbmcaddon.Addon().getSetting('reconnect') == 'true':
                xbmc.log("Media Steward reconnecting for settings change", level=xbmc.LOGNOTICE)
                if addon.getSetting('hide-connection') == 'false':
                    toast = xbmcgui.Dialog()
                    toast.notification("Media Steward", addon.getLocalizedString(983034))  # "Reconnecting..."
                xbmcaddon.Addon().setSetting('reconnect', 'false')
                soft_close()  # does nothing if disconnected already
                state = 'connect'

    # end the service
    xbmc.log("Media Steward exiting", level=xbmc.LOGNOTICE)
    soft_close()
