"""Render what the camera will show, decoded from the actual bytes in a flash image.
   python3 preview_from_image.py IMAGE.bin OUT.png [stock.bin]"""
import io, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import menus as M
BASE = 0xb1600
F = ImageFont.load_default_imagefont()


def res(fw, i):
    off, size = struct.unpack_from('<II', fw, BASE + 8 * i)
    return fw[BASE + off:BASE + off + size]


def pic(fw, i):
    return np.asarray(Image.open(io.BytesIO(res(fw, i))).convert('RGB'))


fw = open(sys.argv[1], 'rb').read()
stock = open(sys.argv[3], 'rb').read() if len(sys.argv) > 3 else None
tiles = []
for i, name in ((68, 'switch on'), (67, 'switch off'), (78, 'plugged into PC'), (39, 'main menu')):
    tiles.append((name, pic(fw, i), pic(stock, i) if stock else None))
menu = pic(fw, 39)
for i in (40, 44, 41, 43, 42):
    a = menu.copy()
    name, x, y = M.BIG[i]
    a[y:y + 90, x:x + 100] = pic(fw, i)
    b = None
    if stock:
        b = pic(stock, 39).copy()
        b[y:y + 90, x:x + 100] = pic(stock, i)
    tiles.append((f'{name} selected', a, b))
cols = 3
rows = (len(tiles) + cols - 1) // cols
S = Image.new('RGB', (cols * 340 + 20, rows * 268 + 20), (12, 10, 18))
d = ImageDraw.Draw(S)
for k, (name, a, b) in enumerate(tiles):
    x, y = 20 + (k % cols) * 340, 20 + (k // cols) * 268
    S.paste(Image.fromarray(a), (x, y))
    if b is not None:
        S.paste(Image.fromarray(b).resize((80, 60)), (x + 236, y + 176))
    d.text((x, y + 244), name, fill=(210, 210, 210), font=F)
S.save(sys.argv[2])
