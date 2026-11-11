"""Offline test of rq_stub.py: runs the stubs in a small OpenRISC interpreter
(no delay slots) with the ROM's SPI building blocks modelled, against a real
SPI-NOR flash image (the sister MK1 camera's dump). Checks:
  - JEDEC stub sends exactly [9F] then 3 dummy bytes, reads the ID, CS framed
  - READ stub sends exactly [03 A2 A1 A0] + n dummy bytes, returns flash[A:A+n]
  - nothing else ever reaches the flash (no 06/20/D8/C7/02...), CS ends high
  - registers the ROM relies on (r1, r2, r14-r30, r9 return) are preserved
  - bad buffer/length => no SPI activity at all
Run: python3 test_rq_stub.py FLASH.bin
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
import random
import struct
import sys

import rq_stub as S


def sx(v, b):
    return v - (1 << b) if v >> (b - 1) & 1 else v


class Flash:
    """SPI-NOR model: only READ (03) and JEDEC (9F) are legal here."""
    def __init__(self, data, jedec=(0x5e, 0x40, 0x16)):
        self.data, self.jedec = data, jedec
        self.cs_low, self.bytes, self.log, self.illegal = False, [], [], []

    def select(self, low):
        if low and not self.cs_low:
            self.bytes = []
        if not low and self.cs_low:
            self.log.append(bytes(self.bytes))
        self.cs_low = low

    def xfer(self, out, mode_send):
        if not self.cs_low:
            self.illegal.append(('xfer with CS high', out))
            return 0xff
        self.bytes.append(out)
        cmd = self.bytes[0]
        n = len(self.bytes)
        if n == 1:
            if cmd not in (0x03, 0x9F):
                self.illegal.append(('command', cmd))
            return 0xff
        if cmd == 0x9F:
            return self.jedec[n - 2] if n - 2 < 3 else 0xff
        if cmd == 0x03:
            if n <= 4:
                return 0xff
            addr = (self.bytes[1] << 16 | self.bytes[2] << 8 | self.bytes[3]) + (n - 5)
            return self.data[addr % len(self.data)]
        return 0xff


class CPU:
    ROM_FUNCS = {S.CS_LOW, S.CS_HIGH, S.MODE_SEND, S.MODE_RECV, S.XFER}

    def __init__(self, flash):
        self.r = [0] * 32
        self.mem = bytearray(0x10000)       # SRAM model 0x0000..0xffff
        self.flash = flash
        self.flag = False
        self.mode_send = None
        self.steps = 0

    def ld32(self, a): return struct.unpack_from('<I', self.mem, a)[0]
    def st32(self, a, v): struct.pack_into('<I', self.mem, a, v & 0xffffffff)

    def rom(self, pc):
        r = self.r
        if pc == S.CS_LOW:
            self.flash.select(True)
        elif pc == S.CS_HIGH:
            self.flash.select(False)
        elif pc == S.MODE_SEND:
            self.mode_send = True
        elif pc == S.MODE_RECV:
            self.mode_send = False
        elif pc == S.XFER:
            r[11] = self.flash.xfer(r[3] & 0xff, self.mode_send)
        # ROM functions clobber caller-saved registers
        for k in (3, 4, 5, 6, 7, 8, 12, 13):
            r[k] = random.getrandbits(32)
        if pc != S.XFER:
            r[11] = random.getrandbits(32)
        return r[9]

    def call(self, entry, r3, r4, r5, ret=0xdead0000):
        r = self.r
        for k in range(32):
            r[k] = random.getrandbits(32)
        r[0] = 0
        r[1] = 0x4f00                         # stack like the ROM's (~0x4f14)
        r[3], r[4], r[5], r[9] = r3, r4, r5, ret
        saved = {k: r[k] for k in (1, 2, 14, 16, 18, 20, 22, 24, 26, 28, 30)}
        self.steps = 0
        pc = entry
        while pc != ret:
            self.steps += 1
            if self.steps > 100_000:
                raise RuntimeError('runaway')
            if pc in self.ROM_FUNCS:
                pc = self.rom(pc)
                continue
            if not (S.LOAD <= pc < S.BUF):
                raise RuntimeError(f'jumped outside the stub/ROM functions: {pc:#x}')
            pc = self.step(pc)
        for k, v in saved.items():
            assert r[k] == v, f'r{k} not preserved'

    def step(self, pc):
        r = self.r
        w = self.ld32(pc)
        op = w >> 26
        d, a, b, i = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, w & 0xffff
        nxt = pc + 4
        if op in (0x00, 0x01, 0x03, 0x04):
            tgt = (pc + sx(w & 0x3ffffff, 26) * 4) & 0xffffffff
            if op == 0x01:
                r[9] = nxt
                return tgt
            if op == 0x00 or (op == 0x04 and self.flag) or (op == 0x03 and not self.flag):
                return tgt
            return nxt
        if op == 0x11:
            return r[b]
        if op == 0x06:
            r[d] = (i << 16) & 0xffffffff
        elif op == 0x27:
            r[d] = (r[a] + sx(i, 16)) & 0xffffffff
        elif op == 0x2a:
            r[d] = r[a] | i
        elif op == 0x29:
            r[d] = r[a] & i
        elif op == 0x2e:
            assert (w >> 6) & 3 == 1, 'only srli'
            r[d] = r[a] >> (w & 63)
        elif op == 0x38:
            assert w & 0x3cf == 0x3, 'only l.and'
            r[d] = r[a] & r[b]
        elif op == 0x35:
            self.st32((r[a] + sx(((w >> 21) & 31) << 11 | (w & 0x7ff), 16)) & 0xffffffff, r[b])
        elif op == 0x36:
            self.mem[(r[a] + sx(((w >> 21) & 31) << 11 | (w & 0x7ff), 16)) & 0xffffffff] = r[b] & 0xff
        elif op == 0x21:
            r[d] = self.ld32((r[a] + sx(i, 16)) & 0xffffffff)
        elif op == 0x2f:
            v = r[a]
            self.flag = {0: v == (sx(i, 16) & 0xffffffff), 1: v != (sx(i, 16) & 0xffffffff),
                         2: v > (sx(i, 16) & 0xffffffff)}[d]
        elif op == 0x39:
            self.flag = {0: r[a] == r[b], 1: r[a] != r[b]}[d]
        else:
            raise RuntimeError(f'unhandled instruction {w:#010x} at {pc:#x}')
        r[0] = 0
        return nxt


def main(path):
    flash_img = open(path, 'rb').read()
    img = S.image()
    print(f'stub image: {len(img)} bytes')
    random.seed(1)

    def fresh():
        f = Flash(flash_img)
        c = CPU(f)
        c.mem[S.LOAD:S.LOAD + len(img)] = img
        return f, c

    # JEDEC
    f, c = fresh()
    c.call(S.JEDEC_AT, S.BUF, 3, random.getrandbits(32))
    assert f.log == [bytes([0x9F, 0xff, 0xff, 0xff])], f.log
    assert bytes(c.mem[S.BUF:S.BUF + 3]) == bytes(f.jedec)
    assert not f.illegal and not f.cs_low
    print('JEDEC stub ok:', f.log[0].hex())

    # READ at many addresses incl. top byte garbage in r5
    f, c = fresh()
    total = 0
    for k in range(400):
        addr = random.randrange(0, len(flash_img) - 256) if k else 0
        n = random.choice([256, 256, 256, 1, 17, 255])
        r5 = addr | random.getrandbits(8) << 24
        c.mem[S.BUF:S.BUF + 256] = b'\xaa' * 256
        c.call(S.READ_AT, S.BUF, n, r5)
        assert bytes(c.mem[S.BUF:S.BUF + n]) == flash_img[addr:addr + n], hex(addr)
        assert bytes(c.mem[S.BUF + n:S.BUF + 256]) == b'\xaa' * (256 - n), 'wrote past length'
        frame = f.log[-1]
        assert frame[:4] == bytes([0x03, addr >> 16 & 0xff, addr >> 8 & 0xff, addr & 0xff])
        assert frame[4:] == b'\xff' * n and len(frame) == 4 + n
        total += n
    assert not f.illegal and not f.cs_low and len(f.log) == 400
    print(f'READ stub ok: 400 reads, {total} bytes match the flash image, only 03 frames on the wire')

    # full 4 MiB pass like the real backup
    f, c = fresh()
    out = bytearray()
    for addr in range(0, len(flash_img), 256):
        c.call(S.READ_AT, S.BUF, 256, addr)
        out += c.mem[S.BUF:S.BUF + 256]
    assert bytes(out) == flash_img and not f.illegal
    print(f'full pass ok: {len(out)} bytes identical, {len(f.log)} SPI frames, all READ')

    # guards: wrong buffer / zero / too long => no SPI at all
    for args in ((S.BUF + 4, 16, 0), (0x4000, 256, 0), (S.BUF, 0, 0), (S.BUF, 257, 0), (S.BUF, 0x10000, 0)):
        f, c = fresh()
        c.call(S.READ_AT, *args)
        c.call(S.JEDEC_AT, args[0], args[1] if args[1] != 3 else 4, 0)
        assert f.log == [] and not f.illegal and not f.cs_low, args
    f, c = fresh()
    c.call(S.JEDEC_AT, S.BUF, 4, 0)
    assert f.log == []
    print('guards ok: bad buffer/length -> no SPI activity')
    print('ALL TESTS PASSED')


if __name__ == '__main__':
    main(sys.argv[1])
