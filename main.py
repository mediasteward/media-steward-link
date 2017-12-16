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

import xbmc
#import xbmcaddon
#import xbmcgui

TCP_HOST = '127.0.0.1'
TCP_PORT = 59348

LONG_WAIT_SECONDS = 5  # TODO increase
IDLE_SECONDS = 0.1


if __name__ == '__main__':
    monitor = xbmc.Monitor()
    conn = None
    state = 'disconnected'
    data = b''
    header = b''
    bytes_remaining = 0
    packets_remaining = 0
    retries = 0

    while not monitor.abortRequested():
        if state == 'disconnected':
            err_no = -1234567890
            if conn is None:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Retry connecting a few times quickly
            xbmc.log("KodiCloudLink connecting to %s" % TCP_HOST, level=xbmc.LOGNOTICE)
            retries += 1
            err_no = conn.connect_ex((TCP_HOST, TCP_PORT))
            if err_no == 0:
                xbmc.log("KodiCloudLink connected to %s" % TCP_HOST, level=xbmc.LOGNOTICE)
                conn.setblocking(0)
                state = 'idle'
                bytes_remaining = 4
                retries = 0
            elif err_no == 106:
                xbmc.log("KodiCloudLink already connected to %s" % TCP_HOST, level=xbmc.LOGNOTICE)
                conn.setblocking(0)
                state = 'idle'
                bytes_remaining = 4
                retries = 0
            else:
                # Long wait before trying again
                xbmc.log("KodiCloudLink connection failed %d times, waiting %d seconds before trying again" %
                         (retries, LONG_WAIT_SECONDS), level=xbmc.LOGWARNING)
                monitor.waitForAbort(LONG_WAIT_SECONDS)

        if state == 'idle':
            try:
                # Check number of packets
                buffer = conn.recv(bytes_remaining)
                header += buffer
                bytes_remaining -= len(buffer)
                if bytes_remaining < 0:
                    xbmc.log("KodiCloudLink incorrect header size during %s" % state, level=xbmc.LOGWARNING)
                    state = 'disconnected'
                    conn.close()
                    conn = None
                elif bytes_remaining == 0:
                    xbmc.log("KodiCloudLink received number of packets", level=xbmc.LOGNOTICE)
                    packets_remaining = struct.unpack('>l', header)[0]
                    bytes_remaining = 4
                    header = b''
                    state = 'sizing'
                    # TODO check number of packets
                elif len(buffer) == 0:
                    xbmc.log("KodiCloudLink disconnecting gracefully", level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.shutdown(socket.SHUT_RDWR)
                    conn.close()
                    conn = None
                else:
                    xbmc.log("KodiCloudLink disconnecting due to error in number of packets", level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.close()
                    conn = None
            except socket.error as msg:
                if msg[0] == errno.EAGAIN:
                    monitor.waitForAbort(IDLE_SECONDS)
                else:
                    xbmc.log("KodiCloudLink exception: %s, disconnecting" % str(msg), level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.close()
                    conn = None

        if state == 'sizing':
            try:
                # Check for size of packet
                buffer = conn.recv(bytes_remaining)
                header += buffer
                bytes_remaining -= len(buffer)
                if bytes_remaining < 0:
                    xbmc.log("KodiCloudLink incorrect header size during sizing", level=xbmc.LOGWARNING)
                    state = 'disconnected'
                    conn.close()
                    conn = None
                elif bytes_remaining == 0:
                    xbmc.log("KodiCloudLink received number of bytes", level=xbmc.LOGNOTICE)
                    bytes_remaining = struct.unpack('>l', header)[0]
                    header = b''
                    state = 'message'
                    # TODO check max size
                elif len(buffer) == 0:
                    xbmc.log("KodiCloudLink disconnecting gracefully", level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.shutdown(socket.SHUT_RDWR)
                    conn.close()
                    conn = None
                else:
                    xbmc.log("KodiCloudLink disconnecting due to error in sizing", level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.close()
                    conn = None
            except socket.error as msg:
                if msg[0] == errno.EAGAIN:
                    monitor.waitForAbort(IDLE_SECONDS)
                else:
                    xbmc.log("KodiCloudLink exception: %s, disconnecting" % str(msg), level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.close()
                    conn = None

        if state == 'message':
            try:
                # Check for size of packet
                buffer = conn.recv(bytes_remaining)
                data += buffer
                bytes_remaining -= len(buffer)
                if bytes_remaining < 0:
                    xbmc.log("KodiCloudLink incorrect message size", level=xbmc.LOGWARNING)
                    state = 'disconnected'
                    conn.close()
                    conn = None
                elif bytes_remaining == 0:
                    xbmc.log("KodiCloudLink received message", level=xbmc.LOGNOTICE)
                    packets_remaining -= 1
                    if packets_remaining <= 0:
                        state = 'processing'
                    else:
                        state = 'sizing'
                elif len(buffer) == 0:
                    xbmc.log("KodiCloudLink disconnecting gracefully", level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.shutdown(socket.SHUT_RDWR)
                    conn.close()
                    conn = None
                else:
                    xbmc.log("KodiCloudLink disconnecting due to error in message", level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.close()
                    conn = None
            except socket.error as msg:
                if msg[0] == errno.EAGAIN:
                    monitor.waitForAbort(IDLE_SECONDS)
                else:
                    xbmc.log("KodiCloudLink exception: %s, disconnecting" % str(msg), level=xbmc.LOGNOTICE)
                    state = 'disconnected'
                    conn.close()
                    conn = None

        if state == 'processing':
            try:
                response = xbmc.executeJSONRPC(data)
                xbmc.log("KodiCloudLink sending %s" % response, level=xbmc.LOGNOTICE)
                conn.send(struct.pack('>l', 1))  # TODO packetize
                conn.send(struct.pack('>l', len(response)))
                conn.send(response.encode('utf-8'))
            except socket.error as msg:
                xbmc.log("KodiCloudLink exception: %s, disconnecting" % str(msg), level=xbmc.LOGNOTICE)
                state = 'disconnected'
                conn.close()
                conn = None
            data = b''
            state = 'idle'

    # conn.shutdown(socket.SHUT_RDWR)
    conn.close()
