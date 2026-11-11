"""Receipt Quest USB - STEP 4: back up the camera's whole firmware flash, read-only.

How (everything goes through the chip's own boot-ROM loader, verified in step 3):
  1. restart into the loader (0xDA) and check its ID
  2. read the chip ROM again and check its sha256 (same ROM = the ROM building
     blocks the helper uses are exactly where we expect)
  3. copy the tiny helper program (rq_stub.py, 448 bytes) into the loader's
     scratch RAM at 0x4800 and read it back to check it landed exactly.
     This RAM is wiped when the camera restarts.
  4. ask the flash chip its ID (command 9F) - must look like a real SPI flash
  5. read the whole flash twice, 256 bytes at a time (command 03 only), and
     compare the two reads
  6. save flash_read1.bin, flash_read2.bin, BACKUP_firmware.bin + report,
     then let the loader go so the camera restarts normally

The helper can only send the flash chip "9F" (ID) and "03" (read). Every 0xCB
command this script sends is checked against fixed limits before it goes out.
Nothing is ever written to the flash.
"""
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import hashlib
import json
import os
import struct
import time
import traceback

import rq_packs
import rq_stub as stub
import rq_usb_step2b as s2
import rq_usb_step3 as s3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'log_backup.txt')
LINES = []

MEM = s3.MEM_ROUTINE
NONE = s3.NO_CALLBACK
SCSI_IOCTL_DATA_OUT = 0
STATE = {'stub_verified': False}


def log(s=''):
    print(s, flush=True)
    LINES.append(str(s))


s2.log = log
s3.log = log


def check(cdb, length, direction):
    """Hard limits for every 0xCB command in this step."""
    if cdb[0] != 0xCB or len(cdb) != 16:
        raise RuntimeError('only 0xCB here - refused')
    routine, addr, cb = struct.unpack_from('<III', cdb, 1)
    if routine != MEM:
        raise RuntimeError('unknown routine - refused')
    if direction == 'out':
        ok = cb == NONE and stub.LOAD <= addr and addr + length <= stub.BUF and 0 < length <= 64
        what = 'upload helper'
    elif cb == NONE:
        ok = 0 < length <= 256 and ((s3.ROM_BASE <= addr and addr + length <= s3.ROM_BASE + s3.ROM_SIZE) or
                                    (stub.LOAD <= addr and addr + length <= stub.BUF + stub.BUF_LEN))
        what = 'read ROM/scratch'
    else:
        ok = (STATE['stub_verified'] and addr == stub.BUF and
              ((cb == stub.JEDEC_AT and length == 3) or (cb == stub.READ_AT and 0 < length <= stub.BUF_LEN)))
        what = 'run helper'
    if not ok:
        raise RuntimeError(f'{what}: {cdb.hex()} len {length} is outside the limits - refused')


def cmd(handle, cdb, length, direction='in', data=b'', timeout=5):
    check(cdb, length, direction)
    t = time.perf_counter()
    buf = ctypes.create_string_buffer(max(length, 1) + 64)
    addr = (ctypes.addressof(buf) + 63) & ~63
    if direction == 'out':
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
    n = sp.sptd.DataTransferLength
    got = ctypes.string_at(addr, n) if ok and direction == 'in' else b''
    return {'status': sp.sptd.ScsiStatus if ok else None, 'data': got, 'err': err,
            'ms': (time.perf_counter() - t) * 1000, 'sense': bytes(sp.sense[:18]).hex()}


def cdb_mem(addr, callback=NONE, flash=0):
    return (b'\xcb' + struct.pack('<III', MEM, addr, callback) +
            bytes([flash & 0xff, flash >> 8 & 0xff, flash >> 16 & 0xff]))


def retry(handle, cdb, length, direction='in', data=b'', tries=4, what=''):
    for k in range(1, tries + 1):
        r = cmd(handle, cdb, length, direction, data)
        if r['status'] == 0 and (direction == 'out' or len(r['data']) == length):
            return r
        s3.show(f'{what} try {k}', r)
        time.sleep(0.3)
    return None


def read_rom(h):
    data = bytearray()
    for a in range(s3.ROM_BASE, s3.ROM_BASE + s3.ROM_SIZE, 256):
        r = retry(h, cdb_mem(a), 256, what=f'ROM {a:#x}')
        if r is None:
            return None
        data += r['data']
    return bytes(data)


def read_flash(h, size, label):
    data = bytearray()
    t0 = time.monotonic()
    for a in range(0, size, 256):
        r = retry(h, cdb_mem(stub.BUF, stub.READ_AT, a), 256, what=f'{label} @{a:#08x}')
        if r is None:
            log(f'{label}: kept failing at {a:#08x} - stopped.')
            return None
        data += r['data']
        if a % (512 * 1024) == 0 and a:
            log(f'  {label}: {a // 1024} KiB of {size // 1024} ({time.monotonic() - t0:.0f} s)')
    log(f'{label}: {len(data)} bytes in {time.monotonic() - t0:.0f} s, sha256 {hashlib.sha256(data).hexdigest()}')
    return bytes(data)


def main():
    log('RECEIPT QUEST - firmware backup (read only)  ' + dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    if not ctypes.windll.shell32.IsUserAnAdmin():
        log('Not admin - run 3_BACKUP.bat and click Yes.')
        return
    path = s3.enter_loader()
    if not path:
        return
    h, err = s2.open_dev(path)
    if h is None:
        log(f'could not open the loader disk (error {err})')
        return
    outdir = os.path.join(HERE, 'firmware_backup_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S'))
    report = {'started': dt.datetime.now().isoformat(timespec='seconds'), 'flash_written': False}
    try:
        st, _, inq = s2.scsi(h, bytes([0x12, 0, 0, 0, 64, 0]), 64)
        if st != 0 or inq != s2.PENGUIN_INQUIRY:
            log(f'loader ID differs ({st}, {inq.hex()}) - stopped.')
            return
        log('loader ID ok')

        rom = read_rom(h)
        if rom is None or hashlib.sha256(rom).hexdigest() != s3.PENGUIN_ROM_SHA:
            log('chip ROM did not read back as the known ROM - stopped before uploading anything.')
            return
        log('chip ROM verified (sha256 62d4dabe...)')

        img = stub.image()
        for off in range(0, len(img), 64):
            piece = img[off:off + 64]
            if retry(h, cdb_mem(stub.LOAD + off), len(piece), 'out', piece, what='upload') is None:
                log('helper upload failed - stopped.')
                return
        back = bytearray()
        for off in range(0, len(img), 256):
            n = min(256, len(img) - off)
            r = retry(h, cdb_mem(stub.LOAD + off), n, what='read back helper')
            if r is None:
                log('could not read the helper back - stopped.')
                return
            back += r['data']
        if bytes(back) != img:
            log('helper did not land exactly - stopped before running it.')
            return
        STATE['stub_verified'] = True
        log(f'helper uploaded and verified ({len(img)} bytes, sha256 {hashlib.sha256(img).hexdigest()[:16]}...)')

        r = retry(h, cdb_mem(stub.BUF, stub.JEDEC_AT), 3, what='flash ID')
        if r is None:
            log('flash ID read failed - stopped.')
            return
        jid = r['data']
        log(f'flash chip ID (JEDEC): {jid.hex(" ")}')
        report['jedec'] = jid.hex()
        if jid[0] in (0x00, 0xFF) or not 0x10 <= jid[2] <= 0x19:
            log('that does not look like a working SPI flash answer - stopped (nothing read).')
            return
        size = 1 << jid[2]
        log(f'flash size from ID: {size // 1024} KiB')
        report['size'] = size

        r1 = read_flash(h, size, 'flash read 1')
        if r1 is None:
            return
        r2 = read_flash(h, size, 'flash read 2')
        if r2 is None:
            return
        os.makedirs(outdir)
        for name, data in (('flash_read1.bin', r1), ('flash_read2.bin', r2)):
            with open(os.path.join(outdir, name), 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        same = r1 == r2
        report.update(reads_identical=same, sha256_read1=hashlib.sha256(r1).hexdigest(),
                      sha256_read2=hashlib.sha256(r2).hexdigest())
        if not same:
            diffs = [hex(a) for a in range(0, size, 4096) if r1[a:a + 4096] != r2[a:a + 4096]]
            report['differing_4k_sectors'] = diffs
            log(f'the two reads DIFFER in {len(diffs)} sector(s): {diffs[:10]} - both kept, no BACKUP file made')
        else:
            with open(os.path.join(outdir, 'BACKUP_firmware.bin'), 'wb') as f:
                f.write(r1)
                f.flush()
                os.fsync(f.fileno())
        # sanity: what the camera itself told us
        checks = {'boot header BLDR': r1[4:8] == b'BLDR',
                  'version 20240822_V1.9': b'20240822_V1.9' in r1,
                  'chip AX3291A': b'AX3291A' in r1,
                  'not blank': r1.count(b'\xff') < len(r1) * 0.95}
        report['checks'] = checks
        for k, v in checks.items():
            log(f'  {k}: {"yes" if v else "NO"}')
        with open(os.path.join(outdir, 'report.json'), 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        log(f'saved in {outdir}')
        log('\nVERDICT:')
        log('  BACKUP COMPLETE - two identical full reads' if same and all(checks.values()) else
            '  backup NOT confirmed - see above')
        if same:
            fits, why = rq_packs.check_backup(r1)
            report['matches_tested_firmware'] = fits
            with open(os.path.join(outdir, 'report.json'), 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            log('\nIS THIS CAMERA THE TESTED ONE?')
            for line in why:
                log(line)
            log('  YES - the mods in this folder fit this camera. Keep this backup folder safe.' if fits else
                '  NO - do not install anything. Keep the backup anyway; it is your way back.')
    finally:
        s2.k32.CloseHandle(h)
        time.sleep(0.5)
        log('\nletting go of the loader: ' + s3.eject_loader())
        index = s2.wait_for_camera(60)
        log('camera is back in normal USB mode with its card' if index is not None else
            'camera not back yet - unplug the USB cable, wait 10 s, plug it back in')
        log('backup step done - nothing was written to the flash.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log(traceback.format_exc())
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(LINES) + '\n')
