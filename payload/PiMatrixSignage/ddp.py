from __future__ import annotations

import socket
import struct


class DDPSender:
    """Small DDP v1 RGB888 sender compatible with FPP bridge input."""

    VER1 = 0x40
    PUSH = 0x01
    DATATYPE_RGB888 = 0x0B
    DESTINATION_ID = 1
    MAX_DATALEN = 1440  # 480 RGB pixels, fits a normal Ethernet UDP payload comfortably

    def __init__(self, host: str = "127.0.0.1", port: int = 4048, offset: int = 0):
        self.host = host
        self.port = int(port)
        self.offset = int(offset)
        self.frame_count = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def update_target(self, host: str, port: int, offset: int = 0):
        self.host = host
        self.port = int(port)
        self.offset = int(offset)

    def send(self, rgb_bytes: bytes):
        self.frame_count += 1
        sequence = self.frame_count % 15 + 1
        total = len(rgb_bytes)
        if total == 0:
            return
        packet_count = (total + self.MAX_DATALEN - 1) // self.MAX_DATALEN
        for i in range(packet_count):
            start = i * self.MAX_DATALEN
            chunk = rgb_bytes[start : start + self.MAX_DATALEN]
            last = i == packet_count - 1
            flags = self.VER1 | (self.PUSH if last else 0)
            header = struct.pack(
                "!BBBBLH",
                flags,
                sequence,
                self.DATATYPE_RGB888,
                self.DESTINATION_ID,
                self.offset + start,
                len(chunk),
            )
            self.sock.sendto(header + chunk, (self.host, self.port))

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
