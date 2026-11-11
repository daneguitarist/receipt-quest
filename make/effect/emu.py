"""Strict OpenRISC (no delay slots, like the AX3291A) emulator for testing the
Receipt Quest hook + loader stub + effect on the real firmware bytes.

- the patched application image is mapped at 0x02000000, executable
- the camera's helpers the stub calls (flash read, malloc, free, cache) are
  Python hooks that behave like the stock ones (DMA reads round up to 16 bytes)
  and clobber caller-saved registers, so ABI mistakes show up
- every load/store must hit: the stack window, a live heap block, the print
  buffer, or the stub's own cave; anything else is an error
- only instructions the stock firmware itself uses are allowed (no l.muli,
  no l.cmov / l.ext / l.ror / l.ff1 ...)
"""
import random
import struct

BIAS = 0x01ffda00
APP = 0x02000000


def sx(v, b):
    return v - (1 << b) if v >> (b - 1) else v


class EmuError(Exception):
    pass


class Heap:
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi
        self.next = lo
        self.blocks = {}          # addr -> size
        self.freed = []
        self.peak = 0

    def alloc(self, size, align):
        align = max(align, 4)
        a = (self.next + 16 + align - 1) & ~(align - 1)    # 16-byte gap = guard
        if a + size > self.hi:
            return 0
        self.blocks[a] = size
        self.next = a + size
        self.peak = max(self.peak, sum(self.blocks.values()))
        return a

    def free(self, a):
        if a not in self.blocks:
            raise EmuError(f'free of {a:#x} which is not a live block')
        self.freed.append((a, self.blocks.pop(a)))

    def find(self, a, n):
        for b, s in self.blocks.items():
            if b <= a and a + n <= b + s:
                return True
        return False


class Emu:
    def __init__(self, app_image, flash, buf_addr, buf, stack_top=0x027f0000, stack_size=0x4000,
                 cave=(0x02015a00, 0x0201657c), seed=1, ram_hooks=((0x0205eefc, 4),)):
        self.mem = {}                         # page -> bytearray(4096)
        self.app_lo, self.app_hi = APP, APP + len(app_image)
        self._load(APP, app_image)
        self.flash = flash
        self.buf_lo, self.buf_hi = buf_addr, buf_addr + len(buf)
        self._load(buf_addr, buf)
        self.stack_lo, self.stack_hi = stack_top - stack_size, stack_top
        self.cave = cave
        self.ram_hooks = ram_hooks          # app words the stub may patch in RAM
        self.ram_writes = []
        self.heap = Heap(0x02400000, 0x02700000)
        self.r = [0] * 32
        self.pc = 0
        self.f = False
        self.steps = 0
        self.calls = []
        self.rng = random.Random(seed)
        self.min_sp = stack_top
        self.code_ok = set()                  # pages we allow executing: app + heap blocks
        self.hooks = {
            0x020404f0: self.h_flash_read,
            0x0204195c: self.h_malloc,
            0x0204179c: self.h_free,
            0x0202da34: self.h_dflush,
            0x0202d9f0: self.h_iinv,
        }
        self.decoded = {}

    # ------------------------------------------------------------ memory
    def _page(self, a):
        p = self.mem.get(a >> 12)
        if p is None:
            p = self.mem[a >> 12] = bytearray(4096)
        return p

    def _load(self, a, data):
        for i in range(0, len(data)):
            self._page(a + i)[(a + i) & 0xfff] = data[i]

    def read_bytes(self, a, n):
        return bytes(self._page(a + i)[(a + i) & 0xfff] for i in range(n))

    def write_bytes(self, a, data):
        self._load(a, data)
        for k in [k for k in self.decoded if a <= k < a + len(data)]:
            del self.decoded[k]

    def check(self, a, n, write):
        if a % n:
            raise EmuError(f'misaligned {n}-byte access at {a:#x} pc={self.pc:#x}')
        if self.stack_lo <= a and a + n <= self.stack_hi:
            return
        if self.buf_lo <= a and a + n <= self.buf_hi:
            return
        if self.cave[0] <= a and a + n <= self.cave[1]:
            return
        if self.heap.find(a, n):
            return
        if any(lo <= a and a + n <= lo + ln for lo, ln in self.ram_hooks):
            if write:
                self.ram_writes.append((a, self.steps))
            return
        raise EmuError(f'{"write" if write else "read"} of {n} bytes at {a:#x} outside allowed memory, pc={self.pc:#x}')

    def ld(self, a, n, signed=False):
        self.check(a, n, False)
        p = self._page(a)
        o = a & 0xfff
        v = int.from_bytes(p[o:o + n], 'little')
        if signed and v >> (8 * n - 1):
            v -= 1 << (8 * n)
        return v & 0xffffffff

    def st(self, a, n, v):
        self.check(a, n, True)
        p = self._page(a)
        o = a & 0xfff
        p[o:o + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, 'little')
        if a in self.decoded or (a & ~3) in self.decoded:
            self.decoded.pop(a & ~3, None)

    # ------------------------------------------------------------ hooks (stock helpers)
    def _ret(self, v=None):
        if v is not None:
            self.r[11] = v & 0xffffffff
        for k in (3, 4, 5, 6, 7, 8, 12, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31):
            self.r[k] = self.rng.getrandbits(32)
        if v is None:
            self.r[11] = self.rng.getrandbits(32)
        self.pc = self.r[9]

    def h_flash_read(self):
        fa, dst, n = self.r[3], self.r[4], self.r[5]
        self.calls.append(('flash_read', fa, dst, n))
        if fa + n > len(self.flash):
            raise EmuError('flash read past the end')
        m = n if n <= 15 else (n + 15) & ~15          # the DMA path rounds up to 16
        if n > 15 and dst % 4:
            raise EmuError('DMA read to unaligned buffer')
        if n > 15 and (dst % 16 or m % 16):
            # the stock DMA path invalidates whole 16-byte cache lines: anything else sharing them would be lost
            raise EmuError(f'DMA read to {dst:#x}+{m} shares cache lines with other data')
        for i in range(m):
            self.check(dst + i, 1, True)
        data = self.flash[fa:fa + m] + b'\xff' * max(0, fa + m - len(self.flash))
        self.write_bytes(dst, data)
        self._ret(0)

    def h_malloc(self):
        size, align = self.r[3], self.r[4]
        a = self.heap.alloc(size, align)
        self.calls.append(('malloc', size, align, a))
        self._ret(a)

    def h_free(self):
        self.calls.append(('free', self.r[3]))
        self.heap.free(self.r[3])
        self._ret(0)

    def h_dflush(self):
        self.calls.append(('dflush', self.r[3], self.r[4]))
        self._ret(0)

    def h_iinv(self):
        self.calls.append(('iinv',))
        self.decoded.clear()
        self._ret(0)

    # ------------------------------------------------------------ cpu
    def fetch(self, pc):
        if pc % 4:
            raise EmuError(f'misaligned pc {pc:#x}')
        ok = (self.app_lo <= pc < self.app_hi) or self.heap.find(pc, 4)
        if not ok:
            raise EmuError(f'executing outside code: pc={pc:#x}')
        p = self._page(pc)
        return int.from_bytes(p[pc & 0xfff:(pc & 0xfff) + 4], 'little')

    def step(self):
        pc = self.pc
        if pc in self.hooks:
            self.hooks[pc]()
            return
        w = self.fetch(pc)
        op = w >> 26
        d, a, b = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
        r = self.r
        imm = w & 0xffff
        simm = sx(imm, 16)
        npc = pc + 4
        if op in (0, 1):                        # l.j / l.jal
            t = (pc + sx(w & 0x3ffffff, 26) * 4) & 0xffffffff
            if op == 1:
                r[9] = npc
            npc = t
        elif op in (3, 4):                      # l.bnf / l.bf
            if self.f == (op == 4):
                npc = (pc + sx(w & 0x3ffffff, 26) * 4) & 0xffffffff
        elif op == 5:
            pass                                # l.nop
        elif op == 6:
            if w & 0x10000:
                raise EmuError(f'l.macrc at {pc:#x}')
            r[d] = (imm << 16)
        elif op in (0x11, 0x12):                # l.jr / l.jalr
            t = r[b]
            if op == 0x12:
                r[9] = npc
            npc = t
        elif op in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26):
            ea = (r[a] + simm) & 0xffffffff
            n = {0x21: 4, 0x22: 4, 0x23: 1, 0x24: 1, 0x25: 2, 0x26: 2}[op]
            r[d] = self.ld(ea, n, signed=op in (0x22, 0x24, 0x26))
        elif op == 0x27:
            r[d] = (r[a] + simm) & 0xffffffff
        elif op == 0x29:
            r[d] = r[a] & imm
        elif op == 0x2a:
            r[d] = r[a] | imm
        elif op == 0x2b:
            r[d] = (r[a] ^ simm) & 0xffffffff
        elif op == 0x2e:                        # shift immediate
            t, sh = (w >> 6) & 3, w & 31
            v = r[a]
            if t == 0:
                r[d] = (v << sh) & 0xffffffff
            elif t == 1:
                r[d] = v >> sh
            elif t == 2:
                r[d] = (sx(v, 32) >> sh) & 0xffffffff
            else:
                raise EmuError(f'l.rori at {pc:#x}')
        elif op == 0x2f:                        # l.sf*i
            self.f = self.cmp((w >> 21) & 31, r[a], simm & 0xffffffff, pc)
        elif op in (0x35, 0x36, 0x37):          # stores (split immediate)
            si = sx(((w >> 21) & 31) << 11 | (w & 0x7ff), 16)
            ea = (r[a] + si) & 0xffffffff
            n = {0x35: 4, 0x36: 1, 0x37: 2}[op]
            self.st(ea, n, r[b])
        elif op == 0x38:
            sub = w & 0x3cf
            ra, rb = r[a], r[b]
            if sub == 0:
                v = ra + rb
            elif sub == 2:
                v = ra - rb
            elif sub == 3:
                v = ra & rb
            elif sub == 4:
                v = ra | rb
            elif sub == 5:
                v = ra ^ rb
            elif sub == 0x306:
                v = sx(ra, 32) * sx(rb, 32)
            elif sub == 0x309:
                if rb == 0:
                    raise EmuError(f'divide by zero at {pc:#x}')
                q = abs(sx(ra, 32)) // abs(sx(rb, 32))
                v = q if (sx(ra, 32) < 0) == (sx(rb, 32) < 0) else -q
            elif sub == 0x30a:
                if rb == 0:
                    raise EmuError(f'divide by zero at {pc:#x}')
                v = ra // rb
            elif sub == 0x008:
                v = ra << (rb & 31)
            elif sub == 0x048:
                v = ra >> (rb & 31)
            elif sub == 0x088:
                v = sx(ra, 32) >> (rb & 31)
            else:
                raise EmuError(f'ALU op {sub:#x} (not used by the stock firmware) at {pc:#x}')
            r[d] = v & 0xffffffff
        elif op == 0x39:
            self.f = self.cmp((w >> 21) & 31, r[a], r[b], pc)
        else:
            raise EmuError(f'opcode {op:#x} ({w:08x}) not allowed at {pc:#x}')
        r[0] = 0
        self.pc = npc
        if r[1] < self.min_sp:
            self.min_sp = r[1]
            if r[1] < self.stack_lo + 64:
                raise EmuError(f'stack overflow: sp={r[1]:#x}')

    @staticmethod
    def cmp(c, x, y, pc):
        if c in (0, 1, 2, 3, 4, 5):
            res = [x == y, x != y, x > y, x >= y, x < y, x <= y][c]
        elif c in (10, 11, 12, 13):
            xs, ys = sx(x, 32), sx(y, 32)
            res = [xs > ys, xs >= ys, xs < ys, xs <= ys][c - 10]
        else:
            raise EmuError(f'compare type {c} at {pc:#x}')
        return res

    def run(self, start, stop, limit=400_000_000):
        self.pc = start
        while self.pc != stop:
            self.step()
            self.steps += 1
            if self.steps > limit:
                raise EmuError('step limit')
