# -*- coding: utf-8 -*-
#
# Kodi Cloud Link
# Copyright (C) 2017  Matthew C. Ruschmann <https://matthew.ruschmann.net>
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
import struct
import errno
import zlib
import json
import time

import xbmc
import xbmcgui
import xbmcaddon

TCP_HOST = '127.0.0.1'
TCP_PORT = 59348

CONSECUTIVE_RETRIES = 20  # decrease
SHORT_WAIT_SECONDS = 5  # increase
LONG_WAIT_SECONDS = 30  # increase
IDLE_SECONDS = 0.05

# parameters shared with the CloudLinkServer
MAX_NUMBER_OF_PACKETS = 32767
MAX_MESSAGE_SIZE = 2100000000


def soft_close():
    global conn, state
    if conn is not None:
        conn.shutdown(socket.SHUT_RDWR)
    hard_close()


def hard_close():
    global conn, state
    if conn is not None:
        conn.close()
        conn = None
    state = 'disconnected'


if __name__ == '__main__':
    monitor = xbmc.Monitor()
    conn = None
    state = 'disconnected'
    data = b''
    header = b''
    bytes_remaining = 0
    packets_remaining = 0
    control_message_flag = False
    tries = 0
    wait_seconds = LONG_WAIT_SECONDS
    start = 0

    # The main loop performs actions based on the current state. It continues
    # looping until an abort is requested by Kodi.
    while not monitor.abortRequested():
        if state == 'disconnected':
            # TODO do not use blocking socket during connect
            # attempt to connect
            start = time.clock()
            err_no = -1234567890
            if conn is None:
                # create a socket if None exists
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            xbmc.log("CloudLink connecting to %s" % TCP_HOST, level=xbmc.LOGNOTICE)
            tries += 1
            try:
                conn.connect((TCP_HOST, TCP_PORT))
            except socket.error as err:
                if err.errno == errno.EISCONN:
                    # this should not happen, but handle it if it does
                    xbmc.log("CloudLink already connected to %s" % TCP_HOST, level=xbmc.LOGWARNING)
                    conn.settimeout(IDLE_SECONDS)
                    state = 'idle'
                    bytes_remaining = 4
                    tries = 0
                else:
                    # on failed connection
                    if tries % CONSECUTIVE_RETRIES == 0:
                        toast = xbmcgui.Dialog()
                        toast.notification("CloudLink", "Unable to connect to " + TCP_HOST + ". Trying again in " +
                                           str(int(round(LONG_WAIT_SECONDS / 60))) + " minutes.",
                                           icon=xbmcgui.NOTIFICATION_WARNING)
                        wait_seconds = LONG_WAIT_SECONDS
                    else:
                        wait_seconds = SHORT_WAIT_SECONDS
                    xbmc.log("CloudLink connection failed: errno=%d. Connection failed %d consecutive times, waiting "
                             "%d seconds before trying again" % (err.errno, tries, wait_seconds), level=xbmc.LOGNOTICE)
                    # start a new connection just in case the existing socket is bad
                    hard_close()
            else:
                # on successful connection
                xbmc.log("CloudLink connected to %s" % TCP_HOST, level=xbmc.LOGNOTICE)
                conn.settimeout(IDLE_SECONDS)
                announce = "{\"version\":\"" + xbmcaddon.Addon().getAddonInfo('version') + "\",\"uuid\":\"main\"}"
                announce = zlib.compress(announce.encode('utf-8'))
                conn.send(struct.pack('>l', -1))
                conn.send(struct.pack('>l', len(announce)))
                conn.send(announce)
                state = 'idle'
                bytes_remaining = 4
                tries = 0

        if state == 'idle':
            try:
                # check the number of packets
                receive_buffer = conn.recv(bytes_remaining)
                header += receive_buffer
                bytes_remaining -= len(receive_buffer)
            except socket.timeout:
                pass
            except socket.error as err:
                if err.errno == errno.EAGAIN:
                    # no bytes to receive now, continue
                    pass
                else:
                    # failed receive
                    xbmc.log("CloudLink exception: %s, disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    hard_close()
            else:
                # on successful receive
                if bytes_remaining < 0:
                    # received more bytes than we wanted, should never happen
                    xbmc.log("CloudLink incorrect header size during %s" % state, level=xbmc.LOGWARNING)
                    soft_close()
                elif bytes_remaining == 0:
                    # great! we got what we wanted
                    xbmc.log("CloudLink received number of packets", level=xbmc.LOGNOTICE)
                    packets_remaining = struct.unpack('>l', header)[0]
                    header = b''
                    bytes_remaining = 4
                    if packets_remaining == -1:
                        # this is a control message
                        packets_remaining = 1
                        control_message_flag = True
                        state = 'sizing'
                    elif packets_remaining > MAX_NUMBER_OF_PACKETS or packets_remaining < 1:
                        # this should not happen, something has gone wrong
                        soft_close()
                    else:
                        # request message
                        control_message_flag = False
                        state = 'sizing'
                elif len(receive_buffer) == 0:
                    # disconnect signal from the other end
                    xbmc.log("CloudLink disconnecting gracefully", level=xbmc.LOGNOTICE)
                    soft_close()
                elif bytes_remaining > 0:
                    pass
                else:
                    # this should never happen
                    xbmc.log("CloudLink disconnecting due to error in number of packets", level=xbmc.LOGNOTICE)
                    hard_close()

        if state == 'sizing':
            try:
                # check for size of message
                receive_buffer = conn.recv(bytes_remaining)
                header += receive_buffer
                bytes_remaining -= len(receive_buffer)
            except socket.timeout:
                pass
            except socket.error as err:
                if err.errno == errno.EAGAIN:
                    # no bytes to receive now, continue
                    pass
                else:
                    # failed receive
                    xbmc.log("CloudLink exception: %s, disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    hard_close()
            else:
                # on successful receive
                if bytes_remaining < 0:
                    # received more bytes than we wanted, should never happen
                    xbmc.log("CloudLink incorrect header size during sizing", level=xbmc.LOGWARNING)
                    soft_close()
                elif bytes_remaining == 0:
                    # great! we got what we wanted
                    xbmc.log("CloudLink received number of bytes %d", level=xbmc.LOGNOTICE)
                    bytes_remaining = struct.unpack('>l', header)[0]
                    header = b''
                    if bytes_remaining < 1 or bytes_remaining > MAX_MESSAGE_SIZE:
                        soft_close()
                    else:
                        state = 'message'
                elif len(receive_buffer) == 0:
                    # disconnect signal from the other end
                    xbmc.log("CloudLink disconnecting gracefully", level=xbmc.LOGNOTICE)
                    hard_close()
                    conn = None
                elif bytes_remaining > 0:
                    pass
                else:
                    # this should never happen
                    xbmc.log("CloudLink disconnecting due to error in sizing", level=xbmc.LOGNOTICE)
                    hard_close()

        if state == 'message':
            try:
                # receive the message
                receive_buffer = conn.recv(bytes_remaining)
                data += receive_buffer
                bytes_remaining -= len(receive_buffer)
            except socket.timeout:
                pass
            except socket.error as err:
                if err.errno == errno.EAGAIN:
                    # no bytes to receive now, continue
                    pass
                else:
                    # failed receive
                    xbmc.log("CloudLink exception: %s, disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    hard_close()
            else:
                # on successful receive
                if bytes_remaining < 0:
                    xbmc.log("CloudLink incorrect message size", level=xbmc.LOGWARNING)
                    hard_close()
                elif bytes_remaining == 0:
                    xbmc.log("CloudLink received message", level=xbmc.LOGNOTICE)
                    packets_remaining -= 1
                    if packets_remaining <= 0:
                        state = 'processing'
                    else:
                        state = 'sizing'
                    bytes_remaining = 4
                elif len(receive_buffer) == 0:
                    xbmc.log("CloudLink disconnecting gracefully", level=xbmc.LOGNOTICE)
                    soft_close()
                elif bytes_remaining > 0:
                    pass
                else:
                    xbmc.log("CloudLink disconnecting due to error in message", level=xbmc.LOGNOTICE)
                    hard_close()

        if state == 'processing':
            if control_message_flag:
                response = json.loads(zlib.decompress(data).decode('utf-8'))
                if 'valid-version' not in response or not response['valid-version']:
                    xbmc.log("CloudLink disconnecting due to error in message", level=xbmc.LOGERROR)
                    toast = xbmcgui.Dialog()
                    toast.notification("CloudLink", "Outdated addon version. Please update.",
                                       icon=xbmcgui.NOTIFICATION_ERROR)
                    break
                if 'valid-uuid' not in response or not response['valid-uuid']:
                    xbmc.log("CloudLink disconnecting due to error in message", level=xbmc.LOGERROR)
                    toast = xbmcgui.Dialog()
                    toast.notification("CloudLink", "Invalid UUID. Please change settings.",
                                       icon=xbmcgui.NOTIFICATION_ERROR)
                    break
                data = b''
                state = 'idle'
            else:
                try:
                    response = xbmc.executeJSONRPC(zlib.decompress(data))
                    xbmc.log("CloudLink sending %s" % response, level=xbmc.LOGNOTICE)
                    response = zlib.compress(response.encode('utf-8'))
                    conn.send(struct.pack('>l', 1))  # TODO packetize
                    conn.send(struct.pack('>l', len(response)))
                    conn.send(response)
                except socket.error as err:
                    xbmc.log("CloudLink exception: %s, disconnecting" % str(err), level=xbmc.LOGNOTICE)
                    hard_close()
                else:
                    data = b''
                    state = 'idle'

        if state == 'disconnected':
            monitor.waitForAbort(wait_seconds - time.clock() - start)

    # end the service
    hard_close()
