"""Receipt Quest photo frames: 21 overlays for the camera's frame slots.

Rules learned from the stock frames: pure black = the photo shows through;
anything drawn is kept at luma >= 64 (the stock frames' darkest visible colour
is grey 49). Designed on a 320x180 grid (one design pixel = one pixel on the
camera's screen) and scaled x4 to 1280x720. Text is chunky so it survives the
print (1280 wide -> 384 printer dots)."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 320, 180
F = ImageFont.load_default_imagefont()      # the crisp bitmap font, no smoothing
MIN_LUMA = 64

C = {'white': (255, 255, 255), 'cream': (255, 238, 214), 'paper': (238, 238, 210), 'grey': (150, 150, 150),
     'ink': (66, 66, 66), 'teal': (34, 160, 170), 'mint': (110, 196, 186), 'pink': (255, 64, 168),
     'orange': (255, 146, 20), 'rose': (250, 70, 150), 'red': (235, 60, 60), 'yellow': (250, 220, 60),
     'cyan': (60, 220, 230), 'green': (80, 220, 110), 'blue': (90, 110, 255), 'magenta': (230, 70, 230),
     'purple': (150, 90, 200), 'mid': (120, 120, 120)}


class Canvas:
    def __init__(self, seed):
        self.im = Image.new('RGB', (W, H), (0, 0, 0))
        self.d = ImageDraw.Draw(self.im)
        self.rng = np.random.default_rng(seed)

    def rect(self, box, col, outline=None):
        x0, y0, x1, y1 = box
        box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        fill = C.get(col, col) if isinstance(col, str) else col
        line = (C.get(outline, outline) if isinstance(outline, str) else outline) if outline else None
        self.d.rectangle(box, fill=fill, outline=line)

    def text(self, s, x, y, col='white', scale=1, shadow=None):
        m = Image.new('L', (len(s) * 6 + 2, 11), 0)
        ImageDraw.Draw(m).text((0, 0), s, font=F, fill=255)
        m = m.point(lambda v: 255 if v > 127 else 0).resize((m.width * scale, m.height * scale), Image.NEAREST)
        if shadow:
            self.im.paste(Image.new('RGB', m.size, C.get(shadow, shadow)), (x + scale, y + scale), m)
        self.im.paste(Image.new('RGB', m.size, C.get(col, col)), (x, y), m)
        return m.width

    def tw(self, s, scale=1):
        return (len(s) * 6) * scale

    # ---------- degradation (only where something is drawn, unless over=True) ----------
    def arr(self):
        return np.asarray(self.im).astype(float)

    def put(self, a):
        self.im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        self.d = ImageDraw.Draw(self.im)

    def tape(self, amount=0.5, rows=None):
        """TRACKING damage on drawn pixels: plates apart, line wander, noise."""
        a = self.arr()
        drawn = a.max(2) > 0
        s = 1 + int(2 * amount)
        b = a.copy()
        b[..., 0] = np.roll(a[..., 0], s, 1)
        b[..., 2] = np.roll(a[..., 2], -s, 1)
        rows = range(H) if rows is None else rows
        for r in rows:
            if self.rng.random() < 0.3 * amount:
                b[r] = np.roll(b[r], int(self.rng.integers(-2, 3)), 0)
        b += self.rng.normal(0, 14 * amount, b.shape)
        keep = drawn | (b.max(2) > 90)
        b[~keep] = 0
        self.put(b)

    def dropouts(self, n, col='paper'):
        for _ in range(n):
            y, x, L = self.rng.integers(0, H), self.rng.integers(0, W), self.rng.integers(4, 26)
            self.rect((x, y, x + L, y), col)

    def stutter(self, y0, h, x0, bw, span):
        a = self.arr()
        piece = a[y0:y0 + h, x0:x0 + bw].copy()
        for x in range(x0 + bw, min(W, x0 + span), bw):
            w = min(bw, W - x)
            a[y0:y0 + h, x:x + w] = piece[:, :w]
        self.put(a)

    def finish(self):
        """1280x720, drawn pixels lifted to luma >= MIN_LUMA, everything else pure black."""
        a = self.arr()
        drawn = a.max(2) > 8
        y = a @ np.array([0.299, 0.587, 0.114])
        low = drawn & (y < MIN_LUMA)
        if low.any():
            a[low] += (MIN_LUMA - y[low])[:, None] + 2
        a[~drawn] = 0
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        return im.resize((W * 4, H * 4), Image.NEAREST)


# ------------------------------------------------------------------ the frames
def sierra(c, score='Score:7 of 210', cmd='>look at face_'):
    c.rect((0, 0, W - 1, 12), 'white')
    c.rect((0, 13, W - 1, 13), 'ink')
    c.text(score, 4, 1, 'ink')
    c.text('Sound:on', W - c.tw('Sound:on') - 4, 1, 'ink')
    c.rect((0, H - 13, W - 1, H - 1), 'white')
    c.rect((0, H - 14, W - 1, H - 14), 'ink')
    c.text(cmd, 4, H - 12, 'ink')


def f_sierra1(c):
    sierra(c)


def f_sierra2(c):
    sierra(c, 'Score:0 of 158', '>eat receipt_')
    c.tape(0.25, rows=range(H - 14, H))


def f_vhs_play(c):
    c.text('PLAY', 10, 8, 'white', 2, shadow='ink')
    c.d.polygon([(64, 10), (64, 28), (76, 19)], fill=C['white'])
    c.text('SP', W - 30, 8, 'white', 2, shadow='ink')
    c.text('0:13:37', W - 92, H - 26, 'white', 2, shadow='ink')
    for r in range(H - 9, H):                     # head-switch tear along the bottom
        x = int(c.rng.integers(0, 40))
        c.rect((x, r, W - 1, r), (int(c.rng.integers(70, 200)),) * 3)
    c.tape(0.6, rows=range(H - 10, H))
    c.dropouts(5)


def f_vhs_rec(c):
    c.d.ellipse((10, 10, 22, 22), fill=C['red'])
    c.text('REC', 28, 8, 'white', 2, shadow='ink')
    c.rect((W - 46, 10, W - 18, 22), None, 'white')
    c.rect((W - 18, 13, W - 15, 19), 'white')
    c.rect((W - 44, 12, W - 36, 20), 'white')         # one bar left
    for (x, y, dx, dy) in ((8, 34, 1, 1), (W - 9, 34, -1, 1), (8, H - 10, 1, -1), (W - 9, H - 10, -1, -1)):
        c.rect((min(x, x + 18 * dx), y, max(x, x + 18 * dx), y + dy), 'white')
        c.rect((x, min(y, y + 14 * dy), x + dx, max(y, y + 14 * dy)), 'white')
    c.text('TAPE 001  STBY', 10, H - 22, 'cream', 1)
    c.dropouts(3)


def f_tracking(c):
    for r in list(range(0, 10)) + list(range(H - 16, H)):
        x0 = int(c.rng.integers(0, 60))
        col = c.rng.choice(['teal', 'pink', 'mint', 'purple', 'cream'])
        c.rect((x0, r, W - 1, r), col)
    band = int(c.rng.integers(60, 110))
    for r in range(band, band + 6):
        for _ in range(6):
            x, L = int(c.rng.integers(0, W)), int(c.rng.integers(4, 30))
            c.rect((x, r, x + L, r), c.rng.choice(['grey', 'cream', 'teal']))
    c.rect((20, 140, 60, 147), 'rose')
    c.rect((250, 22, 290, 29), (60, 200, 120))
    c.tape(0.9)
    c.stutter(H - 16, 8, 30, 8, 140)


def f_datamosh(c):
    for side in (0, 1):
        for y in range(0, H, 8):
            n = int(c.rng.integers(0, 6))
            for k in range(n):
                x = k * 8 if side == 0 else W - 8 - k * 8
                col = tuple(int(v) for v in c.rng.integers(70, 255, 3))
                c.rect((x, y, x + 7, y + 7), col)
    c.stutter(64, 8, 0, 8, 90)
    c.stutter(120, 16, W - 120, 8, W)
    c.tape(0.4)


def f_rotting_film(c):
    for y0 in (0, H - 16):
        c.rect((0, y0, W - 1, y0 + 15), 'mid')
        for x in range(6, W, 20):
            if c.rng.random() < 0.8:
                c.rect((x, y0 + 4, x + 9, y0 + 11), (0, 0, 0))
    c.text('400  EXPIRED 1987', 6, 3, 'orange')
    for _ in range(14):                               # rot: holes eaten into the strip
        x, y, r = int(c.rng.integers(0, W)), int(c.rng.choice([int(c.rng.integers(0, 16)), int(c.rng.integers(H - 16, H))])), int(c.rng.integers(2, 8))
        c.d.ellipse((x - r, y - r, x + r, y + r), fill=(0, 0, 0))
        c.d.ellipse((x - r - 1, y - r - 1, x + r + 1, y + r + 1), outline=C['orange'])
    c.tape(0.3)


def f_receipt(c):
    c.rect((0, 0, W - 1, 30), 'paper')
    for x in range(0, W, 6):
        c.d.polygon([(x, 31), (x + 3, 35), (x + 6, 31)], fill=C['paper'])
    c.text('GERBILHAMSTER RECORDS', 6, 2, 'ink')
    c.text('RECEIPT #000117    1x FACE ..... $0.03', 6, 12, 'ink')
    c.text('TOTAL 0.03 MEGAPIXELS', 6, 21, 'ink')
    c.rect((0, H - 16, W - 1, H - 1), 'paper')
    for x in range(0, W, 6):
        c.d.polygon([(x, H - 17), (x + 3, H - 21), (x + 6, H - 17)], fill=C['paper'])
    c.text('*** NO REFUNDS ***  THANK YOU', 40, H - 13, 'ink')
    c.dropouts(2, 'grey')


def f_cctv(c):
    c.text('CAM 03', 8, 6, 'white', 2, shadow='ink')
    c.d.ellipse((W - 62, 9, W - 52, 19), fill=C['red'])
    c.text('REC', W - 48, 6, 'white', 2, shadow='ink')
    c.text('1970-01-01  00:00:00', 8, H - 18, 'white', 1, shadow='ink')
    cx, cy = W // 2, H // 2
    for dx, dy in ((-30, -24), (30, -24), (-30, 24), (30, 24)):
        sx, sy = (1 if dx < 0 else -1), (1 if dy < 0 else -1)
        c.rect((cx + dx, cy + dy, cx + dx + 8 * sx, cy + dy), 'white') if sx > 0 else c.rect((cx + dx - 8, cy + dy, cx + dx, cy + dy), 'white')
        c.rect((cx + dx, min(cy + dy, cy + dy + 6 * sy), cx + dx, max(cy + dy, cy + dy + 6 * sy)), 'white')
    for r in range(0, H, 6):                           # faint scan lines over the edges only
        c.rect((0, r, 6, r), 'grey'); c.rect((W - 7, r, W - 1, r), 'grey')
    c.tape(0.35)


def f_evidence(c):
    c.rect((8, 8, 92, 34), 'paper', 'ink')
    c.text('EXHIBIT', 14, 10, 'ink')
    c.text('A', 64, 10, 'red', 2)
    c.text('CASE 0017', 14, 22, 'ink')
    c.rect((10, H - 22, W - 11, H - 10), 'paper')
    for k, x in enumerate(range(12, W - 12, 6)):
        c.rect((x, H - 22, x, H - 22 + (8 if k % 5 == 0 else 4)), 'ink')
    c.text('cm', W - 26, H - 21, 'ink')


def f_illegal(c):
    x0, y0, x1, y1 = 8, H - 70, 200, H - 8
    c.rect((x0, y0, x1, y1), (192, 192, 192), 'white')
    c.rect((x0 + 2, y0 + 2, x1 - 2, y0 + 13), (60, 60, 200))
    c.text('CAMERA.EXE', x0 + 5, y0 + 3, 'white')
    c.text('This face has performed an', x0 + 6, y0 + 18, 'ink')
    c.text('illegal operation and will', x0 + 6, y0 + 28, 'ink')
    c.text('be printed.', x0 + 6, y0 + 38, 'ink')
    c.rect((x1 - 42, y1 - 16, x1 - 8, y1 - 5), (210, 210, 210), 'ink')
    c.text('OK', x1 - 31, y1 - 16, 'ink')
    c.tape(0.2)


def f_missing(c):
    c.rect((0, 0, W - 1, 30), 'paper')
    c.text('MISSING', (W - c.tw('MISSING', 3)) // 2, 0, 'ink', 3)
    c.rect((0, H - 20, W - 1, H - 1), 'paper')
    c.text('HAVE YOU SEEN THIS PERSON?', (W - c.tw('HAVE YOU SEEN THIS PERSON?')) // 2, H - 16, 'ink')
    a = c.arr()                                         # photocopy toner specks + a streak
    paper = a.max(2) > 0
    noise = c.rng.random(a.shape[:2]) < 0.06
    a[paper & noise] = 90
    a[:, 250:253][a[:, 250:253].max(2) > 0] = 110
    c.put(a)


def f_dither(c):
    a = np.zeros((H, W, 3))
    yy, xx = np.mgrid[0:H, 0:W]
    edge = np.minimum(np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy))
    bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16
    level = np.clip(1 - edge / 22, 0, 1)
    on = (edge < 22) & (bayer[yy % 4, xx % 4] < level)
    a[on] = (150, 170, 140)
    a[edge < 3] = (200, 215, 185)
    c.put(a)
    for (x, y) in ((14, 12), (W - 30, 14), (20, H - 26), (W - 26, H - 24)):
        c.rect((x, y, x + 6, y + 6), (230, 240, 210))
        c.rect((x + 2, y - 2, x + 4, y + 8), (230, 240, 210))


def f_arcade(c):
    c.text('1UP', 10, 4, 'red', 1); c.text('000300', 10, 14, 'white', 1)
    c.text('HIGH SCORE', (W - c.tw('HIGH SCORE')) // 2, 4, 'red'); c.text('999990', (W - c.tw('999990')) // 2, 14, 'white')
    c.text('INSERT COIN', (W - c.tw('INSERT COIN', 2)) // 2, H - 26, 'yellow', 2)
    c.text('CREDIT 0', W - c.tw('CREDIT 0') - 8, H - 12, 'white')
    c.dropouts(2, 'cyan')


def f_teletext(c):
    c.rect((0, 0, W - 1, 11), (0, 0, 0))
    c.text('P100', 4, 1, 'white'); c.text('GHR', 40, 1, 'yellow'); c.text('TEXT', 62, 1, 'cyan'); c.text('100', 96, 1, 'white')
    cols = ['cyan', 'yellow', 'magenta', 'green', 'white', 'red', 'blue']
    for y in range(13, 37, 4):                          # mosaic graphics header
        for x in range(0, W, 4):
            if c.rng.random() < 0.55:
                c.rect((x, y, x + 3, y + 3), cols[(x // 24 + y // 8) % len(cols)])
    c.text(' RECEIPT QUEST  ', 70, 18, 'white', 2, shadow='blue')
    c.rect((0, H - 12, W - 1, H - 1), 'blue')
    c.text('NEWS  WEATHER  TAPE  FACES', 6, H - 11, 'yellow')


def f_nosignal(c):
    """Colour bars that also work on thermal paper: each bar carries its own dot density
    (solid -> sparse), so they print as clearly different greys, not seven near-whites."""
    bars = [((215, 215, 215), 0.00), ((205, 185, 45), 0.15), ((60, 180, 190), 0.30), ((45, 170, 55), 0.45),
            ((185, 50, 185), 0.60), ((200, 40, 40), 0.75), ((60, 60, 225), 0.90)]
    bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16
    a = c.arr()
    y0 = H - 28
    for k, (col, dark) in enumerate(bars):
        x0, x1 = k * W // len(bars), (k + 1) * W // len(bars)
        yy, xx = np.mgrid[y0:H, x0:x1]
        dots = bayer[yy % 4, xx % 4] < dark
        block = np.empty(dots.shape + (3,))
        block[...] = col
        block[dots] = (70, 70, 70)
        a[y0:H, x0:x1] = block
    c.put(a)
    c.rect((W // 2 - 58, 7, W // 2 + 58, 27), (52, 52, 150), 'white')
    c.text('NO SIGNAL', W // 2 - c.tw('NO SIGNAL', 2) // 2, 9, 'white', 2)
    c.tape(0.5, rows=range(H - 28, H))


def f_broken_jpeg(c):
    y0 = int(H * 0.72)
    for x in range(0, W, 8):
        col = tuple(int(v) for v in c.rng.integers(70, 255, 3))
        c.rect((x, y0 - 8, x + 7, y0 - 1), col) if c.rng.random() < 0.7 else None
    c.rect((0, y0, W - 1, H - 1), (128, 128, 128))
    c.stutter(y0 - 8, 8, 40, 8, 200)


GERBIL = ["..........##....",
          ".........####...",
          "...######o####..",
          "..###########NN.",
          ".#############..",
          ".############...",
          "..##..##..##...."]
HAMSTER = [".##......##.",
           "###########.",
           "############",
           "##o######o##",
           "############",
           "#####NN#####",
           ".##########.",
           "..########..",
           "..##....##.."]


def sprite(c, rows, x, y, body, s=4, light=None):
    cols = {'#': body, 'o': C['white'], 'N': C['pink']}
    for v, row in enumerate(rows):
        for u, ch in enumerate(row):
            if ch in cols:
                c.rect((x + u * s, y + v * s, x + u * s + s - 1, y + v * s + s - 1), cols[ch])


def f_gerbils(c):
    sprite(c, GERBIL, 8, H - 34, (205, 150, 95))
    c.rect((8 - 30, H - 18, 8 + 3, H - 17), (205, 150, 95))          # the long gerbil tail
    c.rect((0, H - 18, 8, H - 17), (205, 150, 95))
    sprite(c, HAMSTER, W - 56, H - 42, (235, 200, 130))
    c.rect((W - 80, 6, W - 8, 30), 'cream', 'orange')
    c.text('GHR', W - 80 + (72 - c.tw('GHR', 3)) // 2, 7, 'orange', 3)
    c.text('GERBILHAMSTER RECORDS', 8, 8, 'cream', 1, shadow='ink')


def f_loading(c):
    c.text('LOADING FACE... 43%', 10, H - 30, 'white', 1, shadow='ink')
    c.rect((10, H - 18, W - 11, H - 10), None, 'white')
    c.rect((12, H - 16, 12 + int((W - 24) * 0.43), H - 12), 'mint')
    c.text('56k', W - 30, 6, 'grey')
    for _ in range(9):                                   # blocks that never arrived
        x, y = int(c.rng.integers(0, W // 8)) * 8, int(c.rng.integers(0, 3)) * 8
        c.rect((x, y, x + 7, y + 7), (140, 140, 140))


def f_waveform(c):
    t = np.arange(W)
    rng = c.rng
    env = np.abs(np.sin(t / 37.0)) * 8 + rng.random(W) * 6
    for x in range(W):
        h = int(env[x])
        c.rect((x, 14 - h, x, 14 + h), 'teal' if x % 3 else 'mint')
        h2 = int(env[(x * 7) % W])
        c.rect((x, H - 15 - h2, x, H - 15 + h2), 'teal' if x % 4 else 'cream')
    for _ in range(40):                                   # grains: dust in the air
        x, y = int(rng.integers(0, W)), int(rng.choice([int(rng.integers(0, 30)), int(rng.integers(H - 30, H))]))
        c.rect((x, y, x, y), 'orange')
    c.text('REC LEVEL -3dB', W - c.tw('REC LEVEL -3dB') - 6, 34, 'cream')


def f_printer_test(c):
    for x in range(0, W, 2):
        c.rect((x, 0, x, 7), 'white') if (x // 2) % 2 == 0 else None
    for k in range(16):                                   # grey ramp
        v = 64 + k * 12
        c.rect((k * 20, H - 14, k * 20 + 19, H - 1), (v, v, v))
    for y in range(10, H - 16, 4):
        c.rect((W - 10 + (y // 4) % 2 * 4, y, W - 7 + (y // 4) % 2 * 4, y + 1), 'white')
    c.text('PRINTER TEST  384 DOTS  //////', 6, 10, 'white')


# ------------------------------------------------------------------ more VHS
def noise_band(c, y0, h, density=0.55, tear=True):
    """A band of tape noise across the picture: bright specks, black gaps let the photo through."""
    a = c.arr()
    for r in range(y0, min(H, y0 + h)):
        k = 1 - abs((r - y0) - h / 2) / (h / 2 + 1)            # thickest in the middle of the band
        on = c.rng.random(W) < density * (0.4 + 0.6 * k)
        v = c.rng.integers(70, 255, W)
        a[r, on] = np.stack([v[on]] * 3, 1)
        if tear and c.rng.random() < 0.5:
            x = int(c.rng.integers(0, W - 40))
            a[r, x:x + int(c.rng.integers(20, 90))] = (238, 238, 210)
    c.put(a)


def snow(c, n, margin=None):
    for _ in range(n):
        x, y = int(c.rng.integers(0, W)), int(c.rng.integers(0, H))
        if margin and margin < x < W - margin and margin < y < H - margin:
            continue
        v = int(c.rng.integers(90, 255))
        c.rect((x, y, x, y), (v, v, v))


def osd(c, s, x, y, scale=2, col='white'):
    return c.text(s, x, y, col, scale, shadow='ink')


def f_vhs_pause(c):
    osd(c, 'PAUSE', 10, 8)
    c.rect((76, 9, 79, 25), 'white'); c.rect((84, 9, 87, 25), 'white')
    noise_band(c, int(H * 0.68), 12)
    noise_band(c, int(H * 0.68) + 30, 4, 0.3, tear=False)
    osd(c, 'SP', W - 30, 8)


def f_vhs_ff(c):
    osd(c, 'FF', 10, 8)
    c.d.polygon([(40, 10), (40, 26), (50, 18)], fill=C['white'])
    c.d.polygon([(50, 10), (50, 26), (60, 18)], fill=C['white'])
    osd(c, 'x16', W - 44, 8)
    for y0 in (40, 96, 148):                                   # fast-forward bars rolling through
        noise_band(c, y0, 7, 0.45)
    c.tape(0.3)


def f_vhs_rew(c):
    c.d.polygon([(30, 10), (30, 26), (20, 18)], fill=C['white'])
    c.d.polygon([(40, 10), (40, 26), (30, 18)], fill=C['white'])
    osd(c, 'REW', 46, 8)
    osd(c, '-0017', W - 70, H - 26)
    snow(c, 900, margin=26)
    noise_band(c, 120, 6, 0.4)


def f_vhs_tracking_bar(c):
    osd(c, 'TRACKING', (W - c.tw('TRACKING', 2)) // 2, H - 44)
    x0, y0 = 70, H - 20
    c.text('-', x0 - 12, y0 - 2, 'white', 2, shadow='ink')
    c.text('+', x0 + 186, y0 - 2, 'white', 2, shadow='ink')
    for k in range(12):
        c.rect((x0 + k * 15, y0, x0 + k * 15 + 10, y0 + 10), 'white' if k < 7 else (110, 110, 110))
    noise_band(c, 18, 10, 0.5)


def f_vhs_channel(c):
    osd(c, 'CH 03', W - 72, 8)
    osd(c, 'VIDEO 1', 10, 8, 1)
    osd(c, 'TIMER REC  --:--', 10, H - 18, 1)
    osd(c, 'AUTO TRACKING', W - c.tw('AUTO TRACKING') - 10, H - 18, 1, 'mint')
    c.tape(0.4)
    snow(c, 300, margin=14)


def f_vhs_label(c):
    x0, y0, x1, y1 = W - 132, H - 50, W - 8, H - 8                # the cassette label sticker
    c.rect((x0, y0, x1, y1), 'paper', 'grey')
    for y in range(y0 + 12, y1, 9):
        c.rect((x0 + 4, y, x1 - 4, y), (170, 190, 220))
    c.text('DO NOT', x0 + 8, y0 + 3, 'red', 1)
    c.text('TAPE OVER!!', x0 + 8, y0 + 13, 'red', 1)
    c.text('faces vol.3', x0 + 8, y0 + 25, (60, 60, 160), 1)
    osd(c, 'PLAY', 10, 8)
    c.d.polygon([(62, 10), (62, 26), (72, 18)], fill=C['white'])
    noise_band(c, H - 10, 10, 0.5)


FRAMES = [f_sierra1, f_vhs_play, f_receipt, f_tracking, f_cctv, f_missing, f_evidence, f_illegal, f_vhs_pause,
          f_teletext, f_vhs_rew, f_datamosh, f_nosignal, f_broken_jpeg, f_vhs_ff, f_loading, f_vhs_rec,
          f_vhs_tracking_bar, f_vhs_channel, f_vhs_label, f_sierra2]          # final set (Dane, 2026-11-08)
EXTRA_VHS = [f_vhs_rew, f_vhs_tracking_bar, f_vhs_channel, f_vhs_label]      # candidates to swap in


def build_all(frames=None):
    out = []
    for k, f in enumerate(frames or FRAMES):
        c = Canvas(seed=1000 + k)
        f(c)
        out.append((f.__name__[2:], c.finish()))
    return out
