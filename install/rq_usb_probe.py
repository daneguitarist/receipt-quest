"""Receipt Quest USB probe - STEP 1 (look only).

Identifies the camera over USB and proves this PC can send it SCSI commands.
It sends ONLY standard, read-only SCSI commands that every USB drive answers:
  TEST UNIT READY (0x00), INQUIRY (0x12), READ CAPACITY(10) (0x25).
No vendor/hidden commands, no writes. Any other opcode is refused in code.

Needs administrator rights (Windows only lets admin programs send raw SCSI
commands), so 1_FIND_CAMERA.bat asks once via the normal Windows prompt.
Results go to log_find_camera.txt.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'log_find_camera.txt')
LINES = []

ALLOWED_OPCODES = {0x00, 0x12, 0x25}          # read-only, standard

IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x4D014
SCSI_IOCTL_DATA_IN = 1
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value


def log(s=''):
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


def ps_json(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd + ' | ConvertTo-Json -Depth 3'],
                       capture_output=True, text=True, timeout=60)
    if not r.stdout.strip():
        return []
    d = json.loads(r.stdout)
    return d if isinstance(d, list) else [d]


def scsi(handle, cdb, length):
    if cdb[0] not in ALLOWED_OPCODES:
        raise RuntimeError(f'opcode {cdb[0]:#04x} is not allowed in step 1')
    k32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(max(length, 1) + 64)
    addr = (ctypes.addressof(buf) + 63) & ~63                 # 64-byte aligned
    s = SPTDWithSense()
    s.sptd.Length = ctypes.sizeof(SPTD)
    s.sptd.CdbLength = len(cdb)
    s.sptd.SenseInfoLength = 32
    s.sptd.DataIn = SCSI_IOCTL_DATA_IN
    s.sptd.DataTransferLength = length
    s.sptd.TimeOutValue = 5
    s.sptd.DataBuffer = addr if length else None
    s.sptd.SenseInfoOffset = SPTDWithSense.sense.offset
    for i, b in enumerate(cdb):
        s.sptd.Cdb[i] = b
    ret = wt.DWORD()
    ok = k32.DeviceIoControl(handle, IOCTL_SCSI_PASS_THROUGH_DIRECT,
                             ctypes.byref(s), ctypes.sizeof(s),
                             ctypes.byref(s), ctypes.sizeof(s),
                             ctypes.byref(ret), None)
    if not ok:
        return None, f'DeviceIoControl failed, Windows error {k32.GetLastError()}', b''
    data = ctypes.string_at(addr, s.sptd.DataTransferLength) if length else b''
    return s.sptd.ScsiStatus, bytes(s.sense[:18]).hex(), data


def main():
    log('RECEIPT QUEST USB PROBE - step 1 (look only)')
    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    log(f'running as admin: {is_admin}')

    log('\n-- USB devices from the camera chip makers (BuildWin 1908 / 0219) --')
    devs = ps_json("Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_1908|VID_0219' } "
                   "| Select-Object Status, Class, FriendlyName, InstanceId")
    for d in devs:
        log(f"  {d.get('Status')}  {d.get('Class')}  {d.get('FriendlyName')}  {d.get('InstanceId')}")
    if not devs:
        log('  none found - is the camera plugged in and showing its USB screen?')

    log('\n-- disks --')
    disks = ps_json("Get-CimInstance Win32_DiskDrive | Select-Object Index, Model, InterfaceType, "
                    "PNPDeviceID, Size, MediaType")
    cam = None
    for d in disks:
        log(f"  disk {d.get('Index')}: {d.get('Model')} [{d.get('InterfaceType')}] {d.get('PNPDeviceID')}")
        if 'BUILDWIN' in str(d.get('PNPDeviceID', '')).upper() or 'Buildwin' in str(d.get('Model', '')):
            cam = d
    if cam is None:
        log('\nNo Buildwin camera disk found - nothing was sent to anything.')
        return
    path = rf"\\.\PhysicalDrive{int(cam['Index'])}"
    log(f'\ncamera disk: {path}  ({cam.get("Model")})')
    if not is_admin:
        log('Not admin - cannot send SCSI commands. Run 1_FIND_CAMERA.bat and click Yes.')
        return

    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = ctypes.c_void_p
    h = k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, 0, None)
    if h in (None, INVALID_HANDLE):
        log(f'could not open the camera disk, Windows error {k32.GetLastError()}')
        return
    try:
        st, sense, _ = scsi(h, bytes(6), 0)
        log(f'TEST UNIT READY: status={st} sense={sense}')
        st, sense, data = scsi(h, bytes([0x12, 0, 0, 0, 36, 0]), 36)
        log(f'INQUIRY: status={st} sense={sense}')
        if data:
            log(f'  vendor  = {data[8:16]!r}')
            log(f'  product = {data[16:32]!r}')
            log(f'  rev     = {data[32:36]!r}')
            log(f'  raw     = {data.hex()}')
        st, sense, data = scsi(h, bytes([0x25] + [0] * 9), 8)
        log(f'READ CAPACITY: status={st} sense={sense}')
        if len(data) == 8:
            last, bs = int.from_bytes(data[:4], 'big'), int.from_bytes(data[4:], 'big')
            log(f'  {last + 1} blocks x {bs} bytes = {(last + 1) * bs / 1e9:.2f} GB')
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))
    log('\nstep 1 done - only standard read-only commands were sent.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log(traceback.format_exc())
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(LINES) + '\n')
