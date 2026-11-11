"""Receipt Quest installer: put a mod (a pack) on the camera, or take it off again.

    rq_install.py install NAME     e.g. install print-effect
    rq_install.py undo NAME        put those sectors back exactly as in your backup
    rq_install.py list             show the packs and whether your backup fits them (no USB)

Your camera is only touched if ALL of this holds:
  - your own backup (2_BACKUP.bat) matches the tested firmware in every sector
    except the camera's settings sector (sha256 per 4 KiB sector)
  - the pack rebuilds, from YOUR backup, exactly the sectors that were tested
    (sha256 of every one of them is in the pack's .json)
  - on the camera right now, each of those sectors is stock, already ours, or a
    half-written copy of ours (from an interrupted run); anything else = stop

Order of work:
  1. build the target from the backup + the pack and list the sectors that change
  2. restart into the chip's boot-ROM loader, check its ID and the chip ROM
  3. upload the read-only helper, check flash ID c8 40 16, read the whole flash
     ("before.bin") and check every planned sector is as expected
  4. upload the writer helper (verified) - it can only erase/program inside the
     pack's own sector windows, enforced inside the helper on the camera - and
     check the flash is not write-protected
  5. per sector: erase -> check blank -> program 32 x 128 bytes -> read back and
     compare; retries on USB hiccups; a journal line per step
  6. upload the read-only helper again, read the whole flash ("after.bin") and
     check it equals "before" with exactly the planned sectors changed
  7. let the loader go; the camera restarts normally

Windows only (raw SCSI through the USB disk driver, needs administrator rights).
Python 3 standard library only.
"""
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import hashlib
import json
import os
import struct
import sys
import time
import traceback

import rq_packs as P
import rq_stub as R
import rq_stub_w as W
import rq_usb_step2b as s2
import rq_usb_step3 as s3

HERE = os.path.dirname(os.path.abspath(__file__))
LINES = []
MEM, NONE = s3.MEM_ROUTINE, s3.NO_CALLBACK
SCSI_IOCTL_DATA_OUT = 0
STATE = {'image': None, 'plan': set()}
JOURNAL = [None]


def log(s=''):
    print(s, flush=True)
    LINES.append(str(s))


def journal(**kv):
    kv['t'] = dt.datetime.now().isoformat(timespec='milliseconds')
    if JOURNAL[0]:
        with open(JOURNAL[0], 'a', encoding='utf-8') as f:
            f.write(json.dumps(kv) + '\n')
            f.flush()
            os.fsync(f.fileno())


s2.log = log
s3.log = log


# ---------------------------------------------------------------- commands
def check(cdb, length, direction):
    if cdb[0] != 0xCB or len(cdb) != 16:
        raise RuntimeError('only 0xCB here')
    routine, addr, cb = struct.unpack_from('<III', cdb, 1)
    flash = cdb[13] | cdb[14] << 8 | cdb[15] << 16
    if routine != MEM:
        raise RuntimeError('unknown routine')
    if cb == NONE:
        if direction == 'out':
            ok = W.LOAD <= addr and addr + length <= W.BUF and 0 < length <= 64
        else:
            ok = 0 < length <= 256 and ((s3.ROM_BASE <= addr and addr + length <= s3.ROM_BASE + s3.ROM_SIZE) or
                                        (W.LOAD <= addr and addr + length <= W.END))
    elif STATE['image'] == 'reader':
        ok = direction == 'in' and addr == R.BUF and (
            (cb == R.JEDEC_AT and length == 3) or (cb == R.READ_AT and 0 < length <= 256))
    elif STATE['image'] == 'writer':
        sector = flash & ~0xfff
        ok = addr == W.BUF and (
            (cb == W.ENTRY['STAT'] and direction == 'in' and length == 2) or
            (cb == W.ENTRY['READ'] and direction == 'in' and 0 < length <= 128) or
            (cb == W.ENTRY['ERASE'] and direction == 'in' and length == 1 and flash == sector
             and sector in STATE['plan']) or
            (cb == W.ENTRY['PROG'] and direction == 'out' and length == 128 and flash % 128 == 0
             and sector in STATE['plan']))
    else:
        ok = False
    if not ok:
        raise RuntimeError(f'command {cdb.hex()} len {length} {direction} is outside the plan - refused')


def cmd(handle, cdb, length, direction='in', data=b'', timeout=15):
    check(cdb, length, direction)
    t = time.perf_counter()
    buf = ctypes.create_string_buffer(max(length, 1) + 64)
    addr = (ctypes.addressof(buf) + 63) & ~63
    if direction == 'out':
        assert len(data) == length
        ctypes.memmove(addr, data, length)
    sp = s2.SPTDWithSense()
    sp.sptd.Length = ctypes.sizeof(s2.SPTD)
    sp.sptd.CdbLength = 16
    sp.sptd.SenseInfoLength = 32
    sp.sptd.DataIn = s2.SCSI_IOCTL_DATA_IN if direction == 'in' else SCSI_IOCTL_DATA_OUT
    sp.sptd.DataTransferLength = length
    sp.sptd.TimeOutValue = timeout
    sp.sptd.DataBuffer = addr
    sp.sptd.SenseInfoOffset = s2.SPTDWithSense.sense.offset
    for i, x in enumerate(cdb):
        sp.sptd.Cdb[i] = x
    ret = wt.DWORD()
    ok = s2.k32.DeviceIoControl(handle, s2.IOCTL_SCSI_PASS_THROUGH_DIRECT, ctypes.byref(sp), ctypes.sizeof(sp),
                                ctypes.byref(sp), ctypes.sizeof(sp), ctypes.byref(ret), None)
    err = 0 if ok else ctypes.get_last_error()
    got = ctypes.string_at(addr, sp.sptd.DataTransferLength) if ok and direction == 'in' else b''
    return {'status': sp.sptd.ScsiStatus if ok else None, 'data': got, 'err': err,
            'ms': (time.perf_counter() - t) * 1000, 'sense': bytes(sp.sense[:18]).hex()}


def cdb_mem(addr, callback=NONE, flash=0):
    return b'\xcb' + struct.pack('<III', MEM, addr, callback) + bytes([flash & 0xff, flash >> 8 & 0xff,
                                                                         flash >> 16 & 0xff])


def retry(h, cdb, length, direction='in', data=b'', tries=4, what=''):
    for k in range(1, tries + 1):
        r = cmd(h, cdb, length, direction, data)
        if r['status'] == 0 and (direction == 'out' or len(r['data']) == length):
            return r
        s3.show(f'{what} try {k}', r)
        time.sleep(0.3)
    return None


# ---------------------------------------------------------------- helpers
def upload(h, img, name):
    STATE['image'] = None
    for off in range(0, len(img), 64):
        piece = img[off:off + 64]
        if retry(h, cdb_mem(W.LOAD + off), len(piece), 'out', piece, what=f'upload {name}') is None:
            return False
    back = bytearray()
    for off in range(0, len(img), 256):
        r = retry(h, cdb_mem(W.LOAD + off), min(256, len(img) - off), what=f'check {name}')
        if r is None:
            return False
        back += r['data']
    if bytes(back) != img:
        log(f'{name} helper did not land exactly')
        return False
    STATE['image'] = name
    log(f'{name} helper uploaded and verified ({len(img)} bytes)')
    return True


def read_rom(h):
    data = bytearray()
    for a in range(s3.ROM_BASE, s3.ROM_BASE + s3.ROM_SIZE, 256):
        r = retry(h, cdb_mem(a), 256, what=f'ROM {a:#x}')
        if r is None:
            return None
        data += r['data']
    return bytes(data)


def read_all(h, size, label):
    assert STATE['image'] == 'reader'
    data = bytearray()
    t0 = time.monotonic()
    for a in range(0, size, 256):
        r = retry(h, cdb_mem(R.BUF, R.READ_AT, a), 256, tries=8, what=f'{label} @{a:#08x}')
        if r is None:
            log(f'{label}: the flash could not be read reliably at {a:#08x} (USB trouble).')
            return None
        data += r['data']
    log(f'{label}: read {len(data)} bytes in {time.monotonic() - t0:.0f} s, '
        f'sha256 {hashlib.sha256(data).hexdigest()[:16]}...')
    return bytes(data)


def w_read_sector(h, s):
    data = bytearray()
    for a in range(s, s + 0x1000, 128):
        r = retry(h, cdb_mem(W.BUF, W.ENTRY['READ'], a), 128, what=f'verify @{a:#08x}')
        if r is None:
            return None
        data += r['data']
    return bytes(data)


def w_status_byte(h):
    r = retry(h, cdb_mem(W.STATUS), 4, what='status byte')
    return None if r is None else r['data'][0]


def write_sector(h, s, want):
    """erase, blank check, program, verify - up to 3 attempts. True on success."""
    for attempt in range(1, 4):
        r = retry(h, cdb_mem(W.BUF, W.ENTRY['ERASE'], s), 1, what=f'erase {s:#08x}')
        sr = None if r is None else r['data'][0]
        journal(op='erase', sector=hex(s), attempt=attempt, status=sr)
        if sr is None or sr == 0xEE or sr & 0x03:
            log(f'  erase {s:#08x}: status {sr} - not clean')
            continue
        blank = w_read_sector(h, s)
        if blank != b'\xff' * 0x1000:
            log(f'  sector {s:#08x} not blank after erase')
            journal(op='blank_check', sector=hex(s), ok=False)
            continue
        ok = True
        for a in range(s, s + 0x1000, 128):
            piece = want[a - s:a - s + 128]
            if piece == b'\xff' * 128:
                continue                                   # already erased state
            if retry(h, cdb_mem(W.BUF, W.ENTRY['PROG'], a), 128, 'out', piece, what=f'program {a:#08x}') is None:
                ok = False
                break
            st = w_status_byte(h)
            if st is None or st == 0xEE or st & 0x03:
                log(f'  program {a:#08x}: status {st}')
                ok = False
                break
        got = w_read_sector(h, s) if ok else None
        good = got == want
        journal(op='program+verify', sector=hex(s), attempt=attempt, ok=good)
        if good:
            return True
        log(f'  sector {s:#08x} did not verify (attempt {attempt})')
    return False


# ---------------------------------------------------------------- packs -> jobs
def prepare_job(action, name, backup):
    """-> job dict for run_job, or None (with the reason logged)."""
    if name not in P.pack_names():
        log(f'no pack called {name!r}. Packs here: {", ".join(P.pack_names())}')
        return None
    try:
        man, ours = P.build(backup, name)
    except ValueError as e:
        log(f'{e} - stopped, camera untouched.')
        return None
    undo = action == 'undo'
    plan = sorted(int(s, 16) for s in man['sectors'])
    target = backup if undo else ours
    last = {int(s, 16) for s in (man['last_undo'] if undo else man['last_install'])}
    needs = [] if undo else man.get('requires', [])

    def precheck(before):
        for other in needs:
            try:
                oman, oours = P.build(backup, other)
            except (ValueError, OSError) as e:
                return f'this pack needs {other!r} first, and that pack cannot be checked ({e}).'
            for s in oman['sectors']:
                a = int(s, 16)
                if before[a:a + P.SECTOR] != oours[a:a + P.SECTOR]:
                    return f'this pack needs {other!r} on the camera first - install that one before this.'
        return None
    return {'mode': f'{action}_{name}', 'title': man['title'] + (' PUT BACK TO STOCK' if undo else ''),
            'target': target, 'expected': hashlib.sha256(target).hexdigest(), 'plan': plan,
            'known': lambda sec, cur: cur in (backup[sec:sec + P.SECTOR], ours[sec:sec + P.SECTOR]),
            'precheck': precheck, 'last': last,
            'windows': tuple((lo, hi) for lo, hi in man['windows']), 'folder': 'write'}


def list_packs():
    path, backup, lines = P.find_backup(HERE)
    log('backup: ' + (path or 'none usable'))
    for line in lines:
        log(line)
    for name in P.pack_names():
        try:
            man, _ = P.load_pack(name)
            fits = ''
            if backup is not None:
                P.build(backup, name)
                fits = '  (fits your backup)'
            log(f'  {name:16s} {man["title"]}: {len(man["sectors"])} sectors{fits}')
            if man.get('note'):
                log(f'                   {man["note"]}')
        except ValueError as e:
            log(f'  {name:16s} PROBLEM: {e}')


def main(action, name):
    log(f'RECEIPT QUEST installer ({action} {name})  ' + dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    if action == 'list':
        list_packs()
        return
    if action not in ('install', 'undo') or not name:
        log('usage: rq_install.py install|undo PACK   or   rq_install.py list')
        return
    if not ctypes.windll.shell32.IsUserAnAdmin():
        log('Not admin - run the .bat file and click Yes.')
        return
    bpath, backup, lines = P.find_backup(HERE)
    for line in lines:
        log(line)
    if backup is None:
        log('no backup that matches the tested firmware - stopped, camera untouched.')
        return
    log(f'backup: {bpath}')
    job = prepare_job(action, name, backup)
    if job:
        run_job(job, backup)


def run_job(job, backup):
    mode, target, plan = job['mode'], job['target'], job['plan']
    if not plan:
        log('nothing to write for this mode - camera untouched.')
        return
    log(f'plan: {len(plan)} sectors {plan[0]:#x}..{plan[-1]:#x}')

    run = base = os.path.join(HERE, f"{job['folder']}_{mode}_" + dt.datetime.now().strftime('%Y%m%d_%H%M%S'))
    k = 1
    while os.path.exists(run):
        run, k = f'{base}_{k}', k + 1
    os.makedirs(run)
    JOURNAL[0] = os.path.join(run, 'journal.jsonl')
    journal(op='start', mode=mode, plan=[hex(s) for s in plan], target_sha=job['expected'])

    # 2. loader
    path = s3.enter_loader()
    if not path:
        return
    h, err = s2.open_dev(path)
    if h is None:
        log(f'could not open the loader disk (error {err})')
        return
    report = {'mode': mode, 'flash_written': False}
    try:
        st, _, inq = s2.scsi(h, bytes([0x12, 0, 0, 0, 64, 0]), 64)
        if st != 0 or inq != s2.PENGUIN_INQUIRY:
            log('loader ID differs - stopped.')
            return
        rom = read_rom(h)
        if rom is None or hashlib.sha256(rom).hexdigest() != s3.PENGUIN_ROM_SHA:
            log('chip ROM check failed - stopped.')
            return
        log('loader and chip ROM ok')

        # 3. reader + before
        if not upload(h, R.image(), 'reader'):
            return
        r = retry(h, cdb_mem(R.BUF, R.JEDEC_AT), 3, what='flash ID')
        if r is None or r['data'] != bytes([0xc8, 0x40, 0x16]):
            log(f'flash ID not c8 40 16 ({None if r is None else r["data"].hex()}) - stopped.')
            return
        size = 0x400000
        before = read_all(h, size, 'before')
        if before is None:
            log('Stopped before writing, camera untouched. Unplug the USB cable, wait 10 s, plug it in, run again.')
            return
        with open(os.path.join(run, 'before.bin'), 'wb') as f:
            f.write(before)
        why = job.get('precheck', lambda b: None)(before)
        if why:
            log(why + ' Stopped before writing, camera untouched.')
            return
        todo = []
        for s in plan:
            cur, t0 = before[s:s + 0x1000], target[s:s + 0x1000]
            if cur == t0:
                continue                                   # already done
            partial = all(c in (0xff, t) for c, t in zip(cur, t0))
            if not (job['known'](s, cur) or partial):
                log(f'sector {s:#08x} is neither stock, ours, nor a half-written copy - stopped before writing.')
                return
            todo.append(s)
        others = [hex(a) for a in range(0, size, 0x1000) if a not in plan and before[a:a + 0x1000] != backup[a:a + 0x1000]]
        log(f'outside the plan, sectors that differ from the backup (earlier mods / settings): {len(others)}')
        if not todo:
            log('everything in the plan is already written - nothing to do.')
            return
        todo.sort(key=lambda s: (s in job['last'], s))           # e.g. the power-on music last
        STATE['plan'] = set(todo)
        log(f'{len(todo)} sectors to write')

        # 4. writer + protection check
        if not upload(h, W.image(job['windows']), 'writer'):
            return
        r = retry(h, cdb_mem(W.BUF, W.ENTRY['STAT']), 2, what='status registers')
        if r is None:
            return
        sr1, sr2 = r['data']
        log(f'flash status: SR1={sr1:#04x} SR2={sr2:#04x}')
        journal(op='status', sr1=sr1, sr2=sr2)
        if sr1 & 0x7d or sr2 & 0x40:
            log('flash reports write protection or busy - stopped (status registers are never changed).')
            return

        # 5. write
        report['flash_written'] = True
        t0 = time.monotonic()
        for n, s in enumerate(todo, 1):
            okay = write_sector(h, s, target[s:s + 0x1000])
            if n % 25 == 0 or not okay or n == len(todo):
                log(f'  [{n}/{len(todo)}] sector {s:#08x}: {"ok" if okay else "FAILED"}')
            if not okay:
                log('STOPPED with this sector not verified. Do not unplug or switch off the camera yet -')
                log('see docs/TROUBLESHOOTING.md - your backup has everything needed to put it right.')
                report['failed_sector'] = hex(s)
                return
        log(f'all {len(todo)} sectors written and verified in {time.monotonic() - t0:.0f} s')

        # 6. after
        if not upload(h, R.image(), 'reader'):
            return
        after = read_all(h, size, 'after')
        if after is None:
            log('All sectors were written and verified one by one, but the final full read-back failed.')
            log('Run the same .bat again: it reads everything again and says "already written" if all is well.')
            return
        with open(os.path.join(run, 'after.bin'), 'wb') as f:
            f.write(after)
        expect = bytearray(before)
        for s in todo:
            expect[s:s + 0x1000] = target[s:s + 0x1000]
        same = after == bytes(expect)
        bad = [hex(a) for a in range(0, size, 0x1000) if after[a:a + 0x1000] != expect[a:a + 0x1000]]
        report.update(after_ok=same, unexpected=bad, sectors=[hex(s) for s in todo])
        log('\nVERDICT:')
        log(f'  whole flash = before + exactly the planned sectors: {same}' + ('' if same else f' {bad}'))
        log(f"  {job['title']} WRITTEN" if same else '  check failed - see docs/TROUBLESHOOTING.md')
    finally:
        s2.k32.CloseHandle(h)
        with open(os.path.join(run, 'report.json'), 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        if 'failed_sector' in report:
            log('\nleaving the camera in loader mode on purpose (USB stays usable).')
        else:
            time.sleep(0.5)
            log('\nletting go of the loader: ' + s3.eject_loader())
            index = s2.wait_for_camera(60)
            log('camera is back in normal USB mode with its card' if index is not None else
                'camera not back yet - unplug the USB cable, wait 10 s, plug it back in')
        journal(op='end', report=report)


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    name = sys.argv[2] if len(sys.argv) > 2 else ''
    try:
        main(action, name)
    except Exception:
        log(traceback.format_exc())
    with open(os.path.join(HERE, f'log_{action or "x"}_{name or "x"}.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(LINES) + '\n')
