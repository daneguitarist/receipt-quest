"""List and extract the camera's built-in resources (pictures, sounds) from YOUR backup.

    python extract_resources.py BACKUP.bin OUTDIR

Writes OUTDIR/resNN.<jpg|bmp|wav|bin> exactly as stored, OUTDIR/resNN.png for every
picture (needs Pillow), and OUTDIR/resources.json: number, flash offset, size, kind,
picture size, and which 4 KiB sectors each resource touches - the starting point
for making your own sounds / frames / screens.

The resource table: the u32 at flash 0x18 times 512 is its address (0xb1600 on
firmware 20240822_V1.9); it is a list of (offset, size) u32 pairs relative to that
address, and the first offset / 8 is the number of entries. These files are the
camera maker's artwork: fine to look at and to measure, not ours to share.
"""
import json
import os
import struct
import sys


def table(fw):
    base = struct.unpack_from('<I', fw, 0x18)[0] * 512
    first = struct.unpack_from('<I', fw, base)[0]
    out = []
    for i in range(first // 8):
        off, size = struct.unpack_from('<II', fw, base + 8 * i)
        out.append((i, base + off, size))
    return base, out


def kind(b):
    if b[:2] == b'\xff\xd8':
        return 'jpg'
    if b[:2] == b'BM':
        return 'bmp'
    if b[:4] == b'RIFF' and b[8:12] == b'WAVE':
        return 'wav'
    return 'bin'


def main(path, outdir):
    fw = open(path, 'rb').read()
    base, entries = table(fw)
    os.makedirs(outdir, exist_ok=True)
    try:
        from PIL import Image
    except ImportError:
        Image = None
    info = {'table': hex(base), 'resources': []}
    for i, a, size in entries:
        b = fw[a:a + size]
        k = kind(b)
        name = f'res{i:02d}.{k}'
        with open(os.path.join(outdir, name), 'wb') as f:
            f.write(b)
        row = {'res': i, 'flash': hex(a), 'size': size, 'kind': k, 'file': name,
               'sectors': [hex(s) for s in range(a & ~0xfff, a + size, 0x1000)]}
        if k in ('jpg', 'bmp') and Image is not None:
            import io
            try:
                im = Image.open(io.BytesIO(b))
                im.load()
                row['picture'] = list(im.size)
                im.convert('RGB').save(os.path.join(outdir, f'res{i:02d}.png'))
            except Exception as e:                       # sprite atlases etc. are not plain pictures
                row['picture_error'] = str(e)
        if k == 'wav':
            ch, rate = struct.unpack_from('<HI', b, 22)
            bits = struct.unpack_from('<H', b, 34)[0]
            row['sound'] = {'rate': rate, 'channels': ch, 'bits': bits,
                            'seconds': round((size - 44) / (rate * ch * bits // 8), 3)}
        info['resources'].append(row)
        print(f"res{i:02d}  {a:#08x}  {size:7d}  {k}  {row.get('picture', '')}{row.get('sound', '')}")
    with open(os.path.join(outdir, 'resources.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
