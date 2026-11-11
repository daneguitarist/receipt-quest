"""Receipt Quest - turn a photo into Sierra-style 1-bit pixel art for a
384-dot thermal print head (AX3291A kids print camera).

Output: a 384 x 224 dot black/white image (the camera's print width), and a
camera-ready JPEG upscaled 6x to 2304 x 1344 - the camera's own photo size,
which its printer scales back down to exactly 384 dots.

Styles
  agi       96 x 112 pixels that are twice as wide as tall (4 x 2 dots),
            like the original AGI engine (King's Quest I-III). Whole pixels
            only; greys are checkerboards of fat pixels.
  sci       128 x 75 square pixels, 3 x 3 dots each (SCI0 era). Pure 1-bit
            pixel art: greys are checkerboards of whole pixels.
  hercules  192 x 112 pixels, 2 dots each. Every EGA colour gets its own
            texture (blue = horizontal lines, red = vertical, green =
            diagonal...), the way Sierra games looked on monochrome Hercules
            cards, so colours stay tellable-apart in black and white.
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from scipy import ndimage
from skimage import exposure

HEAD_DOTS = 384          # dots across the paper
PRINT_LINES = 224        # 2304x1344 photo / 6 = 384x224 dots
CAMERA_SCALE = 6         # camera photo pixels per printed dot

# Tone settings (tuned on a first test portrait)
TUNE = {
    'luma': np.array([0.40, 0.48, 0.12], dtype=np.float32),  # mild warm bias
    'clahe': 0.02,
    'mid': 0.58,
    'face_mid': 0.62,     # skin a light-but-printed tone, not paper white
    'clahe_face': 0.03,
}

# Classic 16-colour EGA palette (the Sierra AGI/SCI0 palette).
EGA = np.array([
    (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170),
    (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
    (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255),
    (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255),
], dtype=np.float32)

# Warm "orange filter" luminance (bright skin tones), from the penguin-camera
# project's measured print work.
LUMA_W = np.array([0.55, 0.40, 0.05], dtype=np.float32)

# 4x4 fill-order matrices: a dot is black when rank < darkness * 16.
ORDER = {
    'b': [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
    'h': [[0, 1, 2, 3], [8, 9, 10, 11], [4, 5, 6, 7], [12, 13, 14, 15]],
    'd': [[0, 4, 8, 12], [13, 1, 5, 9], [10, 14, 2, 6], [7, 11, 15, 3]],
    'o': [[12, 4, 7, 13], [5, 0, 1, 8], [6, 3, 2, 9], [14, 11, 10, 15]],
    'x': [[0, 4, 1, 5], [8, 12, 9, 13], [2, 6, 3, 7], [10, 14, 11, 15]],
}
ORDER['v'] = [list(r) for r in zip(*ORDER['h'])]
ORDER['e'] = [row[::-1] for row in ORDER['d']]
ORDER = {k: np.array(v) for k, v in ORDER.items()}


def prep(img, sat=1.4, contrast=1.0):
    """Crop to the 12:7 print shape, auto-level, boost colour (Sierra
    palettes are loud, and EGA quantising works better on loud input)."""
    img = img.convert('RGB')
    w, h = img.size
    target = HEAD_DOTS / PRINT_LINES
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    a = np.asarray(img).astype(np.float32)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    a = np.clip((a - lo) / max(hi - lo, 1) * 255, 0, 255)
    img = Image.fromarray(a.astype(np.uint8))
    img = ImageEnhance.Color(img).enhance(sat)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    return img


def analyse(img, w, h, levels, clean=1, punch=1.0, face=None):
    """Downscale to the logical grid and work out, per pixel:
    - a tone level 0 (white) .. levels-1 (black), posterised into flat
      painted areas (Sierra backgrounds are flat fills, not gradients)
    - a texture family from its hue (only the hercules style uses it)
    - a local-contrast luminance for the ink outlines."""
    small = img.resize((w, h), Image.BOX)
    a = np.asarray(small).astype(np.float32) / 255.0
    lum = a @ TUNE['luma']
    # local contrast so a face or fur keeps some detail at 96-192 pixels
    k = max(8, min(w, h) // 3)
    lum = exposure.equalize_adapthist(
        np.clip(lum, 0, 1), kernel_size=k,
        clip_limit=TUNE['clahe_face'] if face is not None else TUNE['clahe'])
    lum = np.clip(lum, 1e-4, 1)
    # auto exposure: bend the curve so the middle tone lands on TUNE['mid']
    # (bright selfies get pulled down, dark rooms get lifted)
    if face is not None:
        # meter on the face so skin isn't blown out to paper white
        cx, cy, fw, fh = face
        ya, yb = int((cy - fh * 0.4) * h), int((cy + fh * 0.4) * h)
        xa, xb = int((cx - fw * 0.4) * w), int((cx + fw * 0.4) * w)
        patch = lum[max(0, ya):max(1, yb), max(0, xa):max(1, xb)]
        med = float(np.median(patch)) if patch.size else float(np.median(lum))
        target = TUNE['face_mid']
    else:
        med = float(np.median(lum))
        target = TUNE['mid']
    gamma = np.log(target) / np.log(min(max(med, 0.05), 0.95))
    lum = lum ** np.clip(gamma, 0.5, 2.5)
    # punch > 1 pushes more pixels to solid white/black: flatter, more
    # 'painted' areas and fewer checkerboards
    lum = np.clip(0.5 + (lum - 0.5) * punch, 0, 1)
    lvl = np.clip(np.round((1 - lum) * (levels - 1)), 0, levels - 1).astype(int)
    for _ in range(clean):
        lvl = majority(lvl, levels)
    hsv = np.asarray(small.convert('HSV')).astype(np.float32)
    hue, sat = hsv[..., 0] * 360 / 255, hsv[..., 1] / 255
    fam = np.select([sat < 0.22, hue < 20, hue < 70, hue < 170, hue < 210,
                     hue < 270, hue < 330], [0, 1, 2, 3, 4, 5, 6], 1)
    for _ in range(clean):
        fam = majority(fam, 7)
    return lvl, fam, lum


def majority(lab, n):
    counts = np.stack([ndimage.uniform_filter((lab == c).astype(np.float32), 3,
                                              mode='nearest') for c in range(n)])
    best = counts.argmax(0)
    # only replace a pixel when a clear majority disagrees with it
    return np.where(counts.max(0) >= 5 / 9, best, lab)


def outlines(lum, strength):
    """Sierra-ish ink lines: mark the darker side of the strongest edges."""
    if strength <= 0:
        return np.zeros(lum.shape, bool)
    s = ndimage.gaussian_filter(lum, 0.8)
    g = np.hypot(ndimage.sobel(s, 0), ndimage.sobel(s, 1))
    thr = np.percentile(g, 100 - strength)
    darker = s < ndimage.uniform_filter(s, 3)
    return (g > thr) & darker


# hue family -> 4x4 fill order: grey=bayer, red=vertical lines,
# yellow/orange=clustered dots, green=diagonal /, cyan=diagonal \\,
# blue=horizontal lines, magenta=cross-hatch
FAMILY_ORDER = ['b', 'v', 'o', 'd', 'e', 'h', 'x']


def render_textured(lvl, fam, ink, levels, d):
    """Hercules: each hue gets its own texture, density from the tone."""
    h, w = lvl.shape
    H, W = h * d, w * d
    yy, xx = np.mgrid[0:H, 0:W]
    ty, tx = yy % 4, xx % 4
    big_l = np.repeat(np.repeat(lvl, d, 0), d, 1)
    big_f = np.repeat(np.repeat(fam, d, 0), d, 1)
    out = np.zeros((H, W), bool)  # True = black dot
    for f, key in enumerate(FAMILY_ORDER):
        m = big_f == f
        if m.any():
            rank = ORDER[key][ty, tx]
            out |= m & (rank < np.round(big_l / (levels - 1) * 16))
    out |= np.repeat(np.repeat(ink, d, 0), d, 1)
    return out


def render_pixels(lvl, ink, dx, dy):
    """Pure pixel art: whole pixels black or white, 2x2 ordered checker
    between pixels for 5 tone levels (0 white .. 4 black)."""
    h, w = lvl.shape
    yy, xx = np.mgrid[0:h, 0:w]
    bayer2 = np.array([[0, 2], [3, 1]])[yy % 2, xx % 2]
    px = (bayer2 < lvl) | ink
    return np.repeat(np.repeat(px, dy, 0), dx, 1)


# The camera's head prints real shades (heat time per dot). Measured from
# the grey-wedge print (test print 2, 2026-11-08): inputs 0-60 all print the
# same (soft) black, 75/90/105/120/135/150 step lighter, 165 and up print
# white. So the 4 flat EGA-style tones are picked from inside 0-150:
#   white 255, light grey 120 (~15% dark), dark grey 80 (~35%), black 0 (~50%)
GREY_TONES = [255, 120, 80, 0]   # index = darkness level 0..3


def render_grey(lvl, ink, dx, dy, tones=None):
    """Flat fills in real printed grey - the EGA look without dither: every
    region is one solid tone, with black ink outlines."""
    tones = np.array(tones or GREY_TONES, np.uint8)
    px = np.where(ink, 0, tones[lvl])
    return np.repeat(np.repeat(px, dy, 0), dx, 1).astype(np.uint8)


STYLES = {
    #            grid        dots(x,y) levels outline% clean punch
    'agi':      ((96, 112), (4, 2), 5, 4, 2, 1.35),
    'sci':      ((128, 75), (3, 3), 5, 4, 1, 1.25),
    'hercules': ((192, 112), (2, 2), 9, 3, 1, 1.0),
    'ega':      ((128, 75), (3, 3), 4, 5, 2, 1.1),
    # AGI's real look: fat 2:1 pixels and flat fills, no dithering at all
    'agi-grey': ((96, 112), (4, 2), 4, 4, 2, 1.2),
}


_CASCADES = None


def find_face(img):
    """Biggest face in the picture as a (cx, cy, w, h) fraction of the frame,
    or None. Uses OpenCV's stock frontal + profile detectors (both sides)."""
    global _CASCADES
    try:
        import cv2
    except ImportError:
        return None
    here = os.path.dirname(os.path.abspath(__file__))
    if _CASCADES is None:
        folder = os.path.join(here, 'models')                  # your own copies, if you add them
        if not os.path.isdir(folder):
            folder = getattr(getattr(cv2, 'data', None), 'haarcascades', '')   # the ones opencv ships
        _CASCADES = [cv2.CascadeClassifier(os.path.join(folder, n))
                     for n in ('haarcascade_frontalface_default.xml',
                               'haarcascade_profileface.xml')]
    g = np.asarray(img.convert('L'))
    s = 400 / max(g.shape)
    g = cv2.resize(g, (int(g.shape[1] * s), int(g.shape[0] * s)))
    H, W = g.shape
    found = []
    for c in _CASCADES:
        if c.empty():
            continue
        for x, y, w, h in c.detectMultiScale(g, 1.1, 4, minSize=(24, 24)):
            found.append((w * h, x, y, w, h))
        for x, y, w, h in c.detectMultiScale(g[:, ::-1].copy(), 1.1, 4,
                                             minSize=(24, 24)):
            found.append((w * h, W - x - w, y, w, h))
    if not found:
        return None
    _, x, y, w, h = max(found)
    return ((x + w / 2) / W, (y + h / 2) / H, w / W, h / H)


def strip_camera_stamp(img):
    """The camera burns a date/time into the bottom-left of its photos (and
    its clock is wrong). Cut that strip off before converting."""
    w, h = img.size
    return img.crop((0, 0, w, int(h * 0.93)))


def convert(img, style, lines=PRINT_LINES, glitches=0, seed=None, rot=None,
            log=None, prev=None, memory=None, chrome=None, fine=0,
            fine_prev=None):
    """glitches: number of random grid events, or 'random' to roll an amount
    (clean .. meltdown). rot: True / False / None (None = coin flip when
    glitching) for JPEG bit rot of the source. seed makes a print
    reproducible; log (a list) collects what happened. prev: the previous
    print's clean pixel planes (for 'ghost'); memory (a dict) receives this
    print's planes to pass on as the next prev. chrome: None / 'sierra' /
    'random' - adventure-game status line and parser prompt."""
    import glitch
    (w, h), (dx, dy), levels, ink_pct, clean, punch = STYLES[style]
    rng = np.random.default_rng(seed)
    meltdown = False
    if glitches == 'random':
        glitches, meltdown = glitch.roll_amount(rng)
    src = prep(img)
    face = find_face(src)
    if log is not None and face is not None:
        log.append('face')
    if glitches and (rot if rot is not None else rng.random() < 0.4):
        src, ok = glitch.jpeg_rot(src, rng)
        if ok and log is not None:
            log.append('rot')
    lvl, fam, lum = analyse(src, w, h, levels, clean, punch, face=face)
    ink = outlines(lum, ink_pct)
    planes = None
    if isinstance(prev, dict):
        # the previous print may be another style: resample its pixel grid
        # and rescale its tone levels to this one
        p = prev['planes']
        yi = (np.arange(h) * p.shape[0] / h).astype(int)
        xi = (np.arange(w) * p.shape[1] / w).astype(int)
        p = p[yi][:, xi].copy()
        p[..., 0] = np.round(p[..., 0] * (levels - 1) / max(1, prev['levels'] - 1))
        prev = p
    if glitches:
        lvl, ink, fam, events, planes = glitch.glitch_grid(
            lvl, ink, fam, levels, rng, glitches, prev=prev, meltdown=meltdown,
            face=face)
        if log is not None:
            log.extend(events)
    lvl = np.clip(lvl, 0, levels - 1)
    if memory is not None:
        memory['planes'] = planes if planes is not None else np.stack(
            [lvl, ink.astype(int), fam], axis=-1)
        memory['levels'] = levels
    if style == 'hercules':
        bw = render_textured(lvl, fam, ink, levels, dx)
    elif style in ('ega', 'agi-grey'):
        bw = render_grey(lvl, ink, dx, dy)
    else:
        bw = render_pixels(lvl, ink, dx, dy)
    # centre on the print area: crop if the grid is taller, white margin if
    # it is shorter
    if bw.shape[0] > lines:
        top = (bw.shape[0] - lines) // 2
        bw = bw[top:top + lines]
    bw = bw[:, :HEAD_DOTS]
    if bw.dtype == bool:
        canvas = np.zeros((lines, HEAD_DOTS), bool)
    else:
        canvas = np.full((lines, HEAD_DOTS), 255, np.uint8)
    oy = (lines - bw.shape[0]) // 2
    ox = (HEAD_DOTS - bw.shape[1]) // 2
    canvas[oy:oy + bw.shape[0], ox:ox + bw.shape[1]] = bw
    # fine glitch layer: small dot-level damage on top of the pixel art
    # (fine = number of events, or 'random' for a subtle random amount).
    # Its own random stream, so the same seed gives the same pixel art.
    if fine:
        import glitch_dots as gd
        frng = np.random.default_rng(None if seed is None else seed + 7919)
        n = gd.roll_amount(frng) if fine == 'random' else int(fine)
        fp = fine_prev if (fine_prev is not None and fine_prev.shape == canvas.shape
                           and fine_prev.dtype == canvas.dtype) else None
        canvas, ev = gd.apply(canvas, frng, n, face=face, prev=fp)
        if log is not None:
            log.extend('~' + e for e in ev)
    if memory is not None:
        memory['canvas'] = canvas.copy()
    if chrome == 'sierra' or (chrome == 'random' and rng.random() < 0.5):
        import chrome as ch
        canvas = ch.sierra(canvas, rng)
        if log is not None:
            log.append('sierra')
    return canvas, lvl


def to_image(bw):
    """bool array (True = black dot) or a uint8 grey array -> 'L' image."""
    if bw.dtype == bool:
        return Image.fromarray(np.where(bw, 0, 255).astype(np.uint8), 'L')
    return Image.fromarray(bw.astype(np.uint8), 'L')


TAG = b'GHR-RQ'   # JPEG comment that marks a file as one of our prints


def _jpeg_bytes(img, restart_blocks, comment=None):
    import io
    buf = io.BytesIO()
    kw = dict(quality=30, subsampling=2, optimize=False, progressive=False,
              dpi=(72, 72), restart_marker_blocks=restart_blocks)
    if comment:
        kw['comment'] = comment
    img.convert('RGB').save(buf, 'JPEG', **kw)
    return buf.getvalue()


def camera_jpeg(bw_main, bw_alt, path, note=''):
    """Write a file shaped like the camera's own photos: a 2304x1344
    baseline JPEG (restart interval 36) with a 1280x720 JPEG (restart
    interval 80) appended straight after it. The camera stores both; we
    don't know yet which one Playback prints, so each gets its own art:
    bw_main 384x224 dots (exactly 6x), bw_alt 384x216 dots."""
    main = to_image(bw_main).resize((HEAD_DOTS * CAMERA_SCALE,
                                     PRINT_LINES * CAMERA_SCALE), Image.NEAREST)
    alt = to_image(bw_alt).resize((1280, 720), Image.NEAREST)
    comment = TAG + (b' ' + note.encode('ascii', 'replace') if note else b'')
    with open(path, 'wb') as f:
        f.write(_jpeg_bytes(main, 36, comment))
        f.write(_jpeg_bytes(alt, 80, comment))


def paper_preview(bw, scale=3):
    """What the receipt should look like: dots slightly soft, on warm paper."""
    if bw.dtype == bool:
        a = np.where(bw, 0.0, 1.0)
    else:
        # measured from the grey wedge: 0-60 = the head's darkest (soft)
        # black, ~160+ = white, roughly linear between
        a = np.clip((bw.astype(np.float32) - 60) / 100.0, 0, 1)
        a = 0.45 + 0.55 * a          # its darkest is only about half-dark
    a = np.repeat(np.repeat(a, scale, 0), scale, 1)
    a = ndimage.gaussian_filter(a, scale * 0.28)
    paper = np.array([246, 243, 236], np.float32)
    ink = np.array([38, 36, 40], np.float32)
    rgb = ink + (paper - ink) * a[..., None]
    return Image.fromarray(rgb.astype(np.uint8))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('photo')
    ap.add_argument('--style', choices=STYLES, default='sci')
    ap.add_argument('--out', default='out')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.photo))[0]
    bw, _ = convert(Image.open(args.photo), args.style)
    to_image(bw).save(os.path.join(args.out, f'{base}_{args.style}_384.png'))
    bw_alt, _ = convert(Image.open(args.photo), args.style, lines=216)
    camera_jpeg(bw, bw_alt, os.path.join(args.out, f'{base}_{args.style}_camera.jpg'))
    paper_preview(bw).save(os.path.join(args.out, f'{base}_{args.style}_preview.png'))
    print('done:', base, args.style)


if __name__ == '__main__':
    main()
