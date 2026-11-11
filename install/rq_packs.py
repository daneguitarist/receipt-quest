"""Receipt Quest packs: check a firmware backup and rebuild a mod from it.

A pack (packs/NAME.rqp + packs/NAME.json) holds only the NEW bytes of a mod
(sounds, pictures, code) plus "copy N bytes from stock offset X" records. The
camera's own firmware is never shipped: it is rebuilt from YOUR backup, and only
if your backup matches the tested firmware sector for sector.

No third-party packages: Python 3 standard library only.
"""
import glob
import hashlib
import json
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
SECTOR = 0x1000
SIZE = 0x400000
MAGIC = b'RQP1'
LITERAL = 0xFFFFFFFF
REFERENCE = os.path.join(HERE, 'reference', 'ax3291a_20240822_v1.9.json')


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- the patch format
def records(blob):
    if blob[:4] != MAGIC:
        raise ValueError('not a Receipt Quest pack')
    n, = struct.unpack_from('<I', blob, 4)
    p = 8
    for _ in range(n):
        dst, length, src = struct.unpack_from('<III', blob, p)
        p += 12
        data = b''
        if src == LITERAL:
            data = blob[p:p + length]
            if len(data) != length:
                raise ValueError('pack is cut short')
            p += length
        yield dst, length, src, data
    if p != len(blob):
        raise ValueError('pack has trailing bytes')


def apply(stock, blob, allowed_sectors):
    """stock flash + pack -> modded flash. Every byte written must land in an allowed
    sector; copies always read the untouched stock."""
    allowed = set(allowed_sectors)
    out = bytearray(stock)
    for dst, length, src, data in records(blob):
        if length == 0 or dst + length > len(stock):
            raise ValueError('bad record')
        for s in range(dst & ~(SECTOR - 1), dst + length, SECTOR):
            if s not in allowed:
                raise ValueError(f'pack writes outside its sectors ({s:#x})')
        if src == LITERAL:
            out[dst:dst + length] = data
        else:
            if src + length > len(stock):
                raise ValueError('bad copy record')
            out[dst:dst + length] = stock[src:src + length]
    return bytes(out)


# ---------------------------------------------------------------- the backup
def load_reference():
    with open(REFERENCE, encoding='utf-8') as f:
        return json.load(f)


def check_backup(backup):
    """-> (ok, lines). ok only if every sector except the camera's settings sector is
    byte-identical to the tested firmware (checked by sha256 per 4 KiB sector)."""
    ref = load_reference()
    lines = []
    if len(backup) != ref['size']:
        return False, [f'backup is {len(backup)} bytes, expected {ref["size"]}']
    variable = {int(x, 16) for x in ref['variable_sectors']}
    bad = []
    for i, want in enumerate(ref['sector_sha256']):
        a = i * SECTOR
        if a in variable:
            continue
        if sha(backup[a:a + SECTOR]) != want:
            bad.append(a)
    for label, ok in (('boot header BLDR', backup[4:8] == b'BLDR'),
                      ('firmware 20240822_V1.9', b'20240822_V1.9' in backup),
                      ('chip AX3291A', b'AX3291A' in backup)):
        lines.append(f'  {label}: {"yes" if ok else "NO"}')
    if bad:
        lines.append(f'  {len(bad)} of {len(ref["sector_sha256"]) - len(variable)} sectors differ from the tested '
                     f'firmware: {", ".join(hex(a) for a in bad[:12])}{" ..." if len(bad) > 12 else ""}')
        lines.append('  -> this camera is NOT the tested model/firmware (or it was already modified).')
        lines.append('     Nothing will be written. Please open an issue and paste this list (it holds no firmware).')
    else:
        lines.append('  every sector matches the tested firmware (the settings sector is allowed to differ)')
    return not bad, lines


def find_backup(root=HERE):
    """newest firmware_backup_*/BACKUP_firmware.bin that passes check_backup -> (path, bytes, lines)"""
    lines = []
    for p in sorted(glob.glob(os.path.join(root, 'firmware_backup_*', 'BACKUP_firmware.bin')), reverse=True):
        with open(p, 'rb') as f:
            d = f.read()
        ok, why = check_backup(d)
        if ok:
            return p, d, why
        lines += [p] + why
    return None, None, lines or ['no firmware_backup_*\\BACKUP_firmware.bin here - run 2_BACKUP.bat first']


# ---------------------------------------------------------------- packs
def pack_names():
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(HERE, 'packs', '*.json')))


def load_pack(name):
    with open(os.path.join(HERE, 'packs', name + '.json'), encoding='utf-8') as f:
        man = json.load(f)
    with open(os.path.join(HERE, 'packs', name + '.rqp'), 'rb') as f:
        blob = f.read()
    if man.get('format') != 'receipt-quest-pack/1':
        raise ValueError(f'{name}: unknown pack format')
    if sha(blob) != man['patch_sha256']:
        raise ValueError(f'{name}.rqp does not match {name}.json (changed or damaged)')
    return man, blob


def window_sectors(man):
    return [s for lo, hi in man['windows'] for s in range(lo * SECTOR, hi * SECTOR, SECTOR)]


def build(backup, name):
    """-> (manifest, ours) where ours = backup with the pack applied; every changed sector
    is proven (sha256) to be exactly the tested one, every other sector untouched."""
    man, blob = load_pack(name)
    allowed = window_sectors(man)
    for s, h in man['sectors'].items():
        a = int(s, 16)
        if sha(backup[a:a + SECTOR]) != h['stock']:
            raise ValueError(f'{name}: sector {s} of the backup is not the stock one')
    ours = apply(backup, blob, allowed)
    for a in range(0, len(backup), SECTOR):
        h = man['sectors'].get(hex(a))
        got = ours[a:a + SECTOR]
        if h is None:
            if got != backup[a:a + SECTOR]:
                raise ValueError(f'{name}: changes sector {a:#x} which it does not list')
        elif sha(got) != h['ours']:
            raise ValueError(f'{name}: rebuilt sector {a:#x} is not the tested one')
    return man, ours
