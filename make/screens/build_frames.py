"""Put 21 photo frames into a copy of your backup.

    python build_frames.py BACKUP.bin OUT.bin                 # the Receipt Quest frames (frames.py)
    python build_frames.py BACKUP.bin OUT.bin MY_FRAMES_DIR   # your own: res04.png .. res24.png

Each frame is a 1280x720 picture: pure black = the photo shows through, everything
else is drawn over the photo (keep drawn colours at luma >= 64; the stock frames'
darkest visible colour is grey 49). It is stored as a baseline JPEG (4:2:0) at the
highest quality that fits the stock slot, and the rest of the slot is zero-filled -
slots never move, so the camera's resource table (sector 0xb1) is never touched.

Then: python ../make_pack.py BACKUP.bin OUT.bin packs/my-frames --title "MY FRAMES" --windows 0xb7-0x1dd
"""
import io
import json
import os
import struct
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
FIRST, LAST = 4, 24                       # res04 .. res24 are the frames


def slot(fw, i):
    base = struct.unpack_from('<I', fw, 0x18)[0] * 512
    off, size = struct.unpack_from('<II', fw, base + 8 * i)
    return base + off, size


def fit(img, budget):
    for q in range(95, 40, -1):
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=q, subsampling=2, optimize=False, progressive=False)
        d = buf.getvalue()
        if len(d) <= budget:
            return d, q
    raise ValueError(f'does not fit in {budget} bytes even at quality 41 - simplify the picture')


def main(backup_path, out_path, folder=None):
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'install'))
    import rq_packs
    fw = bytearray(open(backup_path, 'rb').read())
    assert rq_packs.check_backup(bytes(fw))[0], 'the backup does not match the tested firmware'
    if folder:
        pictures = {i: Image.open(os.path.join(folder, f'res{i:02d}.png')).convert('RGB') for i in range(FIRST, LAST + 1)}
    else:
        import frames
        designs = dict(frames.build_all())
        names = json.load(open(os.path.join(HERE, 'frame_slots.json')))
        pictures = {int(k): designs[v].convert('RGB') for k, v in names.items()}
    for i in range(FIRST, LAST + 1):
        a, size = slot(fw, i)
        img = pictures[i]
        assert img.size == (1280, 720), f'res{i:02d}: must be 1280x720'
        jpg, q = fit(img, size)
        fw[a:a + size] = jpg + b'\0' * (size - len(jpg))
        print(f'res{i:02d}: {len(jpg)} of {size} bytes, quality {q}')
    open(out_path, 'wb').write(bytes(fw))


if __name__ == '__main__':
    main(*sys.argv[1:4])
