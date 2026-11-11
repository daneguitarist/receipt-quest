"""Receipt Quest USB probe - STEP 2b ("hold the ROM door open").

Step 2 proved the camera enters its chip's boot-ROM loader (USB 1908:3319) on
command 0xDA and comes back by itself. The loader only stayed ~1.6 s because
nobody talked to it - Windows was still installing drivers for a device it had
never seen.

This step repeats the same restart (up to 3 tries - Windows finishes its driver
setup a bit more each time) and, as soon as the loader appears as a disk,
talks to it with ONLY the standard questions it answers by itself:
TEST UNIT READY (0x00), INQUIRY (0x12) and REQUEST SENSE (0x03). It keeps it
awake for 6 seconds, then lets go so the loader's watchdog restarts the camera.

The loader's answers are compared with the penguin-camera project's copy of the
same chip ROM: if they match, everything that project learned about the loader
should apply to this camera too.

No memory reads, no code, nothing written anywhere. Log: log_prepare_usb.txt
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'log_prepare_usb.txt')
LINES = []
T0 = [None]

ALLOWED_OPCODES = {0x00, 0x03, 0x12, 0xDA}
KEEP_AWAKE_S = 6.0
TRIES = 3

# what the penguin camera's ROM (assets/rom/soc_boot_rom.bin, sha256 62d4dabe...)
# sends for INQUIRY (ROM 0x105e08, 49 bytes) and REQUEST SENSE (ROM 0x105e3c, 18 bytes)
PENGUIN_INQUIRY = bytes.fromhex(
    '0080 0202 2c00 0000 4275 696c 6457 696e 5669 6465 6f30 3530 4c6f 6164 6572 2020'
    '312e 3030 2e31 2e30 3020 5468 756e 6465 72')
PENGUIN_SENSE = bytes.fromhex('7000 0200 0000 000a 0000 0000 3a00 0000 0000')

IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x4D014
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080
FSCTL_LOCK_VOLUME = 0x90018
FSCTL_DISMOUNT_VOLUME = 0x90020
SCSI_IOCTL_DATA_IN, SCSI_IOCTL_DATA_UNSPECIFIED = 1, 2
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
OPEN_EXISTING = 3
INVALID = ctypes.c_void_p(-1).value

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
k32.CreateFileW.restype = wt.HANDLE
k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
                                wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.DeviceIoControl.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.FlushFileBuffers.argtypes = [wt.HANDLE]
k32.GetLogicalDrives.restype = wt.DWORD


def log(s=''):
    if T0[0] is not None:
        s = f'[{time.monotonic() - T0[0]:6.2f}s] {s}'
    print(s, flush=True)
    LINES.append(str(s))


class SPTD(ctypes.Structure):
    _fields_ = [('Length', ctypes.c_ushort), ('ScsiStatus', ctypes.c_ubyte),
                ('PathId', ctypes.c_ubyte), ('TargetId', ctypes.c_ubyte),
                ('Lun', ctypes.c_ubyte), ('CdbLength', ctypes.c_ubyte),
                ('SenseInfoLength', ctypes.c_ubyte), ('DataIn', ctypes.c_ubyte),
                ('DataTransferLength', ctypes.c_uint32), ('TimeOutValue', ctypes.c_uint32),
                ('DataBuffer', ctypes.c_void_p), ('SenseInfoOffset', ctypes.c_uint32),
                ('Cdb', ctypes.c_ubyte * 16)]


class SPTDWithSense(ctypes.Structure):
    _fields_ = [('sptd', SPTD), ('filler', ctypes.c_uint32), ('sense', ctypes.c_ubyte * 32)]


class STORAGE_DEVICE_NUMBER(ctypes.Structure):
    _fields_ = [('DeviceType', wt.DWORD), ('DeviceNumber', wt.DWORD), ('PartitionNumber', wt.DWORD)]


class GUID(ctypes.Structure):
    _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16), ('Data3', ctypes.c_uint16),
                ('Data4', ctypes.c_ubyte * 8)]


GUID_DEVINTERFACE_DISK = GUID(0x53f56307, 0xb6bf, 0x11d0,
                              (ctypes.c_ubyte * 8)(0x94, 0xf2, 0x00, 0xa0, 0xc9, 0x1e, 0xfb, 0x8b))


def open_dev(path, access=GENERIC_READ | GENERIC_WRITE):
    h = k32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    if h in (None, INVALID):
        return None, ctypes.get_last_error()
    return h, 0


def scsi(handle, cdb, length=0, timeout=3):
    if cdb[0] not in ALLOWED_OPCODES:
        raise RuntimeError(f'opcode {cdb[0]:#04x} is not allowed in step 2b')
    buf = ctypes.create_string_buffer(max(length, 1) + 64)
    addr = (ctypes.addressof(buf) + 63) & ~63
    s = SPTDWithSense()
    s.sptd.Length = ctypes.sizeof(SPTD)
    s.sptd.CdbLength = len(cdb)
    s.sptd.SenseInfoLength = 32
    s.sptd.DataIn = SCSI_IOCTL_DATA_IN if length else SCSI_IOCTL_DATA_UNSPECIFIED
    s.sptd.DataTransferLength = length
    s.sptd.TimeOutValue = timeout
    s.sptd.DataBuffer = addr if length else None
    s.sptd.SenseInfoOffset = SPTDWithSense.sense.offset
    for i, b in enumerate(cdb):
        s.sptd.Cdb[i] = b
    ret = wt.DWORD()
    ok = k32.DeviceIoControl(handle, IOCTL_SCSI_PASS_THROUGH_DIRECT, ctypes.byref(s), ctypes.sizeof(s),
                             ctypes.byref(s), ctypes.sizeof(s), ctypes.byref(ret), None)
    if not ok:
        return None, f'Windows error {ctypes.get_last_error()}', b''
    data = ctypes.string_at(addr, s.sptd.DataTransferLength) if length else b''
    return s.sptd.ScsiStatus, bytes(s.sense[:18]).hex(), data


def ps_json(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd + ' | ConvertTo-Json -Depth 3'],
                       capture_output=True, text=True, timeout=90)
    if not r.stdout.strip():
        return []
    d = json.loads(r.stdout)
    return d if isinstance(d, list) else [d]


# ---- fast device lists (cfgmgr32) ---------------------------------------------
cfg = ctypes.WinDLL('cfgmgr32')
cfg.CM_Get_Device_ID_List_SizeW.argtypes = [ctypes.POINTER(wt.ULONG), wt.LPCWSTR, wt.ULONG]
cfg.CM_Get_Device_ID_ListW.argtypes = [wt.LPCWSTR, ctypes.c_wchar_p, wt.ULONG, wt.ULONG]
cfg.CM_Get_Device_Interface_List_SizeW.argtypes = [ctypes.POINTER(wt.ULONG), ctypes.POINTER(GUID),
                                                   wt.LPCWSTR, wt.ULONG]
cfg.CM_Get_Device_Interface_ListW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, ctypes.c_wchar_p,
                                              wt.ULONG, wt.ULONG]


def _multi_sz(buf, n):
    return {x for x in buf[:n].split('\0') if x}


def present_ids(enumerator):
    flags = 0x1 | 0x100                                   # FILTER_ENUMERATOR | FILTER_PRESENT
    for _ in range(3):
        n = wt.ULONG()
        if cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(n), enumerator, flags):
            continue
        buf = ctypes.create_unicode_buffer(n.value + 64)
        if cfg.CM_Get_Device_ID_ListW(enumerator, buf, n.value + 64, flags) == 0:
            return _multi_sz(buf, n.value + 64)
    raise OSError('device list failed')


def disk_interfaces():
    for _ in range(3):
        n = wt.ULONG()
        if cfg.CM_Get_Device_Interface_List_SizeW(ctypes.byref(n), ctypes.byref(GUID_DEVINTERFACE_DISK), None, 0):
            continue
        buf = ctypes.create_unicode_buffer(n.value + 64)
        if cfg.CM_Get_Device_Interface_ListW(ctypes.byref(GUID_DEVINTERFACE_DISK), None, buf, n.value + 64, 0) == 0:
            return _multi_sz(buf, n.value + 64)
    return set()


def snapshot():
    ids = present_ids('USB') | present_ids('USBSTOR')
    return {i for i in ids if 'VID_1908' in i.upper() or 'VID_0219' in i.upper() or 'USBSTOR' in i.upper()}


def camera_normal(ids):
    up = ' '.join(ids).upper()
    return any(k in up for k in ('VID_0219&PID_3280', 'VID_1908&PID_3283', 'VID_1908&PID_3282'))


def loader_present(ids):
    return any('VID_1908&PID_3319' in i.upper() for i in ids)


def volumes_on_disk(index):
    out = []
    mask = k32.GetLogicalDrives()
    for i in range(3, 26):
        if not mask & (1 << i):
            continue
        letter = chr(65 + i)
        h, _ = open_dev(rf'\\.\{letter}:', 0)
        if h is None:
            continue
        try:
            sdn, ret = STORAGE_DEVICE_NUMBER(), wt.DWORD()
            if k32.DeviceIoControl(h, IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0, ctypes.byref(sdn),
                                   ctypes.sizeof(sdn), ctypes.byref(ret), None) and sdn.DeviceNumber == index:
                out.append(letter)
        finally:
            k32.CloseHandle(h)
    return out


def _camera_disk_with_card():
    if not camera_normal(snapshot()):
        return None
    disks = [d for d in ps_json('Get-CimInstance Win32_DiskDrive | Select-Object Index, Model, PNPDeviceID')
             if 'BUILDWIN' in str(d.get('PNPDeviceID', '')).upper()]
    if len(disks) != 1:
        return None
    idx = int(disks[0]['Index'])
    return idx if volumes_on_disk(idx) else None


def wait_for_camera(timeout=60):
    """Camera back in normal mode with its card mounted, and still there 4 s later
    (after a restart it can drop off USB once more while it settles)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        idx = _camera_disk_with_card()
        if idx is not None:
            time.sleep(4)
            if _camera_disk_with_card() == idx:
                return idx
        time.sleep(1)
    return None


def prepare(index):
    """Same safety checks as step 2. Returns (disk handle, volume handles) or None."""
    letters = volumes_on_disk(index)
    log(f'camera disk: PhysicalDrive{index}, card volume(s): {letters or "none"}')
    for L in letters:
        names = {n.lower() for n in os.listdir(f'{L}:\\')}
        if 'destbin.bin' in names:
            log(f'{L}:\\DestBin.bin is on the card - stopped, nothing sent.')
            return None
    h, err = open_dev(rf'\\.\PhysicalDrive{index}')
    if h is None:
        log(f'could not open the camera disk (error {err}) - nothing sent.')
        return None
    st, sense, data = scsi(h, bytes([0x12, 0, 0, 0, 36, 0]), 36)
    if st != 0 or data[8:16] != b'Buildwin' or not data[16:32].startswith(b'Media-Player'):
        log(f'INQUIRY check failed ({st}, {data[8:36]!r}) - nothing sent.')
        k32.CloseHandle(h)
        return None
    vols = []
    for L in letters:
        vh, verr = open_dev(rf'\\.\{L}:')
        if vh is None:
            log(f'could not open {L}: (error {verr}) - nothing sent.')
            break
        vols.append(vh)
        ret = wt.DWORD()
        flushed = bool(k32.FlushFileBuffers(vh))
        k32.DeviceIoControl(vh, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(ret), None)
        dismounted = bool(k32.DeviceIoControl(vh, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(ret), None))
        log(f'{L}: flushed={flushed} dismounted={dismounted}')
        if not (flushed and dismounted):
            break
    else:
        return h, vols
    k32.CloseHandle(h)
    for vh in vols:
        k32.CloseHandle(vh)
    log('could not safely detach the card - nothing sent.')
    return None


def talk_to_loader(path, result):
    h, err = open_dev(path)
    if h is None:
        log(f'could not open the loader disk (error {err})')
        return
    try:
        st, sense, data = scsi(h, bytes([0x12, 0, 0, 0, 64, 0]), 64)
        log(f'loader INQUIRY: status={st} {len(data)} bytes {data.hex()}')
        log(f'   text: {data[8:].decode("latin-1", "replace")!r}')
        result['inquiry'] = data
        st, sense, data = scsi(h, bytes([0x03, 0, 0, 0, 18, 0]), 18)
        log(f'loader REQUEST SENSE: status={st} {data.hex()}')
        result['sense'] = data
        # the loader acts like a card reader with no card: TEST UNIT READY answers
        # "not ready / medium not present" (status 2). Any answer keeps it awake.
        answered, statuses = 0, {}
        end = time.monotonic() + KEEP_AWAKE_S
        while time.monotonic() < end:
            st, sense, _ = scsi(h, bytes(6), 0)
            statuses[st] = statuses.get(st, 0) + 1
            if st is None:
                log(f'TEST UNIT READY got no answer: {sense}')
                break
            answered += 1
            time.sleep(0.25)
        log(f'kept it awake: {answered} TEST UNIT READY answered, statuses {statuses}')
        result['awake_ok'] = answered
    finally:
        k32.CloseHandle(h)
    result['released'] = time.monotonic()


def one_try(n, index):
    log(f'\n===== try {n} =====')
    prep = prepare(index)
    if prep is None:
        return {'stop': True}
    h, vols = prep
    before_ifaces = disk_interfaces()
    prev = snapshot()
    T0[0] = time.monotonic()
    try:
        log('sending 0xDA (ROM door / restart)')
        st, sense, _ = scsi(h, bytes([0xDA] + [0] * 15), 0, timeout=5)
        log(f'0xDA result: status={st}')
    finally:
        k32.CloseHandle(h)
        for vh in vols:
            k32.CloseHandle(vh)

    result = {}
    loader_in = loader_out = None
    end = time.monotonic() + 40
    while time.monotonic() < end:
        now = snapshot()
        for i in sorted(now - prev):
            log(f'+ {i}')
        for i in sorted(prev - now):
            log(f'- {i}')
        prev = now
        if loader_present(now) and loader_in is None:
            loader_in = time.monotonic()
        if loader_in and not loader_present(now) and loader_out is None:
            loader_out = time.monotonic()
            log(f'loader left after {loader_out - loader_in:.2f} s')
            if 'released' in result:
                log(f'   ({loader_out - result["released"]:.2f} s after we stopped talking)')
        if loader_in and loader_out is None and 'inquiry' not in result and result.get('opens', 0) < 5:
            new = [p for p in disk_interfaces() - before_ifaces
                   if 'usbstor' in p.lower() and 'media-player' not in p.lower()]
            if new:
                result['opens'] = result.get('opens', 0) + 1
                log(f'loader disk ready {time.monotonic() - loader_in:.2f} s after it arrived: {new[0]}')
                talk_to_loader(new[0], result)
                continue
        if loader_out and camera_normal(now):
            log('camera back in normal mode')
            break
        if loader_in is None and time.monotonic() - T0[0] > 15:
            log('no loader seen within 15 s')
            break
        time.sleep(0.02)
    if loader_in and loader_out is None:
        log('loader is STILL there - unplug the camera USB cable, wait 10 s, plug it back in')
        result['stuck'] = True
    T0[0] = None
    return result


def main():
    log('RECEIPT QUEST USB PROBE - step 2b (hold the ROM door open)')
    if not ctypes.windll.shell32.IsUserAnAdmin():
        log('Not admin - run 2_PREPARE_USB.bat and click Yes.')
        return
    result = {}
    for n in range(1, TRIES + 1):
        index = wait_for_camera(60)
        if index is None:
            log('camera is not back in normal USB mode - stopping here.')
            break
        result = one_try(n, index)
        if result.get('stop') or result.get('stuck') or 'inquiry' in result:
            break
    if 'inquiry' in result:
        index = wait_for_camera(60)
        log('camera back with its card' if index is not None else
            'camera not back yet - switch it off and on, then plug it in again')

    log('\nVERDICT:')
    if 'inquiry' in result:
        inq, sense = result['inquiry'], result.get('sense', b'')
        log(f"  talked to the ROM loader and kept it awake ({result.get('awake_ok', 0)} pings)")
        log(f"  INQUIRY same as the penguin camera's ROM: {inq[:len(PENGUIN_INQUIRY)] == PENGUIN_INQUIRY}")
        log(f"  REQUEST SENSE same as the penguin camera's ROM: {sense[:18] == PENGUIN_SENSE}")
    else:
        log('  could not reach the loader as a disk on this run')
    log('step 2b done - only standard questions were asked; nothing written anywhere.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log(traceback.format_exc())
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(LINES) + '\n')
