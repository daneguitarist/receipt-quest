"""End-to-end offline rehearsal of rq_install.py (Linux/macOS/Windows, no camera).

The Windows/USB layer is replaced by a fake boot-ROM loader that behaves like the
ROM's 0xCB memory routine, runs the REAL writer helper (rq_stub_w) in the OpenRISC
interpreter against a NOR-flash model, and drops ~3% of USB replies (half of them
after the work was done, like a lost reply). It then installs and undoes every
pack, interrupts writes, plants unexpected bytes, tampers with a pack and offers an
incompatible backup, checking the whole flash after every step.

    python3 test_install_offline.py STOCK_BACKUP.bin WORKDIR

STOCK_BACKUP.bin = your own 3_BACKUP.bat result from an unmodified camera.
"""
import hashlib
import os
import random
import shutil
import struct
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALL = os.path.join(HERE, '..')
sys.path.insert(0, INSTALL)
sys.path.insert(0, HERE)

# ---- stand-ins for the Windows-only modules ------------------------------------
s2 = types.ModuleType('rq_usb_step2b')
s3 = types.ModuleType('rq_usb_step3')
sys.modules['rq_usb_step2b'] = s2
sys.modules['rq_usb_step3'] = s3
s3.MEM_ROUTINE, s3.NO_CALLBACK, s3.ROM_BASE, s3.ROM_SIZE = 0x00102620, 0xFFFFFFFF, 0x100000, 0x8000
FAKE_ROM = random.Random(5).randbytes(0x8000)       # the real chip ROM is not needed: only its sha256 is checked
s3.PENGUIN_ROM_SHA = hashlib.sha256(FAKE_ROM).hexdigest()
s2.PENGUIN_INQUIRY = b'\x00' * 49
s2.log = s3.log = print
s3.show = lambda name, r: print(f'   (retry) {name}: status={r["status"]}')
s3.enter_loader = lambda: 'fake-loader'
s3.eject_loader = lambda: 'ok'
s2.open_dev = lambda p: (1, 0)
s2.wait_for_camera = lambda t=60: 3
s2.k32 = types.SimpleNamespace(CloseHandle=lambda h: None)
s2.scsi = lambda h, cdb, n, timeout=5: (0, '', s2.PENGUIN_INQUIRY)

import rq_install as I            # noqa: E402
import rq_packs as P              # noqa: E402
import rq_stub as R               # noqa: E402
import rq_stub_w as W             # noqa: E402
import test_rq_stub_w as TW       # noqa: E402

SETTINGS = 0x2ff000


class FakeLoader:
    def __init__(self, flash_bytes, drop=0.03):
        self.flash = TW.NorFlash(flash_bytes, busy_polls=3)
        self.cpu = TW.CPUW(self.flash)
        self.drop = drop
        self.calls = 0

    def run_cb(self, cb, r3, r4, flash):
        if cb == R.READ_AT and I.STATE['image'] == 'reader':
            self.cpu.mem[r3:r3 + r4] = self.flash.mem[flash:flash + r4]        # fast path (tested in test_rq_stub)
            return
        if cb == R.JEDEC_AT and I.STATE['image'] == 'reader':
            self.cpu.mem[r3:r3 + 3] = bytes([0xc8, 0x40, 0x16])
            return
        self.cpu.call(cb, r3, r4, flash | random.getrandbits(8) << 24)

    def cmd(self, h, cdb, length, direction='in', data=b'', timeout=15):
        I.check(cdb, length, direction)                 # the real PC-side fence
        self.calls += 1
        routine, addr, cb = struct.unpack_from('<III', cdb, 1)
        flash = cdb[13] | cdb[14] << 8 | cdb[15] << 16
        fail = {'status': None, 'data': b'', 'err': 31, 'ms': 1, 'sense': ''}
        roll = random.random()
        if roll < self.drop / 2:
            return fail
        mem = self.cpu.mem
        if direction == 'out':
            mem[addr:addr + length] = data
            if cb != I.NONE:
                self.run_cb(cb, addr, length, flash)
            out = b''
        else:
            if cb != I.NONE:
                self.run_cb(cb, addr, length, flash)
            if s3.ROM_BASE <= addr < s3.ROM_BASE + s3.ROM_SIZE:
                out = FAKE_ROM[addr - s3.ROM_BASE:addr - s3.ROM_BASE + length]
            else:
                out = bytes(mem[addr:addr + length])
        if roll < self.drop:
            return fail
        return {'status': 0, 'data': out, 'err': 0, 'ms': 1, 'sense': ''}


def text():
    return '\n'.join(I.LINES)


def main(stock_path, work):
    stock = open(stock_path, 'rb').read()
    ok, why = P.check_backup(stock)
    assert ok, why
    random.seed(11)
    tool = os.path.join(work, 'tool')
    if os.path.exists(tool):
        shutil.rmtree(tool)
    shutil.copytree(INSTALL, tool, ignore=shutil.ignore_patterns('tests', '__pycache__', 'firmware_backup_*', 'write_*'))
    # this camera has its own settings - its backup differs from the tested one there
    backup = bytearray(stock)
    backup[SETTINGS:SETTINGS + 16] = b'OTHER CAMERA SET'
    backup = bytes(backup)
    os.makedirs(os.path.join(tool, 'firmware_backup_20990101_000000'))
    open(os.path.join(tool, 'firmware_backup_20990101_000000', 'BACKUP_firmware.bin'), 'wb').write(backup)
    I.HERE = tool
    P.HERE = tool
    I.ctypes.windll = types.SimpleNamespace(shell32=types.SimpleNamespace(IsUserAnAdmin=lambda: 1))
    I.time.sleep = lambda s: None

    # since the backup, the user changed a setting on the camera again
    camera = bytearray(backup)
    camera[SETTINGS + 16:SETTINGS + 32] = b'CHANGED SETTING!'
    dev = FakeLoader(bytes(camera))
    I.cmd = dev.cmd

    def run(action, name):
        I.LINES.clear()
        n = len(dev.flash.erased)
        I.main(action, name)
        return dev.flash.erased[n:]

    built = {name: P.build(backup, name) for name in P.pack_names()}
    packs = []                                       # every pack in the folder, required ones first
    while len(packs) < len(built):
        ready = [n for n in sorted(built) if n not in packs and all(r in packs for r in built[n][0]['requires'])]
        assert ready, 'packs with circular or missing requirements'
        packs.append(ready[0])
    for a in packs:                                  # two packs must never share a sector
        for b in packs:
            if a < b:
                both = set(built[a][0]['sectors']) & set(built[b][0]['sectors'])
                assert not both, f'{a} and {b} both change {sorted(both)[:4]}'
    print('packs:', ', '.join(packs))

    def apply(base, names, undo=False):
        e = bytearray(base)
        for name in names:
            man, ours = built[name]
            for s in man['sectors']:
                a = int(s, 16)
                e[a:a + P.SECTOR] = (backup if undo else ours)[a:a + P.SECTOR]
        return bytes(e)

    start = bytes(dev.flash.mem)
    for name in packs:
        if built[name][0]['requires']:
            print(f'\n========== {name} before {built[name][0]["requires"]} (refused) ==========')
            erases = run('install', name)
            assert not erases and bytes(dev.flash.mem) == start and 'install that one before this' in text()
            print('--> refused, flash untouched')

    done = []
    for name in packs:
        print(f'\n========== install {name} ==========')
        erases = run('install', name)
        done.append(name)
        man = built[name][0]
        assert bytes(dev.flash.mem) == apply(start, done), f'{name}: flash is not the expected image'
        assert f"{man['title']} WRITTEN" in text(), f'{name}: no success verdict'
        assert not dev.flash.illegal, dev.flash.illegal[:3]
        order = list(dict.fromkeys(erases))
        assert set(order) == {int(s, 16) for s in man['sectors']}
        last = {int(s, 16) for s in man['last_install']}
        pos = [k for k, x in enumerate(order) if x in last]
        assert pos == list(range(len(order) - len(pos), len(order))), 'last-install sectors not last'
        assert bytes(dev.flash.mem[SETTINGS:SETTINGS + P.SECTOR]) == camera[SETTINGS:SETTINGS + P.SECTOR]
        print(f'--> {name}: flash == expected, settings untouched, {len(order)} sectors, order rules kept')

    full = bytes(dev.flash.mem)
    for name in packs:
        man, ours = built[name]
        secs = sorted(int(s, 16) for s in man['sectors'])
        print(f'\n========== {name}: again (nothing to do), then interrupted (one sector erased, one half-written) ==========')
        erases = run('install', name)
        assert not erases and 'already written' in text()
        a, b = secs[0], secs[-1]
        dev.flash.mem[a:a + 0x1000] = b'\xff' * 0x1000
        dev.flash.mem[b:b + 0x1000] = b'\xff' * 0x1000
        dev.flash.mem[b:b + 0x600] = ours[b:b + 0x600]
        erases = run('install', name)
        assert bytes(dev.flash.mem) == full and f"{man['title']} WRITTEN" in text()
        assert set(erases) == {a, b}, erases
        print(f'--> no erases the first time; then only {a:#x} and {b:#x} rewritten')

    name = packs[0]
    victim = sorted(int(s, 16) for s in built[name][0]['sectors'])[0] + 0x10
    print(f'\n========== unexpected bytes in a {name} sector (undo refused) ==========')
    dev.flash.mem[victim] ^= 0x5a
    snap = bytes(dev.flash.mem)
    erases = run('undo', name)
    assert not erases and bytes(dev.flash.mem) == snap and 'stopped before writing' in text()
    dev.flash.mem[victim] ^= 0x5a
    print('--> refused, flash untouched')

    print('\n========== a damaged pack (refused before any USB) ==========')
    rqp = os.path.join(tool, 'packs', packs[-1] + '.rqp')
    good = open(rqp, 'rb').read()
    bad = bytearray(good)
    bad[len(bad) // 2] ^= 1
    open(rqp, 'wb').write(bytes(bad))
    calls = dev.calls
    erases = run('undo', packs[-1])
    assert not erases and dev.calls == calls and 'changed or damaged' in text()
    open(rqp, 'wb').write(good)
    print('--> refused, no USB command sent')

    remaining = list(done)
    for name in reversed(packs):
        print(f'\n========== undo {name} ==========')
        erases = run('undo', name)
        remaining.remove(name)
        man = built[name][0]
        assert bytes(dev.flash.mem) == apply(start, remaining), f'undo {name}: flash is not the expected image'
        assert 'PUT BACK TO STOCK WRITTEN' in text()
        order = list(dict.fromkeys(erases))
        last = {int(s, 16) for s in man['last_undo']}
        pos = [k for k, x in enumerate(order) if x in last]
        assert pos == list(range(len(order) - len(pos), len(order))), 'last-undo sectors not last'
        print(f'--> {name} removed; {len(order)} sectors; order rules kept')
    assert bytes(dev.flash.mem) == start
    print('--> camera is exactly as before (with its own settings)')

    print('\n========== a backup from a different firmware (refused before any USB) ==========')
    other = bytearray(backup)
    other[0x61000 + 123] ^= 0x10
    os.rename(os.path.join(tool, 'firmware_backup_20990101_000000'), os.path.join(tool, 'keep'))
    os.makedirs(os.path.join(tool, 'firmware_backup_20990102_000000'))
    open(os.path.join(tool, 'firmware_backup_20990102_000000', 'BACKUP_firmware.bin'), 'wb').write(bytes(other))
    calls = dev.calls
    erases = run('install', packs[0])
    assert not erases and dev.calls == calls and 'no backup that matches' in text() and '0x61000' in text()
    print('--> refused, it names the differing sector, no USB command sent')

    print('\n========== the PC-side fence ==========')
    I.STATE['image'], I.STATE['plan'] = 'writer', {0x244000}
    for flash in (0x0, 0x1000, 0x61000, 0xb1000, 0x243000, 0x248000, 0x2ff000, 0x244001):
        try:
            I.check(I.cdb_mem(W.BUF, W.ENTRY['ERASE'], flash), 1, 'in')
            raise AssertionError(f'erase {flash:#x} was allowed')
        except RuntimeError:
            pass
    for name in packs:
        man = built[name][0]
        W.image(tuple(tuple(w) for w in man['windows']))      # every pack's helper builds (size + NEVER checks)
    print('--> erase outside the plan refused; every pack\'s writer helper builds inside its limits')
    print(f'\nALL INSTALLER REHEARSALS PASSED ({dev.calls} fake USB commands, {len(dev.flash.erased)} erases)')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
