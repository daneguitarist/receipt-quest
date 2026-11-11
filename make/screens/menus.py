"""Receipt Quest camera screens in MOTES's TRACKING look.

res68  switch-on screen   -> PLAY >   (VCR on-screen display, dark tape)
res67  switch-off screen  -> STOP []
res78  USB screen         -> DUBBING >> PC
res39  main menu          -> dark tape background, five dim icons
res40..44 big icons       -> the selected icon, drawn by the camera over res39
                             at fixed spots (found by matching the stock art)

The big icons are 100x90 BMPs the camera pastes over the menu picture, so each
one is cut from the very same background (taken from the DECODED menu JPEG at
its edges), which keeps the boxes invisible. The OSD text uses the same crisp
bitmap font as the photo frames, so the start-up PLAY matches the PLAY frame.
"""
import io
import os
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from tracking import TRACK, tracking

W, H = 320, 240
F = ImageFont.load_default_imagefont()
STOCK = os.environ.get('RQ_STOCK', 'stock')   # PNGs from extract_resources.py
# where the camera pastes each 100x90 big icon over the menu (matched against the stock art)
BIG = {40: ('camera', 3, 14), 44: ('video', 109, 14), 41: ('gallery', 216, 14),
       43: ('settings', 2, 125), 42: ('power', 107, 133)}
BIG_W, BIG_H = 100, 90


# ------------------------------------------------------------------ OSD text
def text_mask(s, scale):
    m = Image.new('L', (len(s) * 6 + 2, 11), 0)
    ImageDraw.Draw(m).text((0, 0), s, font=F, fill=255)
    m = m.point(lambda v: 255 if v > 127 else 0)
    return np.asarray(m.resize((m.width * scale, m.height * scale), Image.NEAREST)) > 0


def osd(a, s, x, y, scale=3, col=(240, 240, 232), ghost=True):
    """VCR on-screen text: dark outline, slight red/cyan ghost, a little line jitter."""
    m = text_mask(s, scale)
    h, w = m.shape
    pad = np.zeros((h + 2 * scale, w + 2 * scale), bool)
    pad[scale:scale + h, scale:scale + w] = m
    outline = ndimage.binary_dilation(pad, iterations=max(1, scale // 2 + 1))
    region = a[y - scale:y - scale + pad.shape[0], x - scale:x - scale + pad.shape[1]]
    region[outline] = region[outline] * 0.25 + np.array((8, 6, 16)) * 0.75
    if ghost:
        g = np.roll(pad, 2, axis=1)
        region[g & ~pad] = region[g & ~pad] * 0.55 + np.array(TRACK['rose']) * 0.45
        g = np.roll(pad, -2, axis=1)
        region[g & ~pad] = region[g & ~pad] * 0.6 + np.array((40, 200, 220)) * 0.4
    region[pad] = col
    return w


def play_triangle(a, x, y, size, col=(240, 240, 232)):
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.polygon([(x - 2, y - 2), (x - 2, y + size + 2), (x + size * 0.8 + 3, y + size / 2)], fill=(8, 6, 16))
    d.polygon([(x, y), (x, y + size), (x + size * 0.8, y + size / 2)], fill=col)
    return np.asarray(im).astype(float)


def stop_square(a, x, y, size, col=(240, 240, 232)):
    a[y - 2:y + size + 2, x - 2:x + size + 2] = (8, 6, 16)
    a[y:y + size, x:x + size] = col
    return a


# ------------------------------------------------------------------ dark tape backdrop
def tape_backdrop(seed, base=(20, 16, 58), noise=14):
    rng = np.random.default_rng(seed)
    a = np.zeros((H, W, 3)) + base
    yy = np.arange(H)[:, None]
    a *= (0.75 + 0.25 * np.cos((yy - H / 2) / H * np.pi))[..., None]        # darker top and bottom
    a += rng.normal(0, noise, (H, W, 1)) * np.array([0.8, 0.8, 1.2])         # grain
    for _ in range(6):                                                       # soft lighter bands
        r, h = rng.integers(0, H), rng.integers(2, 10)
        a[r:r + h] += rng.uniform(4, 12)
    return a


def tape_damage(a, seed, band=None, heads=True):
    """Tracking band of torn noisy lines, head-switch tear at the bottom, dropouts, scanlines."""
    rng = np.random.default_rng(seed)
    if band:
        y0, h = band
        for r in range(y0, min(H, y0 + h)):
            k = 1 - abs((r - y0) - h / 2) / (h / 2 + 1)
            a[r] = np.roll(a[r], int(rng.integers(-4, 9)), axis=0)
            on = rng.random(W) < 0.35 * k
            a[r, on] = rng.integers(90, 235, (on.sum(), 1))
            if rng.random() < 0.35:
                x = int(rng.integers(0, W - 40))
                a[r, x:x + int(rng.integers(15, 70))] = np.array(TRACK['paper']) * 0.85
    if heads:
        for r in range(H - 6, H):
            a[r] = np.roll(a[r], 6 + int(rng.integers(0, 10)), axis=0)
            a[r] += rng.normal(0, 22, (W, 1))
    for _ in range(int(rng.integers(2, 5))):
        r, x0, L = int(rng.integers(0, H - 8)), int(rng.integers(0, W)), int(rng.integers(6, 36))
        a[r, x0:x0 + L] = np.array(TRACK['paper']) * 0.9
    a[1::2] *= 0.86
    return a


def screen_play():
    a = tape_backdrop(68)
    x = 22
    w = osd(a, 'PLAY', x, 22, scale=5)
    a = play_triangle(a, x + w + 6, 26, 40)
    osd(a, 'SP', 22, 196, scale=2)
    osd(a, '0:00:00', 58, 196, scale=2)
    return tape_damage(a, 680, band=(150, 16))


def screen_stop():
    a = tape_backdrop(67, base=(16, 12, 44))
    x = 22
    w = osd(a, 'STOP', x, 22, scale=5)
    a = stop_square(a, x + w + 8, 28, 36)
    osd(a, 'SP', 22, 196, scale=2)
    osd(a, '0:00:00', 58, 196, scale=2)
    return tape_damage(a, 670, band=(108, 22))


def screen_usb():
    a = tape_backdrop(78, base=(18, 14, 52))
    w = osd(a, 'DUBBING', 22, 22, scale=4)
    osd(a, 'CAM', 40, 100, scale=4)
    for k in range(2):
        a = play_triangle(a, 128 + k * 24, 102, 32, col=TRACK['orange'])
    osd(a, 'PC', 196, 100, scale=4)
    osd(a, 'SP', 22, 196, scale=2)
    return tape_damage(a, 780, band=(160, 12))


# ------------------------------------------------------------------ main menu
def stock(i):
    return np.asarray(Image.open(f'{STOCK}/res{i:02d}.png').convert('RGB')).astype(float)


def icon_alpha(rgb, min_px=60):
    """Line-art icons: big blobs of strongly coloured pixels (cores > 120 chroma, the pale leaves stay
    below that), plus their soft edges. Small blobs (sparkles, leaf specks) are left to the background."""
    chroma = rgb.max(2) - rgb.min(2)
    lab, n = ndimage.label(chroma > 120)
    sizes = ndimage.sum(np.ones(chroma.shape), lab, range(1, n + 1))
    keep = np.isin(lab, [k + 1 for k, s in enumerate(sizes) if s >= min_px])
    keep = ndimage.binary_dilation(keep, iterations=2)
    return np.clip((chroma - 60) / 100, 0, 1) * keep


def yellow(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (r > 200) & (g > 150) & (b < 140)


def night(rgb):
    """Pale stock background -> night tape: near-white becomes deep purple, the pale leaves dim teal."""
    lum = (0.3 * rgb[..., 0] + 0.59 * rgb[..., 1] + 0.11 * rgb[..., 2]) / 255
    d = np.clip((1 - lum) / 0.35, 0, 1)[..., None]           # 0 on the white, 1 on the leaves
    base = np.array((14, 9, 30), float)
    leaf = np.array((22, 58, 72), float)
    return base * (1 - d) + leaf * d


def menu_background(seed=39):
    s = stock(39)
    alpha = np.zeros(s.shape[:2])
    for i, (name, x, y) in BIG.items():
        alpha[y:y + BIG_H, x:x + BIG_W] = np.maximum(alpha[y:y + BIG_H, x:x + BIG_W],
                                                     icon_alpha(s[y:y + BIG_H, x:x + BIG_W]))
    # fill the icons with the surrounding background before recolouring
    bg = s.copy()
    filled = ndimage.grey_dilation(np.where(alpha[..., None] > 0, 0, s), size=(9, 9, 1))
    bg[alpha > 0] = filled[alpha > 0]
    for _ in range(3):
        blur = ndimage.uniform_filter(bg, size=(7, 7, 1))
        bg[alpha > 0] = blur[alpha > 0]
    sparkle = yellow(s) & (alpha == 0)                                 # the little stars stay, in orange
    a = night(bg)
    a[sparkle] = np.array(TRACK['orange']) * 0.8
    img = tracking(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), amount=0.5, seed=seed,
                   blocks=False, band_y=112)
    return np.asarray(img).astype(float)


def icon_layer(rgb_stock, colour, glow=False, split=1):
    """Recolour stock line art: alpha from the stock icon, colour ours, red/cyan plates apart."""
    al = icon_alpha(rgb_stock)
    col = np.array(colour, float)
    lay = np.zeros(rgb_stock.shape)
    lay[...] = col
    a3 = al[..., None]
    if split:
        r = np.roll(al, split, axis=1)[..., None]
        b = np.roll(al, -split, axis=1)[..., None]
        ghost = np.concatenate([r * 0.9, np.minimum(r, b) * 0.3, b * 0.9], 2)
    else:
        ghost = np.zeros_like(lay)
    if glow:
        g = ndimage.gaussian_filter(al, 2.2)[..., None]
        return lay, a3, ghost, g
    return lay, a3, ghost, None


def put_icon(a, x, y, rgb_stock, colour, glow=False, ghost_col=(255, 64, 168)):
    lay, a3, ghost, g = icon_layer(rgb_stock, colour, glow)
    h, w = a3.shape[:2]
    reg = a[y:y + h, x:x + w]
    if g is not None:
        reg[:] = reg + g * np.array(colour) * 0.55
    gr = ghost[..., :1]
    reg[:] = reg * (1 - gr * 0.5) + gr * 0.5 * np.array(ghost_col)
    gb = ghost[..., 2:]
    reg[:] = reg * (1 - gb * 0.35) + gb * 0.35 * np.array((40, 200, 220))
    reg[:] = reg * (1 - a3) + lay * a3
    return a


DIM = (40, 120, 132)            # unselected icons: dim teal tape
LIT = (255, 156, 40)            # the selected one: hot orange, glowing


def jpeg_roundtrip(a, quality):
    buf = io.BytesIO()
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(buf, 'JPEG', quality=quality, subsampling=2)
    return np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert('RGB')).astype(float), buf.getvalue()


def build_menu(quality=88):
    bg = menu_background()
    s39 = stock(39)
    menu = bg.copy()
    for i, (name, x, y) in BIG.items():                    # the small icons sit inside each big box
        crop = s39[y:y + BIG_H, x:x + BIG_W]
        put_icon(menu, x, y, crop, DIM)
    # res44's last 196 bytes (its top row from x=34 on) share a flash sector with the sounds, so they stay
    # stock: a pale line. The same line goes into the menu itself - a tape dropout that is always there.
    menu[BIG[44][2], BIG[44][1] + 34:BIG[44][1] + BIG_W] = stock(44)[0, 34:]
    menu = np.clip(menu, 0, 255)
    dec, jpg = jpeg_roundtrip(menu, quality)
    bigs = {}
    for i, (name, x, y) in BIG.items():
        # edges from what the camera will actually show (the decoded menu), the middle from the clean background
        tile = dec[y:y + BIG_H, x:x + BIG_W].copy()
        inner = icon_alpha(s39[y:y + BIG_H, x:x + BIG_W]) > 0
        inner = ndimage.binary_dilation(inner, iterations=6)
        tile[inner] = bg[y:y + BIG_H, x:x + BIG_W][inner]
        put_icon(tile, 0, 0, stock(i), LIT, glow=True)
        if i == 44:
            tile[0, 34:] = stock(44)[0, 34:]                # the stock bytes that must not change
        bigs[i] = np.clip(tile, 1, 255)                     # never pure black, just in case
    return menu, jpg, bigs


def selected_view(menu_dec, bigs, i):
    a = menu_dec.copy()
    name, x, y = BIG[i]
    a[y:y + BIG_H, x:x + BIG_W] = bigs[i]
    return a


if __name__ == '__main__':
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else 'menus_preview.png'
    menu, jpg, bigs = build_menu()
    dec = np.asarray(Image.open(io.BytesIO(jpg)).convert('RGB')).astype(float)
    tiles = [('switch-on (PLAY)', screen_play()), ('switch-off (STOP)', screen_stop()),
             ('USB / PC', screen_usb()), ('main menu', dec)]
    for i in (40, 44, 41, 43, 42):
        tiles.append((f'{BIG[i][0]} selected', selected_view(dec, bigs, i)))
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    S = Image.new('RGB', (cols * 340 + 20, rows * 280 + 20), (12, 10, 18))
    d = ImageDraw.Draw(S)
    for k, (name, a) in enumerate(tiles):
        x, y = 20 + (k % cols) * 340, 20 + (k // cols) * 280
        S.paste(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), (x, y))
        d.text((x, y + 244), name, fill=(200, 200, 200), font=F)
    S.save(out)
    print('menu jpeg', len(jpg), 'bytes')


# ------------------------------------------------------------------ settings list (res71) + selected bar (res64 #1)
BAR_X, BAR_Y0, BAR_DY, BAR_W, BAR_H = 98, 42, 40, 200, 37     # stock res71's four bars
BAR_FILL, BAR_EDGE = np.array((20, 40, 56), float), np.array((60, 132, 140), float)
SEL_RING, SEL_FILL = 21, 196             # res65 palette entries: orange (255,101,0), dark navy (32,32,65)


def night_inv(rgb):
    """Neutral pixels: luminance flipped onto the tape ramp (pale -> deep purple, dark lines -> cream);
    coloured pixels keep their hue, darkened."""
    lum = (0.3 * rgb[..., 0] + 0.59 * rgb[..., 1] + 0.11 * rgb[..., 2]) / 255
    t = np.clip(1 - lum, 0, 1)
    stops = np.array([(14, 9, 30), (22, 58, 72), (110, 170, 160), (236, 226, 204)], float)
    pos = np.array([0.0, 0.25, 0.6, 1.0])
    ramp = np.stack([np.interp(t, pos, stops[:, c]) for c in range(3)], -1)
    chroma = rgb.max(2) - rgb.min(2)
    sat = np.clip((chroma - 50) / 80, 0, 1)[..., None]
    warm = (rgb[..., 0] > rgb[..., 2])[..., None]           # orange / yellow / red -> tape pink, blue -> teal
    tone = np.where(warm, np.array(TRACK['rose'], float), np.array(TRACK['teal'], float))
    tone = tone * (0.45 + 0.55 * lum[..., None])
    return ramp * (1 - sat) + tone * sat


def settings_screen(seed=71, amount=0.8):
    """v2 (Dane: more degraded, less video-game): the bars are painted in BEFORE the tape damage, so they
    smear, bleed, ghost and wander with everything else. They stay dark so the camera's white text reads."""
    s = stock(71)
    r, b = s[..., 0], s[..., 2]
    bar_a = np.clip((r - b) / 212.0, 0, 1)
    region = np.zeros(bar_a.shape, bool)
    for k in range(4):
        y = BAR_Y0 + k * BAR_DY
        region[y - 2:y + BAR_H + 2, BAR_X - 2:BAR_X + BAR_W + 2] = True
    bar_a = (bar_a * region)[..., None]
    bg = s.copy()
    bg[bar_a[..., 0] > 0.02] = np.array((236, 243, 251), float)
    a = night_inv(bg)
    rng = np.random.default_rng(seed + 1)
    bar = np.zeros_like(a) + np.array((36, 38, 64), float)
    yy = np.arange(H)[:, None, None]
    bar += 10 * np.sin(yy / 3.0)                                    # uneven tape, not flat buttons
    bar[..., 1:] += rng.normal(0, 3, (H, W, 1))
    a = a * (1 - bar_a) + bar * bar_a
    img = tracking(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), amount=amount, seed=seed,
                   blocks=False, band_y=214)
    out = np.asarray(img).astype(float)
    out = tape_damage(out, seed + 2, band=(12, 9), heads=False)       # a second, thinner tracking tear up top
    for _ in range(3):                                                  # a few slid blocks, bars included
        x0, y0 = int(rng.integers(40, 250)), int(rng.integers(30, 200))
        w0, h0 = int(rng.integers(20, 60)), int(rng.integers(3, 8))
        out[y0:y0 + h0, x0:x0 + w0] = np.roll(out[y0:y0 + h0, x0:x0 + w0], int(rng.integers(-12, 13)), axis=1)
    lum = out.mean(2, keepdims=True)
    out = out * 0.8 + lum * 0.2                                         # a bit washed out
    return out


def res64_entry(fw, n):
    at, _ = slot_of(fw, 64)
    w, h, o = struct.unpack_from('<III', fw, at + 12 + 12 * n)
    return at + o, w, h


def slot_of(fw, i):
    off, size = struct.unpack_from('<II', fw, 0xb1600 + 8 * i)
    return 0xb1600 + off, size


def palette(fw):
    at, size = slot_of(fw, 65)
    P = []
    for k in range(256):
        c, a = struct.unpack_from('<HH', fw, at + 4 * k)
        P.append(((c >> 11 & 31) * 255 // 31, (c >> 5 & 63) * 255 // 63, (c & 31) * 255 // 31, a))
    return np.array(P)


def selected_bar(fw, variant='mix'):
    """res64 sprite #1 (the camera's 'selected' bar, 200x40, palette indices), worn-tape version: scan-lined
    dark fill, a faded dusty-pink edge broken by scanlines, no round button - just a small arrow with a
    ghost, a few rows slipped sideways and a dropout. Colours from the camera's own palette only (res65 is
    not touched)."""
    at, w, h = res64_entry(fw, 1)
    idx = np.frombuffer(fw[at:at + w * h], np.uint8).reshape(h, w)
    shape = idx != 0
    rng = np.random.default_rng(64)
    inner = ndimage.binary_erosion(shape, iterations=2)
    edge, ghost, fill_a, fill_b, arrow, drop = {
        'pink': (177, 173, 196, 8, 30, 151),
        'lav': (184, 193, 196, 192, 30, 151),
        'mix': (177, 173, 196, 192, 30, 151),
    }[variant]
    new = np.zeros((h, w), np.uint8)
    rows = np.arange(h)[:, None]
    new[shape & inner] = np.where((rows % 2 == 0) & np.ones((1, w), bool), fill_a, fill_b)[shape & inner]
    ring = shape & ~inner
    new[ring] = np.where((rows % 2 == 0) & np.ones((1, w), bool), edge, fill_a)[ring]
    # small play arrow near the right end (where the camera's round button was) + a faded ghost to its left
    ax, ay = 172, 12
    for k in range(14):
        half = int(round(7 - abs(k - 6.5)))
        if half > 0:
            new[ay + k, ax - 3:ax - 3 + half] = ghost
            new[ay + k, ax:ax + half] = arrow
    # a dropout streak and rows slipped sideways (tracking)
    new[33, 14:44] = drop
    for r0 in (5, 6, 30, 31):
        sh = int(rng.integers(2, 6))
        new[r0] = np.roll(new[r0], sh)
    assert new.shape == (h, w)
    return at, new.tobytes()


def draw_sprite(a, fw, n, x, y, idx_bytes=None):
    at, w, h = res64_entry(fw, n)
    idx = np.frombuffer(idx_bytes if idx_bytes is not None else fw[at:at + w * h], np.uint8).reshape(h, w)
    P = palette(fw)
    rgb, al = P[idx][..., :3].astype(float), (P[idx][..., 3] / 31.0)[..., None]
    reg = a[y:y + h, x:x + w]
    reg[:] = reg * (1 - al) + rgb * al
    return a


def settings_mock(fw, page, sel, sel_bytes=None, font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
    """Approximation of what the camera shows: our res71 + its own icons, selected bar and white text."""
    a = settings_screen()
    icons, words = page
    for k, (ic, word) in enumerate(zip(icons, words)):
        y = BAR_Y0 - 1 + k * BAR_DY
        if k == sel:
            draw_sprite(a, fw, 1, BAR_X, y, sel_bytes)
        if ic is not None:
            draw_sprite(a, fw, ic, 56, y)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    ft = ImageFont.truetype(font_path, 15)
    for k, word in enumerate(words):
        if word:
            tw = d.textlength(word, font=ft)
            d.text((BAR_X + (BAR_W - tw) / 2 - (8 if k == sel else 0), BAR_Y0 + k * BAR_DY + 9), word,
                   font=ft, fill=(255, 255, 255))
    return np.asarray(im).astype(float)
