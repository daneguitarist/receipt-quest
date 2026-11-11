"""Build the camera-screens flash image from the verified backup.

Every new picture goes into its stock resource slot (same offset, same size in
the resource table, which is never touched):
  JPEG  -> baseline 4:2:0 like the stock screens, must fit the slot, zero padded
  BMP   -> the stock 54-byte header and 2 trailing bytes kept, only pixels new
Then checks that every changed byte is inside the screen windows below, and that
no changed sector is shared with the sounds, the frames, the resource table or
the settings sector.

  python3 build_screens.py BACKUP.bin OUTDIR
"""
import hashlib
import io
import json
import os
import struct
import sys

import numpy as np
from PIL import Image

import menus as M

BASE = 0xb1600                        # resource table (sector 0xb1, never written)
STAGE1 = ((0x201, 0x228), (0x254, 0x257), (0x2d1, 0x2da))   # main menu + big icons, selected bar, settings
STAGE2 = ((0x295, 0x2aa), (0x2f5, 0x2fd))     # switch-off + switch-on screens, USB screen
WINDOWS = STAGE1 + STAGE2
FORBIDDEN = [(0xb1, 0xb2), (0xb7, 0x1dd), (0x1f1, 0x1f3), (0x228, 0x248), (0x2ff, 0x300)]


def slot(fw, i):
    off, size = struct.unpack_from('<II', fw, BASE + 8 * i)
    return BASE + off, size


def jpeg_fit(a, budget, qualities=(92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72, 70)):
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    for q in qualities:
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=q, subsampling=2, optimize=False, progressive=False)
        d = buf.getvalue()
        if len(d) <= budget - 64:                 # a little headroom
            return d, q
    raise ValueError(f'does not fit {budget} bytes')


def bmp_pixels(stock_bytes, a):
    """Same header and trailer as stock; 24-bit bottom-up BGR rows."""
    w, h = struct.unpack_from('<ii', stock_bytes, 18)
    assert struct.unpack_from('<H', stock_bytes, 28)[0] == 24 and h > 0 and (w * 3) % 4 == 0
    px = np.clip(np.rint(a), 0, 255).astype(np.uint8)[::-1, :, ::-1]
    body = px.tobytes()
    assert len(body) == w * h * 3
    return stock_bytes[:54] + body + stock_bytes[54 + len(body):]


def build(fw):
    menu, menu_jpg, bigs = M.build_menu()
    pictures = {                                   # res -> ('jpeg', array) or ('bmp', array)
        68: ('jpeg', M.screen_play()),
        67: ('jpeg', M.screen_stop()),
        78: ('jpeg', M.screen_usb()),
        39: ('jpeg-bytes', menu_jpg),
        71: ('jpeg', M.settings_screen()),
    }
    for i, a in bigs.items():
        pictures[i] = ('bmp', a)
    out = bytearray(fw)
    info = {}
    for i, (kind, a) in sorted(pictures.items()):
        at, size = slot(fw, i)
        old = fw[at:at + size]
        if kind == 'bmp':
            new = bmp_pixels(old, a)
            q = None
        elif kind == 'jpeg-bytes':
            new, q = a, 88
            assert len(new) <= size - 64, f'res{i} too big'
        else:
            new, q = jpeg_fit(a, size)
        if kind != 'bmp':
            assert new[:2] == b'\xff\xd8' and new[-2:] == b'\xff\xd9'
            new = new + b'\0' * (size - len(new))
        assert len(new) == size
        out[at:at + size] = new
        info[f'res{i:02d}'] = {'kind': kind.split('-')[0], 'slot': size, 'used': size if kind == 'bmp' else
                               len(new.rstrip(b'\0')), 'quality': q}
    at, sel = M.selected_bar(fw)                 # res64 sprite #1: the camera's 'selected' bar
    assert len(sel) == 8000 and at == 0x254424
    out[at:at + len(sel)] = sel
    info['res64#1'] = {'kind': 'sprite', 'slot': len(sel), 'used': len(sel), 'quality': None}
    out = bytes(out)
    changed = [s for s in range(0, len(fw), 0x1000) if out[s:s + 0x1000] != fw[s:s + 0x1000]]
    for s in changed:
        n = s >> 12
        assert any(lo <= n < hi for lo, hi in WINDOWS), f'sector {s:#x} outside the screen windows'
        assert not any(lo <= n < hi for lo, hi in FORBIDDEN), f'sector {s:#x} is shared with another mod'
    return out, changed, info


def blob(img):
    return b''.join(img[lo << 12:hi << 12] for lo, hi in WINDOWS)


if __name__ == '__main__':
    fw = open(sys.argv[1], 'rb').read()
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    img, changed, info = build(fw)
    b = blob(img)
    open(os.path.join(outdir, 'screens_for_camera.bin'), 'wb').write(b)
    stage = lambda s, st: any(lo <= s >> 12 < hi for lo, hi in st)
    summary = {'blob_sha': hashlib.sha256(b).hexdigest(), 'blob_len': len(b),
               'image_sha': hashlib.sha256(img).hexdigest(),
               'stage1': [hex(s) for s in changed if stage(s, STAGE1)],
               'stage2': [hex(s) for s in changed if stage(s, STAGE2)], 'resources': info}
    print(json.dumps({k: v for k, v in summary.items() if k != 'resources'}, indent=1))
    for k, v in info.items():
        print(k, v)
    open(os.path.join(outdir, 'screens_build.json'), 'w').write(json.dumps(summary, indent=1))
    open(os.path.join(outdir, 'target_screens.bin'), 'wb').write(img)
