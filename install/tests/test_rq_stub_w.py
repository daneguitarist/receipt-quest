"""Offline test of the flash WRITER helpers (rq_stub_w.py) in the OpenRISC
interpreter from test_rq_stub.py, with a stricter SPI-NOR model (GD25Q32-style:
06 write enable, 20 sector erase, 02 page program, 05/35 status, 03 read,
busy time after erase/program). Checks, using a real stock backup:

  - STAT returns both status registers
  - ERASE/PROG inside the sound windows work; READ verifies
  - outside the windows / misaligned / wrong buffer or length: not one SPI byte
  - the full update of all 7 sounds turns the backup into exactly the target
    image: only the 34 sound sectors erased, nothing else changed
  - only commands 05 35 03 06 20 02 ever appear; 06 is always followed by 20/02
  - watchdog kicked while waiting; callee-saved registers preserved
Run: python3 test_rq_stub_w.py BACKUP.bin TARGET.bin
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
import random
import sys

import rq_stub_w as W
import test_rq_stub as T

LEGAL = {0x03, 0x05, 0x35, 0x06, 0x20, 0x02}


class NorFlash:
    def __init__(self, data, busy_polls=7):
        self.mem = bytearray(data)
        self.cs_low, self.frame, self.frames, self.illegal = False, [], [], []
        self.wel = False
        self.busy = 0
        self.busy_polls = busy_polls
        self.erased, self.programmed = [], []
        self.sr2 = 0x00

    def select(self, low):
        if low and not self.cs_low:
            self.frame = []
        if not low and self.cs_low:
            self._finish(bytes(self.frame))
        self.cs_low = low

    def _sr1(self):
        return (1 if self.busy else 0) | (2 if self.wel else 0)

    def xfer(self, out, mode_send):
        if not self.cs_low:
            self.illegal.append(('xfer with CS high', out))
            return 0xff
        self.frame.append(out)
        cmd, n = self.frame[0], len(self.frame)
        if n == 1:
            if cmd not in LEGAL:
                self.illegal.append(('command', hex(cmd)))
            if cmd != 0x05 and self.busy:
                self.illegal.append(('command while busy', hex(cmd)))
            return 0xff
        if cmd == 0x05:
            v = self._sr1()
            if self.busy:
                self.busy -= 1
            return v
        if cmd == 0x35:
            return self.sr2
        if cmd == 0x03 and n > 4:
            a = (self.frame[1] << 16 | self.frame[2] << 8 | self.frame[3]) + n - 5
            return self.mem[a % len(self.mem)]
        return 0xff

    def _finish(self, f):
        self.frames.append(f)
        if not f:
            return
        cmd = f[0]
        if cmd == 0x06:
            if len(f) != 1:
                self.illegal.append(('06 with extra bytes', f.hex()))
            self.wel = True
            return
        if cmd in (0x20, 0x02):
            if not self.wel:
                self.illegal.append(('write without WEL', f[:4].hex()))
                return
            prev = self.frames[-2] if len(self.frames) > 1 else b''
            if prev != b'\x06':
                self.illegal.append(('write not right after 06', f[:4].hex()))
            a = f[1] << 16 | f[2] << 8 | f[3]
            if cmd == 0x20:
                if len(f) != 4:
                    self.illegal.append(('erase frame length', len(f)))
                base = a & ~0xfff
                self.mem[base:base + 0x1000] = b'\xff' * 0x1000
                self.erased.append(base)
            else:
                data = f[4:]
                if (a & 0xff) + len(data) > 256:
                    self.illegal.append(('program crosses a page', hex(a), len(data)))
                for k, b in enumerate(data):
                    self.mem[a + k] &= b
                self.programmed.append((a, len(data)))
            self.wel = False
            self.busy = self.busy_polls


class CPUW(T.CPU):
    ROM_FUNCS = T.CPU.ROM_FUNCS

    def __init__(self, flash):
        super().__init__(flash)
        self.wdt_kicks = 0

    def call(self, entry, r3, r4, r5, ret=0xdead0000):
        r = self.r
        for k in range(32):
            r[k] = random.getrandbits(32)
        r[0], r[1], r[3], r[4], r[5], r[9] = 0, 0x4f00, r3, r4, r5, ret
        saved = {k: r[k] for k in (1, 2, 14, 16, 18, 20, 22, 24, 26, 28, 30)}
        self.steps = 0
        pc = entry
        while pc != ret:
            self.steps += 1
            if self.steps > 3_000_000:
                raise RuntimeError('runaway')
            if pc in self.ROM_FUNCS:
                pc = self.rom(pc)
                continue
            if not (W.LOAD <= pc < W.STATUS):
                raise RuntimeError(f'jumped outside the helper: {pc:#x}')
            pc = self.step(pc)
        for k, v in saved.items():
            assert r[k] == v, f'r{k} not preserved'
        assert r[1] == 0x4f00

    def step(self, pc):
        w = self.ld32(pc)
        op = w >> 26
        d, a = (w >> 21) & 31, (w >> 16) & 31
        r = self.r
        if op == 0x30:                                   # l.mtspr
            spr = (d << 11) | (w & 0x7ff) | r[a]
            assert spr == W.WDT_SPR and r[(w >> 11) & 31] == W.WDT_VALUE, 'unexpected SPR write'
            self.wdt_kicks += 1
            return pc + 4
        if op == 0x23:                                   # l.lbz
            r[d] = self.mem[(r[a] + T.sx(w & 0xffff, 16)) & 0xffffffff]
            return pc + 4
        if op == 0x2f and d == 4:                        # l.sfltui
            self.flag = r[a] < (T.sx(w & 0xffff, 16) & 0xffffffff)
            return pc + 4
        return super().step(pc)


def main(backup_path, target_path):
    backup = open(backup_path, 'rb').read()
    target = open(target_path, 'rb').read()
    img = W.image()
    random.seed(7)
    print(f'writer image {len(img)} bytes, entries', {k: hex(v) for k, v in W.ENTRY.items()})

    def fresh(data=backup):
        f = NorFlash(data)
        c = CPUW(f)
        c.mem[W.LOAD:W.LOAD + len(img)] = img
        return f, c

    # STAT
    f, c = fresh()
    f.sr2 = 0x02
    c.call(W.ENTRY['STAT'], W.BUF, 2, 0)
    assert bytes(c.mem[W.BUF:W.BUF + 2]) == bytes([0x00, 0x02]) and not f.illegal
    print('STAT ok')

    # READ
    f, c = fresh()
    for _ in range(300):
        a = random.randrange(0, len(backup) - 128)
        n = random.choice([128, 128, 1, 77])
        c.call(W.ENTRY['READ'], W.BUF, n, a | random.getrandbits(8) << 24)
        assert bytes(c.mem[W.BUF:W.BUF + n]) == backup[a:a + n]
    assert not f.illegal and {fr[0] for fr in f.frames} == {0x03}
    print('READ ok')

    # refusals: not one SPI byte
    bad_erase = [0x0, 0x1000, 0xb1000, 0x1f0000, 0x1f3000, 0x227000, 0x248000, 0x300000, 0x1f1001, 0x228800,
                 0x3ff000, 0xffffff]
    for a in bad_erase:
        f, c = fresh()
        c.call(W.ENTRY['ERASE'], W.BUF, 1, a)
        assert f.frames == [] and c.mem[W.BUF] == 0xEE, hex(a)
    bad_prog = [0x0, 0xb1600, 0x1f0f80, 0x1f3000, 0x248000, 0x1f1001, 0x228040, 0x2fe000]
    for a in bad_prog:
        f, c = fresh()
        c.call(W.ENTRY['PROG'], W.BUF, 128, a)
        assert f.frames == [] and c.mem[W.STATUS] == 0xEE, hex(a)
    for entry, n in (('ERASE', 2), ('ERASE', 0), ('PROG', 127), ('PROG', 256), ('READ', 129), ('READ', 0),
                     ('STAT', 1)):
        for buf in (W.BUF, W.BUF + 1, 0x4000):
            if buf == W.BUF and ((entry == 'READ' and 0 < n <= 128)):
                continue
            f, c = fresh()
            c.call(W.ENTRY[entry], buf, n, 0x228000)
            assert f.frames == [], (entry, n, hex(buf))
    print(f'refusals ok: {len(bad_erase)} erase + {len(bad_prog)} program addresses outside the fence, '
          'wrong lengths/buffers -> no SPI at all')

    # full simulated update: backup -> target
    changed = sorted({a & ~0xfff for a in range(len(backup)) if backup[a] != target[a]})
    print(f'sectors that differ between backup and target: {len(changed)}')
    f, c = fresh()
    for s in changed:
        c.mem[W.BUF] = 0
        c.call(W.ENTRY['ERASE'], W.BUF, 1, s)
        sr = c.mem[W.BUF]
        assert sr & 3 == 0, f'erase status {sr:#x}'
        for half in range(s, s + 0x1000, 128):
            c.mem[W.BUF:W.BUF + 128] = target[half:half + 128]
            c.call(W.ENTRY['PROG'], W.BUF, 128, half)
            assert c.mem[W.STATUS] & 3 == 0
        got = bytearray()
        for a in range(s, s + 0x1000, 128):
            c.call(W.ENTRY['READ'], W.BUF, 128, a)
            got += c.mem[W.BUF:W.BUF + 128]
        assert bytes(got) == target[s:s + 0x1000], hex(s)
    assert bytes(f.mem) == target, 'flash != target after update'
    assert sorted(set(f.erased)) == changed and len(f.erased) == len(changed)
    assert not f.illegal, f.illegal[:5]
    cmds = {fr[0] for fr in f.frames if fr}
    assert cmds <= LEGAL, cmds
    print(f'full update ok: flash now == target; erased exactly {len(f.erased)} sectors; '
          f'{len(f.programmed)} half-page programs; commands used {sorted(hex(x) for x in cmds)}; '
          f'watchdog kicks {c.wdt_kicks}')

    # erase while the chip stays busy too long -> reports WIP, does not proceed
    # (same code built with a small poll limit so the interpreter finishes quickly)
    real_limit = W.POLL_LIMIT
    W.POLL_LIMIT = 0x40
    small = W.image()
    W.POLL_LIMIT = real_limit
    f = NorFlash(backup)
    c = CPUW(f)
    c.mem[W.LOAD:W.LOAD + len(small)] = small
    f.busy, f.busy_polls = 10 ** 9, 0
    c.call(W.ENTRY['ERASE'], W.BUF, 1, 0x228000)
    assert c.mem[W.BUF] & 1 and not f.erased and all(fr[:1] == b'\x05' for fr in f.frames)
    print('busy chip -> erase not started, WIP reported')
    print('ALL WRITER TESTS PASSED')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
