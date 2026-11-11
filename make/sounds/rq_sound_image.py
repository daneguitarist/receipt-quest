"""Builds the target flash image: a stock backup with new sounds dropped into the
camera's 7 sound slots, in place, same sizes (only the audio bytes change; the
camera's own WAV headers are kept as they are).

    python rq_sound_image.py BACKUP.bin SLOT_FIT_DIR OUT.bin [shutter|all]
"""
import hashlib
import struct
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'install'))
import rq_packs  # noqa: E402  (checks a backup against the tested firmware)


# resource number, flash offset, stored size, file from camera_slot_fit, role
SLOTS = [
    (28, 0x1f1e4b, 3396, 'slot01_click_b.wav', 'click (22 kHz stereo)'),
    (45, 0x2280c6, 1932, 'slot02_click_d.wav', 'click'),
    (46, 0x228852, 2638, 'slot03_click_a.wav', 'click'),
    (47, 0x2292a0, 2064, 'slot04_click_c.wav', 'click'),
    (48, 0x229ab0, 58352, 'slot05_poweroff.wav', 'power-off'),     # heard at switch-off on the real camera
    (49, 0x237ea0, 51824, 'slot06_poweron.wav', 'power-on'),       # and res49 at switch-on
    (50, 0x244910, 13296, 'slot07_shutter.wav', 'shutter'),
]
HEADER = 44


def load_slot_file(path):
    """The WAV as plain fmt + data (44-byte header). Extra chunks some file
    transfers add (e.g. a C2PA provenance tag) are ignored."""
    d = open(path, 'rb').read()
    assert d[:4] == b'RIFF' and d[8:12] == b'WAVE', f'{path}: not a WAV'
    chunks, j = {}, 12
    while j + 8 <= len(d):
        cid, cl = d[j:j + 4], struct.unpack_from('<I', d, j + 4)[0]
        chunks.setdefault(cid, d[j + 8:j + 8 + cl])
        j += 8 + cl + (cl & 1)
    fmt, data = chunks[b'fmt '], chunks[b'data']
    body = b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', len(data)) + data
    return b'RIFF' + struct.pack('<I', len(body)) + body


def resource_table(d):
    base = struct.unpack_from('<I', d, 0x18)[0] * 512
    first = struct.unpack_from('<I', d, base)[0]
    return {i: (base + struct.unpack_from('<II', d, base + 8 * i)[0], struct.unpack_from('<II', d, base + 8 * i)[1])
            for i in range(first // 8)}


def build(backup, fit_dir, which='all'):
    assert rq_packs.check_backup(backup)[0], 'the backup does not match the tested firmware'
    table = resource_table(backup)
    out = bytearray(backup)
    used = []
    for res, off, size, name, role in SLOTS:
        if which == 'shutter' and res != 50:
            continue
        assert table[res] == (off, size), f'resource {res} moved: {table[res]}'
        new = load_slot_file(f'{fit_dir}/{name}')
        stock = backup[off:off + size]
        assert stock[:4] == b'RIFF' and new[:HEADER] == stock[:HEADER], f'{name}: header differs from the camera'
        n = min(size, len(new))
        out[off + HEADER:off + n] = new[HEADER:n]          # audio bytes only
        used.append((res, role, name, n - HEADER))
    return bytes(out), used


def changed_sectors(a, b):
    return sorted({k & ~0xfff for k in range(len(a)) if a[k] != b[k]})


if __name__ == '__main__':
    backup = open(sys.argv[1], 'rb').read()
    which = sys.argv[4] if len(sys.argv) > 4 else 'all'
    img, used = build(backup, sys.argv[2], which)
    open(sys.argv[3], 'wb').write(img)
    for res, role, name, n in used:
        print(f'res{res} {role:22s} <- {name} ({n} audio bytes)')
    secs = changed_sectors(backup, img)
    print(f'{len(secs)} sectors change: {", ".join(hex(s) for s in secs)}')
    print('sha256', hashlib.sha256(img).hexdigest())
