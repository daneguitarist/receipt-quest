"""Glitch engine for Receipt Quest.

Everything here works on the low-res pixel grid (before pixels become printer
dots), so the damage stays chunky pixel art instead of smearing into mush.

How much: every print rolls its own amount (see AMOUNTS) - sometimes clean,
usually a hit or two, now and then a full meltdown.

Where: hits avoid the middle of the frame (where a face usually is) unless
it's a meltdown, so the person stays recognisable and the edges fall apart.

Events (applied to the tone map, ink outlines and texture map together):
  mosh     datamosh bloom: a patch of macroblocks keeps re-copying itself
           along drifting motion vectors with no fresh frame to fix it
  ghost    the real datamosh trick: the PREVIOUS photo shows through. A patch
           of the last print is pasted in as the stale reference frame, then
           dragged by motion vectors into this one - every print carries a
           smear of the one before it
  slice    a band of rows slips sideways (tracking error), sometimes with its
           tones flipped
  stutter  a decoder gets stuck on one macroblock and repeats it to the edge
  stall    receipt-native: the paper sticks while the head keeps printing the
           same line, so one row of pixels stretches down into a streak
  tear     interlace tear: inside a band, every other row is offset
Source event:
  rot      real JPEG bit rot of the photo before it is turned into pixels
"""
import io

import numpy as np
from PIL import Image

# amount of glitching per print: (probability, number of grid events)
AMOUNTS = [(0.15, 0), (0.30, 1), (0.25, 2), (0.18, 3), (0.12, 'meltdown')]
WEIGHTS = {'mosh': 0.34, 'ghost': 0.16, 'slice': 0.16, 'stutter': 0.10,
           'stall': 0.14, 'tear': 0.10}


def roll_amount(rng):
    p = np.array([a[0] for a in AMOUNTS])
    pick = AMOUNTS[int(rng.choice(len(AMOUNTS), p=p / p.sum()))][1]
    if pick == 'meltdown':
        return int(rng.integers(5, 9)), True
    return pick, False


_FACE = (0.5, 0.5, 0.44, 0.60)   # default "face zone": the middle


def pick_spot(rng, w, h, rw, rh, protect, face=None):
    """Place a rw x rh patch. Once per event we roll whether this hit is
    allowed onto the face (chance 1 - protect). If not, we look for the spot
    covering the least of the face core, shrinking the patch until it
    (nearly) misses. Returns (x0, y0, rw, rh)."""
    fx, fy, fw, fh = face or _FACE
    # the detector's box includes hair and chin; protect the core of it
    fa, fb = (fx - fw * 0.36) * w, (fx + fw * 0.36) * w
    ga, gb = (fy - fh * 0.34) * h, (fy + fh * 0.34) * h
    core = max(1.0, (fb - fa) * (gb - ga))

    def overlap(x0, y0, pw, ph):
        ox = max(0.0, min(x0 + pw, fb) - max(x0, fa))
        oy = max(0.0, min(y0 + ph, gb) - max(y0, ga))
        return ox * oy / core

    if rng.random() > protect:                     # this one may hit the face
        return (int(rng.integers(0, max(1, w - rw + 1))),
                int(rng.integers(0, max(1, h - rh + 1))), rw, rh)
    pw, ph = rw, rh
    best = None
    for _ in range(7):
        for _ in range(50):
            x0 = int(rng.integers(0, max(1, w - pw + 1)))
            y0 = int(rng.integers(0, max(1, h - ph + 1)))
            ov = overlap(x0, y0, pw, ph)
            if best is None or ov < best[0]:
                best = (ov, x0, y0, pw, ph)
        if best[0] < 0.04:
            break
        # too much face: shrink (bands only get thinner, never narrower)
        pw = pw if pw >= w else max(4, int(pw * 0.8))
        ph = max(2, int(ph * 0.8))
    return best[1:]


def _drag(out, rng, x0, y0, rw, rh, b, steps, speed):
    h, w = out.shape[:2]
    ang = rng.uniform(0, 2 * np.pi)
    base = np.array([np.sin(ang), np.cos(ang)]) * speed
    nby, nbx = (rh + b - 1) // b, (rw + b - 1) // b
    field = base + rng.normal(0, 0.6, (nby, nbx, 2))
    for _ in range(steps):
        cur = out.copy()
        for by in range(nby):
            for bx in range(nbx):
                vy, vx = np.round(field[by, bx]).astype(int)
                if vy == 0 and vx == 0:
                    continue
                ty, tx = y0 + by * b, x0 + bx * b
                sy, sx = ty - vy, tx - vx
                if not (0 <= sy < h and 0 <= sx < w and ty < h and tx < w):
                    continue
                hh, ww = min(b, h - ty, h - sy), min(b, w - tx, w - sx)
                out[ty:ty + hh, tx:tx + ww] = cur[sy:sy + hh, sx:sx + ww]
    return out


def mosh(planes, rng, ctx):
    h, w = planes.shape[:2]
    b = int(rng.choice([4, 8]))
    rw = int(rng.integers(w // 4, w * 2 // 3))
    rh = int(rng.integers(h // 5, h // 2))
    x0, y0, rw, rh = pick_spot(rng, w, h, rw, rh, ctx['protect'], ctx['face'])
    return _drag(planes.copy(), rng, x0, y0, rw, rh, b,
                 int(rng.integers(6, 15)), rng.uniform(1.5, 3.0))


def ghost(planes, rng, ctx):
    prev = ctx.get('prev')
    if prev is None or prev.shape != planes.shape:
        return mosh(planes, rng, ctx)
    h, w = planes.shape[:2]
    b = 8
    rw = int(rng.integers(w // 4, w // 2))
    rh = int(rng.integers(h // 4, h // 2))
    x0, y0, rw, rh = pick_spot(rng, w, h, rw, rh, ctx['protect'], ctx['face'])
    out = planes.copy()
    # ragged, blocky patch of the old frame (macroblocks that "didn't update")
    for by in range(y0, min(h, y0 + rh), b):
        for bx in range(x0, min(w, x0 + rw), b):
            if rng.random() < 0.7:
                out[by:by + b, bx:bx + b] = prev[by:by + b, bx:bx + b]
    return _drag(out, rng, x0, y0, rw, rh, b, int(rng.integers(3, 9)),
                 rng.uniform(1.0, 2.5))


def slice_shift(planes, rng, ctx):
    h, w = planes.shape[:2]
    hh = int(rng.integers(2, max(3, h // 8)))
    _, y0, _, hh = pick_spot(rng, w, h, w, hh, ctx['protect'], ctx['face'])
    k = int(rng.choice([-1, 1]) * rng.integers(w // 16, w // 3))
    out = planes.copy()
    out[y0:y0 + hh] = np.roll(planes[y0:y0 + hh], k, axis=1)
    if rng.random() < 0.35:                          # tones flip in the band
        out[y0:y0 + hh, :, 0] = (ctx['levels'] - 1) - out[y0:y0 + hh, :, 0]
    return out


def stutter(planes, rng, ctx):
    h, w = planes.shape[:2]
    b = 4
    rows = int(rng.integers(1, 4)) * b
    # the stuck block repeats to the right edge, so place it like a band
    _, y0, _, rows = pick_spot(rng, w, h, w, rows, ctx['protect'], ctx['face'])
    x0 = int(rng.integers(w // 8, w * 3 // 4)) // b * b
    out = planes.copy()
    blk = planes[y0:y0 + rows, x0:x0 + b]
    for x in range(x0 + b, w, b):
        ww = min(b, w - x)
        out[y0:y0 + rows, x:x + ww] = blk[:, :ww]
    return out


def stall(planes, rng, ctx):
    h, w = planes.shape[:2]
    run = int(rng.integers(h // 12, h // 4))
    _, y0, _, run = pick_spot(rng, w, h, w, run, ctx['protect'], ctx['face'])
    out = planes.copy()
    # the whole width, or just a chunk of the head
    if rng.random() < 0.5:
        xa, xb = 0, w
    else:
        xa = int(rng.integers(0, w // 2))
        xb = int(rng.integers(xa + w // 6, w + 1))
    out[y0:y0 + run, xa:xb] = planes[y0, xa:xb][None]
    return out


def tear(planes, rng, ctx):
    h, w = planes.shape[:2]
    hh = int(rng.integers(h // 10, h // 4))
    _, y0, _, hh = pick_spot(rng, w, h, w, hh, ctx['protect'], ctx['face'])
    k = int(rng.choice([-1, 1]) * rng.integers(2, max(3, w // 10)))
    out = planes.copy()
    rows = np.arange(y0, min(h, y0 + hh))
    odd = rows[(rows - y0) % 2 == 1]
    out[odd] = np.roll(planes[odd], k, axis=1)
    return out


EVENTS = {'mosh': mosh, 'ghost': ghost, 'slice': slice_shift,
          'stutter': stutter, 'stall': stall, 'tear': tear}


def glitch_grid(lvl, ink, fam, levels, rng, count, prev=None, meltdown=False,
                face=None):
    """Apply `count` random events. prev: the previous print's planes (for
    ghost). Returns new (lvl, ink, fam), a log, and the planes to hand on as
    the next print's prev."""
    planes = np.stack([lvl, ink.astype(int), fam], axis=-1)
    clean = planes.copy()
    ctx = {'levels': levels, 'prev': prev, 'face': face,
           'protect': 0.0 if meltdown else 0.85}
    names = list(WEIGHTS)
    p = np.array([WEIGHTS[n] for n in names])
    if prev is None:                                  # nothing to ghost from
        p[names.index('ghost')] = 0
    log = ['MELTDOWN'] if meltdown else []
    for _ in range(count):
        name = str(rng.choice(names, p=p / p.sum()))
        planes = EVENTS[name](planes, rng, ctx)
        log.append(name)
    return planes[..., 0], planes[..., 1].astype(bool), planes[..., 2], log, clean


def jpeg_rot(img, rng, flips=None, width=256):
    """Flip a few bytes in the compressed data of a JPEG of the picture."""
    small = img.resize((width, max(8, round(img.height * width / img.width))))
    buf = io.BytesIO()
    small.save(buf, 'JPEG', quality=70)              # no restart markers:
    data = bytearray(buf.getvalue())                 # damage runs to the end
    sos = data.find(b'\xff\xda')
    start = sos + 2 + int.from_bytes(data[sos + 2:sos + 4], 'big')
    end = len(data) - 2
    n = flips or 1
    for _ in range(20):                              # retry until it decodes
        d = bytearray(data)
        for _ in range(n):
            # damage only the last ~third so most of the picture survives
            pos = int(rng.integers(start + (end - start) * 2 // 3, end))
            if d[pos] == 0xFF or d[pos - 1] == 0xFF:
                continue
            nb = int(rng.integers(0, 255))
            d[pos] = nb if nb != 0xFF else 0xFE
        try:
            out = Image.open(io.BytesIO(bytes(d)))
            out.load()
            return out.convert('RGB').resize(img.size, Image.BOX), True
        except Exception:
            continue
    return img, False
