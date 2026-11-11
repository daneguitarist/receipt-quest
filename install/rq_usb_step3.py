"""Receipt Quest USB - STEP 3: read the chip's boot ROM through its own loader.

Uses the boot-ROM loader reached in steps 2/2b. The loader has a vendor command
0xCB whose CDB names a ROM routine to run; the penguin-camera project found the
memory-transfer routine at ROM 0x00102620 (CDB = cb | routine | address |
callback, little-endian; callback 0xFFFFFFFF = none). Here it is only used to
READ (data comes to the PC), only from the ROM itself (0x00100000-0x00107FFF),
256 bytes at a time. Every 0xCB command is checked against those limits in
code before it is sent.

Order, stopping at the first surprise:
  1. get the camera into the loader (0xDA, as in step 2b) - or use it if it is
     already there
  2. INQUIRY must match the penguin ROM's answer byte for byte
  3. 0xCB with no routine and no callback ("ping": the loader just answers OK)
  4. ONE 64-byte read of the ROM area holding the INQUIRY text - it must equal
     the text the loader already sent us, proving the routine address is right
  5. read the whole 32 KiB ROM twice; both reads must be identical
  6. compare with the penguin camera's ROM (sha256 62d4dabe...)
  7. "safely remove" the loader so it times out and restarts the camera

Saved in usb_step3_<time>\\ : rom_read1.bin, rom_read2.bin. Log: usb_step3_log.txt
No writes to anything on the camera; no code uploaded.
"""
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import hashlib
import os
import struct
import time
import traceback

import rq_usb_step2b as s2

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'usb_step3_log.txt')
LINES = []

ROM_BASE, ROM_SIZE = 0x00100000, 0x8000
MEM_ROUTINE = 0x00102620
NO_CALLBACK = 0xFFFFFFFF
CHUNK = 256
PENGUIN_ROM_SHA = '62d4dabeeca22efddc11ea0fa95a5a0823e1897e35659c9b5ae0bc47f4205eef'


def log(s=''):
    print(s, flush=True)
    LINES.append(str(s))


s2.log = log                                          # step 2b helpers log into this file


class SPT(ctypes.Structure):                         # buffered SCSI_PASS_THROUGH
    _fields_ = [('Length', ctypes.c_ushort), ('ScsiStatus', ctypes.c_ubyte),
                ('PathId', ctypes.c_ubyte), ('TargetId', ctypes.c_ubyte),
                ('Lun', ctypes.c_ubyte), ('CdbLength', ctypes.c_ubyte),
                ('SenseInfoLength', ctypes.c_ubyte), ('DataIn', ctypes.c_ubyte),
                ('DataTransferLength', ctypes.c_uint32), ('TimeOutValue', ctypes.c_uint32),
                ('DataBufferOffset', ctypes.c_size_t), ('SenseInfoOffset', ctypes.c_uint32),
                ('Cdb', ctypes.c_ubyte * 16)]


class SPTWithBuffers(ctypes.Structure):
    _fields_ = [('spt', SPT), ('filler', ctypes.c_uint32), ('sense', ctypes.c_ubyte * 32),
                ('data', ctypes.c_ubyte * 512)]


IOCTL_SCSI_PASS_THROUGH = 0x4D004


def check_cdb(cdb, length):
    """Hard limits for everything this step sends besides the 0xDA restart."""
    if cdb[0] == 0x12:
        return
    if cdb[0] != 0xCB or len(cdb) != 16:
        raise RuntimeError(f'opcode {cdb[0]:#04x} not allowed in step 3 - refused')
    routine, address, callback = struct.unpack_from('<III', cdb, 1)
    if (routine, callback) == (0, 0) and address == 0 and length == 0:
        return                                                         # ping
    if (routine, callback) != (MEM_ROUTINE, NO_CALLBACK):
        raise RuntimeError('0xCB combination not allowed - refused')
    if not (ROM_BASE <= address and address + length <= ROM_BASE + ROM_SIZE and 0 < length <= CHUNK):
        raise RuntimeError(f'read {address:#x}+{length} is outside the ROM - refused')


def raw(handle, cdb, length, buffered=False, timeout=3):
    """Send one checked command. Returns dict: status, data, err, ms, sense."""
    check_cdb(cdb, length)
    t = time.perf_counter()
    ret = wt.DWORD()
    if buffered:
        b = SPTWithBuffers()
        b.spt.Length = ctypes.sizeof(SPT)
        b.spt.CdbLength = len(cdb)
        b.spt.SenseInfoLength = 32
        b.spt.DataIn = s2.SCSI_IOCTL_DATA_IN if length else s2.SCSI_IOCTL_DATA_UNSPECIFIED
        b.spt.DataTransferLength = length
        b.spt.TimeOutValue = timeout
        b.spt.DataBufferOffset = SPTWithBuffers.data.offset
        b.spt.SenseInfoOffset = SPTWithBuffers.sense.offset
        for i, x in enumerate(cdb):
            b.spt.Cdb[i] = x
        ok = s2.k32.DeviceIoControl(handle, IOCTL_SCSI_PASS_THROUGH, ctypes.byref(b), ctypes.sizeof(b),
                                    ctypes.byref(b), ctypes.sizeof(b), ctypes.byref(ret), None)
        err = 0 if ok else ctypes.get_last_error()
        st, n = b.spt.ScsiStatus, b.spt.DataTransferLength
        data = bytes(b.data[:n]) if ok and length else b''
        sense = bytes(b.sense[:18]).hex()
    else:
        buf = ctypes.create_string_buffer(max(length, 1) + 64)
        addr = (ctypes.addressof(buf) + 63) & ~63
        sp = s2.SPTDWithSense()
        sp.sptd.Length = ctypes.sizeof(s2.SPTD)
        sp.sptd.CdbLength = len(cdb)
        sp.sptd.SenseInfoLength = 32
        sp.sptd.DataIn = s2.SCSI_IOCTL_DATA_IN if length else s2.SCSI_IOCTL_DATA_UNSPECIFIED
        sp.sptd.DataTransferLength = length
        sp.sptd.TimeOutValue = timeout
        sp.sptd.DataBuffer = addr if length else None
        sp.sptd.SenseInfoOffset = s2.SPTDWithSense.sense.offset
        for i, x in enumerate(cdb):
            sp.sptd.Cdb[i] = x
        ok = s2.k32.DeviceIoControl(handle, s2.IOCTL_SCSI_PASS_THROUGH_DIRECT, ctypes.byref(sp),
                                    ctypes.sizeof(sp), ctypes.byref(sp), ctypes.sizeof(sp),
                                    ctypes.byref(ret), None)
        err = 0 if ok else ctypes.get_last_error()
        st, n = sp.sptd.ScsiStatus, sp.sptd.DataTransferLength
        data = ctypes.string_at(addr, n) if ok and length else b''
        sense = bytes(sp.sense[:18]).hex()
    return {'status': st if ok else None, 'data': data, 'err': err,
            'ms': (time.perf_counter() - t) * 1000, 'sense': sense}


def show(name, r):
    log(f"{name}: status={r['status']} err={r['err']} {r['ms']:.0f} ms, {len(r['data'])} bytes"
        + (f" sense={r['sense']}" if r['status'] not in (0, None) else '')
        + (f"\n   {r['data'].hex()}" if r['data'] else ''))


def cb_read_cdb(address):
    return b'\xcb' + struct.pack('<III', MEM_ROUTINE, address, NO_CALLBACK) + b'\0' * 3


def loader_disk():
    for p in s2.disk_interfaces():
        if 'video050loader' in p.lower():
            return p
    return None


def enter_loader():
    """Returns the loader's disk interface path, or None."""
    p = loader_disk()
    if p:
        log('camera is already in loader mode')
        return p
    index = s2.wait_for_camera(60)
    if index is None:
        log('camera not found in normal USB mode')
        return None
    prep = s2.prepare(index)
    if prep is None:
        return None
    h, vols = prep
    try:
        log('sending 0xDA (ROM door)')
        st, _, _ = s2.scsi(h, bytes([0xDA] + [0] * 15), 0, timeout=5)
        log(f'0xDA result: status={st}')
    finally:
        s2.k32.CloseHandle(h)
        for vh in vols:
            s2.k32.CloseHandle(vh)
    end = time.monotonic() + 20
    while time.monotonic() < end:
        p = loader_disk()
        if p:
            log('loader disk ready')
            return p
        time.sleep(0.02)
    log('loader disk did not appear within 20 s')
    return None


def eject_loader():
    """'Safely remove' the loader's USB device so Windows stops polling it; the
    loader's idle watchdog then restarts the camera into its normal firmware."""
    cfg = ctypes.WinDLL('cfgmgr32')
    ids = [i for i in s2.present_ids('USB') if 'VID_1908&PID_3319' in i.upper()]
    if not ids:
        return 'loader already gone'
    inst = wt.DWORD()
    if cfg.CM_Locate_DevNodeW(ctypes.byref(inst), ids[0], 0):
        return 'could not find the loader device'
    veto_type = ctypes.c_int()
    veto_name = ctypes.create_unicode_buffer(260)
    r = cfg.CM_Request_Device_EjectW(inst, ctypes.byref(veto_type), veto_name, 260, 0)
    return f'eject result {r}, veto {veto_type.value} {veto_name.value!r}'


def main():
    log('RECEIPT QUEST USB - step 3 v2 (read the boot ROM)  ' + dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    if not ctypes.windll.shell32.IsUserAnAdmin():
        log('Not admin - run the .bat file and click Yes.')
        return
    path = enter_loader()
    if not path:
        return
    h, err = s2.open_dev(path)
    if h is None:
        log(f'could not open the loader disk (error {err})')
        return
    outdir = os.path.join(HERE, 'usb_step3_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S'))
    try:
        st, _, inq = s2.scsi(h, bytes([0x12, 0, 0, 0, 64, 0]), 64)
        if st != 0 or inq != s2.PENGUIN_INQUIRY:
            log(f'INQUIRY differs from the penguin ROM ({st}, {inq.hex()}) - stopped before any 0xCB.')
            return
        log('INQUIRY matches the penguin ROM')

        # how Windows handles the pieces of a 0xCB read, using harmless INQUIRYs first
        show('INQUIRY, 16-byte CDB', raw(h, bytes([0x12, 0, 0, 0, 64, 0]) + bytes(10), 64))
        show('INQUIRY, 16-byte CDB, buffered', raw(h, bytes([0x12, 0, 0, 0, 64, 0]) + bytes(10), 64,
                                                   buffered=True))
        r = raw(h, b'\xcb' + bytes(15), 0)
        show('0xCB ping (no routine)', r)
        if r['status'] != 0:
            log('loader did not accept 0xCB - stopped.')
            return

        buffered = False
        r = None
        for attempt in range(1, 4):
            r = raw(h, cb_read_cdb(0x00105E08), 49)
            show(f'first ROM read @0x105e08 (49 bytes), try {attempt}', r)
            if r['status'] == 0:
                break
            time.sleep(0.3)
        if r['status'] is None and r['ms'] < 500:
            log('Windows refused it before sending (fast error) - trying the buffered way')
            buffered = True
            for attempt in range(1, 3):
                r = raw(h, cb_read_cdb(0x00105E08), 49, buffered=True)
                show(f'first ROM read, buffered, try {attempt}', r)
                if r['status'] == 0:
                    break
                time.sleep(0.3)
        if r['status'] != 0 or r['data'] != s2.PENGUIN_INQUIRY:
            log('the read did not return the INQUIRY text - stopped here.')
            return
        log('routine confirmed: it returned the exact INQUIRY text from the expected ROM address')

        reads, retries = [], 0
        for n in (1, 2):
            data = bytearray()
            t = time.monotonic()
            for a in range(ROM_BASE, ROM_BASE + ROM_SIZE, CHUNK):
                for attempt in range(1, 5):
                    r = raw(h, cb_read_cdb(a), CHUNK, buffered=buffered)
                    if r['status'] == 0 and len(r['data']) == CHUNK:
                        break
                    show(f'read {n} at {a:#x}, try {attempt}', r)
                    retries += 1
                    time.sleep(0.3)
                else:
                    log(f'read {n} kept failing at {a:#x} - stopped.')
                    return
                data += r['data']
            reads.append(bytes(data))
            log(f'ROM read {n}: {len(data)} bytes in {time.monotonic() - t:.1f} s, '
                f'sha256 {hashlib.sha256(data).hexdigest()}')
        os.makedirs(outdir)
        for n, data in enumerate(reads, 1):
            with open(os.path.join(outdir, f'rom_read{n}.bin'), 'wb') as f:
                f.write(data)
        log(f'saved in {outdir}')
        same = reads[0] == reads[1]
        sha = hashlib.sha256(reads[0]).hexdigest()
        log('\nVERDICT:')
        log(f'  two reads identical: {same}   (retried blocks: {retries})')
        log(f"  identical to the penguin camera's ROM: {same and sha == PENGUIN_ROM_SHA}")
    finally:
        s2.k32.CloseHandle(h)
        time.sleep(0.5)
        log('\nletting go of the loader: ' + eject_loader())
        index = s2.wait_for_camera(60)
        log('camera is back in normal USB mode with its card' if index is not None else
            'camera not back yet - unplug the USB cable, wait 10 s, plug it back in')
        log('step 3 done - only reads from the chip ROM; nothing written to the camera.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log(traceback.format_exc())
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(LINES) + '\n')
