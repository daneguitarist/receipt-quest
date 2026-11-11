"""Generate negln.inc (exposure curve table) and font.inc (PIL default bitmap font = the PC chrome font)."""
import math
from PIL import Image, ImageDraw, ImageFont

vals = [65535] + [round(-math.log(i / 255) * 1024) for i in range(1, 256)]
for name, part in (('negln_hi.inc', [v >> 8 for v in vals]), ('negln_lo.inc', [v & 255 for v in vals])):
    with open(name, 'w') as f:      # byte tables only: the camera is little-endian, the compiler big-endian
        f.write(',\n'.join(', '.join(str(v) for v in part[k:k + 16]) for k in range(0, 256, 16)) + '\n')

font = ImageFont.load_default_imagefont()
rows = []
maxw = 0
for ch in range(32, 127):
    im = Image.new('L', (8, 11), 255)
    ImageDraw.Draw(im).text((0, 0), chr(ch), font=font, fill=0)
    px = im.load()
    bits = []
    for y in range(11):
        b = 0
        for x in range(6):
            if px[x, y] < 128:
                b |= 0x20 >> x
        for x in range(6, 8):
            assert px[x, y] >= 128, (chr(ch), 'wider than 6')
        bits.append(b)
    rows.append('{' + ', '.join(f'0x{b:02x}' for b in bits) + '}')
    maxw = max(maxw, font.getbbox(chr(ch))[2])
with open('font.inc', 'w') as f:
    f.write(',\n'.join(rows) + '\n')
print('font max glyph width', maxw, '| advance per char in chrome.py text = getbbox based')
print('text width "Score:12 of 210":', font.getbbox('Score:12 of 210'))
