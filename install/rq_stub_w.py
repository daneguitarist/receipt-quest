"""Receipt Quest flash WRITER helpers for the boot-ROM loader (AX329x, OpenRISC,
no delay slots). Same idea as rq_stub.py (read-only helpers, used first for the
chip ID and the "before" read), plus erase and program - fenced in so they can
only touch the sector windows they are built for (one mod's sectors).

Run as callbacks of the ROM routine 0x102620:
  read  direction: ROM calls cb(r3=buf, r4=len, r5=CDB[13..15]) then sends buf
  write direction: ROM receives len bytes into buf, then calls the same cb

Entries (fixed SRAM addresses; buffer BUF = 0x4b80, 128 bytes):
  STAT   read,  len 2      -> status register 1 (05) and 2 (35)
  READ   read,  len 1..128, r5 = flash address -> 03 read
  ERASE  read,  len 1, r5 = 4 KiB sector address -> 06, 20 addr, poll 05;
                           returns the final status byte (0xEE = refused)
  PROG   write, len 128, r5 = address of a 128-byte half page -> 06, 02 addr +
                           128 bytes, poll 05; final status byte at STATUS

Hard fence inside the helpers (not just on the PC): ERASE/PROG only accept
addresses inside the windows the helper was built with (e.g. [0x1f1000, 0x1f3000)
and [0x228000, 0x248000) for the 7 sounds), correctly aligned, with the right
buffer and length. Anything else returns without a single SPI command. There is no chip
erase, block erase or status-register write anywhere in here.
"""
from rq_stub import Asm, CS_LOW, CS_HIGH, MODE_SEND, MODE_RECV, XFER

LOAD = 0x4800
STATUS = 0x4b78                 # last PROG result byte
SCRATCH = 0x4b7c                # status byte while polling
BUF = 0x4b80
BUF_LEN = 128
END = 0x4c00
SECTOR_WINDOWS = ((0x1f1, 0x1f3), (0x228, 0x248))     # 4 KiB sector numbers: the 7 sounds (default)
FRAME_WINDOWS = ((0xb7, 0x1dd),)                       # the 21 photo frames (res04..res24); the
                                                       # resource table (sector 0xb1) stays outside
SCREEN1_WINDOWS = ((0x201, 0x228), (0x254, 0x257), (0x2d1, 0x2da))   # main menu + big icons (res39..44),
                                                       # selected bar (res64 sprite #1), settings (res71)
SCREEN2_WINDOWS = ((0x295, 0x2aa), (0x2f5, 0x2fd))     # switch-off/on screens (res67/68), USB screen (res78)
FX_WINDOWS = ((0xe, 0x10), (0x18, 0x19), (0x380, 0x384))   # print effect: the 3 print calls (photo screen +
                                                       # gallery), the loader stub in the dead Game-menu
                                                       # code, the effect itself in the erased flash tail
NEVER = (0x0, 0x1, 0x2, 0x61, 0xb1, 0x2ff)             # boot header/stub, boot-time code (nvfs +
                                                       # printer init run before the SD updater),
                                                       # resource table, settings
WINDOWS = tuple((lo << 12, hi << 12) for lo, hi in SECTOR_WINDOWS)
POLL_LIMIT = 0x40000
WDT_SPR, WDT_VALUE = 0x880c, 0x5001d   # the ROM's own watchdog kick

ENTRY = {}


def _mtspr0(a, rb, spr):
    a.w(0x30 << 26 | ((spr >> 11) & 0x1f) << 21 | rb << 11 | (spr & 0x7ff))


def _lbz(a, d, off, ra):
    a.w(0x23 << 26 | d << 21 | ra << 16 | (off & 0xffff))


def _sfltui(a, ra, imm):
    a.w(0x2f << 26 | 0x4 << 21 | ra << 16 | (imm & 0xffff))


def _sfne(a, ra, rb):
    a.w(0x39 << 26 | 0x1 << 21 | ra << 16 | rb << 11)


def _frame(a, regs):
    a.addi(1, 1, -4 * (len(regs) + 1))
    a.sw(0, 1, 9)
    for k, r in enumerate(regs, 1):
        a.sw(4 * k, 1, r)


def _unframe(a, regs):
    a.lwz(9, 0, 1)
    for k, r in enumerate(regs, 1):
        a.lwz(r, 4 * k, 1)
    a.addi(1, 1, 4 * (len(regs) + 1))
    a.jr(9)


ENTRY_SAVED = [14, 16, 18, 20]


def build(windows=SECTOR_WINDOWS):
    assert not any(lo <= n < hi for lo, hi in windows for n in NEVER), 'boot / resource table / settings sectors must stay outside'
    a = Asm(LOAD)

    # txn: one read transaction. r3 = command, r6 = 1 to send the address in r18,
    #      r14 = destination, r16 = byte count. Leaves r14/r16 advanced.
    a.label('txn')
    _frame(a, [22, 24])
    a.ori(22, 3, 0)
    a.ori(24, 6, 0)
    a.jal(CS_LOW)
    a.jal(MODE_SEND)
    a.ori(3, 22, 0)
    a.jal(XFER)
    a.sfeqi(24, 0)
    a.bf('txn_noaddr')
    a.jal('send_addr')
    a.label('txn_noaddr')
    a.jal(MODE_RECV)
    a.label('txn_loop')
    a.sfeqi(16, 0)
    a.bf('txn_end')
    a.addi(3, 0, 0xFF)
    a.jal(XFER)
    a.sb(0, 14, 11)
    a.addi(14, 14, 1)
    a.addi(16, 16, -1)
    a.j('txn_loop')
    a.label('txn_end')
    a.jal(CS_HIGH)
    _unframe(a, [22, 24])

    # send_addr: three address bytes from r18 (CS already low, send mode)
    a.label('send_addr')
    _frame(a, [])
    a.srli(3, 18, 16)
    a.andi(3, 3, 0xff)
    a.jal(XFER)
    a.srli(3, 18, 8)
    a.andi(3, 3, 0xff)
    a.jal(XFER)
    a.andi(3, 18, 0xff)
    a.jal(XFER)
    _unframe(a, [])

    # cmd_start: CS low, send mode, write-enable frame first; then CS low + command r3 + address
    a.label('cmd_start')
    _frame(a, [22])
    a.ori(22, 3, 0)
    a.jal(CS_LOW)
    a.jal(MODE_SEND)
    a.addi(3, 0, 0x06)
    a.jal(XFER)
    a.jal(CS_HIGH)
    a.jal(CS_LOW)
    a.jal(MODE_SEND)
    a.ori(3, 22, 0)
    a.jal(XFER)
    a.jal('send_addr')
    _unframe(a, [22])

    # wait_ready: poll status 1 until WIP clears (kicking the watchdog) -> r11
    a.label('wait_ready')
    _frame(a, [14, 16, 20])
    a.movhi(20, POLL_LIMIT >> 16)
    a.ori(20, 20, POLL_LIMIT & 0xffff)
    a.label('wr_loop')
    a.movhi(3, WDT_VALUE >> 16)
    a.ori(3, 3, WDT_VALUE & 0xffff)
    _mtspr0(a, 3, WDT_SPR)
    a.addi(3, 0, 0x05)
    a.addi(6, 0, 0)
    a.addi(14, 0, SCRATCH)
    a.addi(16, 0, 1)
    a.jal('txn')
    _lbz(a, 11, SCRATCH, 0)
    a.andi(3, 11, 1)
    a.sfeqi(3, 0)
    a.bf('wr_done')
    a.addi(20, 20, -1)
    a.sfeqi(20, 0)
    a.bnf('wr_loop')
    a.label('wr_done')
    _unframe(a, [14, 16, 20])

    # fence: r18 = r5 & 0xffffff; r11 = 1 if (r18 & r6) == 0 and inside a window
    a.label('fence')
    a.addi(11, 0, 0)
    a.movhi(18, 0x00ff)
    a.ori(18, 18, 0xffff)
    a.and_(18, 5, 18)
    a.and_(3, 18, 6)
    a.sfnei(3, 0)
    a.bf('fence_no')
    a.srli(3, 18, 12)
    for k, (lo, hi) in enumerate(windows):
        _sfltui(a, 3, lo)
        a.bf(f'fence_next{k}')
        _sfltui(a, 3, hi)
        a.bf('fence_yes')
        a.label(f'fence_next{k}')
    a.label('fence_no')
    a.jr(9)
    a.label('fence_yes')
    a.addi(11, 0, 1)
    a.jr(9)

    def entry(name, n, ranged=False):
        a.label(name)
        ENTRY[name] = a.pc
        _frame(a, ENTRY_SAVED)
        a.addi(14, 0, BUF)
        _sfne(a, 3, 14)
        a.bf('leave')
        if ranged:
            a.sfeqi(4, 0)
            a.bf('leave')
            a.sfgtui(4, n)
        else:
            a.sfnei(4, n)
        a.bf('leave')

    # ---------------- STAT ----------------
    entry('STAT', 2)
    a.addi(3, 0, 0x05)
    a.addi(6, 0, 0)
    a.addi(16, 0, 1)
    a.jal('txn')
    a.addi(3, 0, 0x35)
    a.addi(6, 0, 0)
    a.addi(16, 0, 1)
    a.jal('txn')
    a.label('leave')                             # shared epilogue: all entries use the same frame
    _unframe(a, ENTRY_SAVED)

    # ---------------- READ ----------------
    entry('READ', BUF_LEN, ranged=True)
    a.ori(16, 4, 0)
    a.movhi(18, 0x00ff)
    a.ori(18, 18, 0xffff)
    a.and_(18, 5, 18)
    a.addi(3, 0, 0x03)
    a.addi(6, 0, 1)
    a.jal('txn')
    a.j('leave')

    # ---------------- ERASE (one 4 KiB sector) ----------------
    entry('ERASE', 1)
    a.addi(3, 0, 0xEE)
    a.sb(0, 14, 3)                               # assume refused
    a.addi(6, 0, 0xfff)
    a.jal('fence')
    a.sfeqi(11, 0)
    a.bf('leave')
    a.jal('wait_ready')
    a.andi(3, 11, 1)
    a.sfnei(3, 0)
    a.bf('erase_store')
    a.addi(3, 0, 0x20)
    a.jal('cmd_start')
    a.jal(CS_HIGH)
    a.jal('wait_ready')
    a.label('erase_store')
    a.sb(0, 14, 11)                              # final status (WIP must be 0)
    a.j('leave')

    # ---------------- PROG (128 bytes = half a page) ----------------
    entry('PROG', BUF_LEN)
    a.addi(20, 0, STATUS)
    a.addi(3, 0, 0xEE)
    a.sb(0, 20, 3)                               # assume refused
    a.addi(6, 0, 0x7f)
    a.jal('fence')
    a.sfeqi(11, 0)
    a.bf('leave')
    a.jal('wait_ready')
    a.andi(3, 11, 1)
    a.sfnei(3, 0)
    a.bf('prog_store')
    a.addi(3, 0, 0x02)
    a.jal('cmd_start')
    a.addi(16, 0, BUF_LEN)
    a.label('pg_loop')
    _lbz(a, 3, 0, 14)
    a.jal(XFER)
    a.addi(14, 14, 1)
    a.addi(16, 16, -1)
    a.sfeqi(16, 0)
    a.bnf('pg_loop')
    a.jal(CS_HIGH)
    a.jal('wait_ready')
    a.label('prog_store')
    a.sb(0, 20, 11)
    a.j('leave')

    code = a.done()
    assert LOAD + len(code) <= STATUS, f'writer code too big: {len(code)} bytes (max {STATUS - LOAD})'
    return code


def image(windows=SECTOR_WINDOWS):
    """Bytes to upload at LOAD: the code, zero padding, STATUS and SCRATCH words."""
    code = build(windows)
    return code + b'\0' * (BUF - LOAD - len(code))


if __name__ == '__main__':
    for w in (SECTOR_WINDOWS, FRAME_WINDOWS, SCREEN1_WINDOWS, SCREEN2_WINDOWS, FX_WINDOWS):
        img = image(w)
        print(w, len(build(w)), 'code bytes,', len(img), 'upload bytes; entries',
              {k: hex(v) for k, v in ENTRY.items()})
