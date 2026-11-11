"""Tiny OpenRISC (AX329x, no delay slots) helper programs for the boot-ROM loader.

They are copied into the loader's scratch SRAM (0x4800..0x4a00) and run as the
"callback" of the ROM's own memory-read routine (0x102620): the ROM calls
callback(r3 = buffer address, r4 = length, r5 = CDB bytes 13..15 + one more
byte), then sends `length` bytes from the buffer to the PC.

Both programs use ONLY the ROM's own SPI building blocks (same ROM, verified
byte-for-byte on the tested camera):
  0x104898  chip-select low      0x1048c8  chip-select high
  0x104808  send mode            0x104838  receive mode
  0x10485c  exchange one byte (r3 out, r11 in)
and can only put two flash commands on the wire:
  JEDEC_STUB  0x9F            (read the chip's ID, 3 bytes)
  READ_STUB   0x03 + address  (normal read)
Anything outside the expected buffer / length makes them return untouched.
"""
import struct

LOAD = 0x4800            # stub area
JEDEC_AT = 0x4800
READ_AT = 0x4900
BUF = 0x4a00             # 256-byte data buffer (0x4a00..0x4b00, inside the free 0x4800..0x4c00 area)
BUF_LEN = 256

CS_LOW, CS_HIGH = 0x104898, 0x1048c8
MODE_SEND, MODE_RECV = 0x104808, 0x104838
XFER = 0x10485c


class Asm:
    def __init__(self, base):
        self.base, self.words, self.labels, self.fix = base, [], {}, []

    @property
    def pc(self):
        return self.base + 4 * len(self.words)

    def label(self, name):
        self.labels[name] = self.pc

    def w(self, x):
        self.words.append(x & 0xffffffff)

    # --- instructions used here ---
    def addi(self, d, a, i): self.w(0x27 << 26 | d << 21 | a << 16 | (i & 0xffff))
    def ori(self, d, a, i): self.w(0x2a << 26 | d << 21 | a << 16 | (i & 0xffff))
    def andi(self, d, a, i): self.w(0x29 << 26 | d << 21 | a << 16 | (i & 0xffff))
    def movhi(self, d, i): self.w(0x06 << 26 | d << 21 | (i & 0xffff))
    def srli(self, d, a, n): self.w(0x2e << 26 | d << 21 | a << 16 | 1 << 6 | n)
    def and_(self, d, a, b): self.w(0x38 << 26 | d << 21 | a << 16 | b << 11 | 0x3)
    def sw(self, off, a, b): self.w(0x35 << 26 | ((off >> 11) & 0x1f) << 21 | a << 16 | b << 11 | (off & 0x7ff))
    def lwz(self, d, off, a): self.w(0x21 << 26 | d << 21 | a << 16 | (off & 0xffff))
    def sb(self, off, a, b): self.w(0x36 << 26 | ((off >> 11) & 0x1f) << 21 | a << 16 | b << 11 | (off & 0x7ff))
    def sfeqi(self, a, i): self.w(0x2f << 26 | 0x0 << 21 | a << 16 | (i & 0xffff))
    def sfnei(self, a, i): self.w(0x2f << 26 | 0x1 << 21 | a << 16 | (i & 0xffff))
    def sfgtui(self, a, i): self.w(0x2f << 26 | 0x2 << 21 | a << 16 | (i & 0xffff))
    def jr(self, b): self.w(0x11 << 26 | b << 11)

    def _branch(self, op, target):
        if isinstance(target, str):
            self.fix.append((len(self.words), op, target))
            self.w(op << 26)
        else:
            self.w(op << 26 | (((target - self.pc) >> 2) & 0x3ffffff))

    def j(self, t): self._branch(0x00, t)
    def jal(self, t): self._branch(0x01, t)
    def bnf(self, t): self._branch(0x03, t)
    def bf(self, t): self._branch(0x04, t)

    def done(self):
        for idx, op, name in self.fix:
            pc = self.base + 4 * idx
            self.words[idx] = op << 26 | (((self.labels[name] - pc) >> 2) & 0x3ffffff)
        return b''.join(struct.pack('<I', w) for w in self.words)


def _prologue(a):
    a.addi(1, 1, -24)
    a.sw(0, 1, 9)
    a.sw(4, 1, 2)
    a.sw(8, 1, 14)
    a.sw(12, 1, 16)
    a.sw(16, 1, 18)


def _epilogue(a):
    a.label(f'out{a.base:x}')
    a.lwz(9, 0, 1)
    a.lwz(2, 4, 1)
    a.lwz(14, 8, 1)
    a.lwz(16, 12, 1)
    a.lwz(18, 16, 1)
    a.addi(1, 1, 24)
    a.jr(9)


def _guard(a, max_len):
    """Return untouched unless r3 == BUF and 1 <= r4 <= max_len."""
    a.movhi(18, BUF >> 16)
    a.ori(18, 18, BUF & 0xffff)
    a.w(0x39 << 26 | 0x1 << 21 | 3 << 16 | 18 << 11)          # l.sfne r3,r18
    a.bf(f'out{a.base:x}')
    a.sfeqi(4, 0)
    a.bf(f'out{a.base:x}')
    a.sfgtui(4, max_len)
    a.bf(f'out{a.base:x}')


def jedec_stub():
    a = Asm(JEDEC_AT)
    _prologue(a)
    _guard(a, 3)
    a.ori(14, 3, 0)                       # dst
    a.ori(16, 4, 0)                       # count
    a.jal(CS_LOW)
    a.jal(MODE_SEND)
    a.addi(3, 0, 0x9F)
    a.jal(XFER)
    a.jal(MODE_RECV)
    a.label('loopj')
    a.sfeqi(16, 0)
    a.bf('endj')
    a.addi(3, 0, 0xFF)
    a.jal(XFER)
    a.sb(0, 14, 11)
    a.addi(14, 14, 1)
    a.addi(16, 16, -1)
    a.j('loopj')
    a.label('endj')
    a.jal(CS_HIGH)
    _epilogue(a)
    return a.done()


def read_stub():
    a = Asm(READ_AT)
    _prologue(a)
    _guard(a, BUF_LEN)
    a.ori(14, 3, 0)                       # dst
    a.ori(16, 4, 0)                       # count
    a.movhi(18, 0x00ff)                   # r18 = r5 & 0x00ffffff  (flash address)
    a.ori(18, 18, 0xffff)
    a.and_(18, 5, 18)
    a.jal(CS_LOW)
    a.jal(MODE_SEND)
    a.addi(3, 0, 0x03)
    a.jal(XFER)
    a.srli(3, 18, 16)
    a.andi(3, 3, 0xff)
    a.jal(XFER)
    a.srli(3, 18, 8)
    a.andi(3, 3, 0xff)
    a.jal(XFER)
    a.andi(3, 18, 0xff)
    a.jal(XFER)
    a.jal(MODE_RECV)
    a.label('loopr')
    a.sfeqi(16, 0)
    a.bf('endr')
    a.addi(3, 0, 0xFF)
    a.jal(XFER)
    a.sb(0, 14, 11)
    a.addi(14, 14, 1)
    a.addi(16, 16, -1)
    a.j('loopr')
    a.label('endr')
    a.jal(CS_HIGH)
    _epilogue(a)
    return a.done()


def image():
    """Bytes to upload at LOAD (0x4800): JEDEC stub, padding, READ stub at 0x4900."""
    j, r = jedec_stub(), read_stub()
    assert len(j) <= READ_AT - JEDEC_AT and READ_AT + len(r) <= BUF
    return j + b'\0' * (READ_AT - JEDEC_AT - len(j)) + r


if __name__ == '__main__':
    img = image()
    print(len(img), 'bytes')
    print(img.hex())
