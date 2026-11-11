"""Fine glitch layer for Receipt Quest - works on printer dots, AFTER the photo
has been turned into chunky pixel art. The pixel art stays clean and big;
the damage is small, sharp and sits on top of it like a separate layer.

Dane's direction (2026-11-08): glitches subtle, smaller than the pixel art.

Events (all small; sizes in printer dots, the print is 384 x 224):
  mosh     micro datamosh: a small patch of 2-4 dot blocks drifts a dot or
           two per step and smears
  ghost    a small ragged patch of the PREVIOUS print bleeds in and drifts
  hair     a 1-3 dot tall hairline slips sideways
  stall    the paper sticks for a moment: one dot row repeats down a few
           lines over part of the width
  stutter  a tiny block gets stuck and repeats to the right for a bit
  tear     a short band where every other dot row is nudged 1-3 dots
  rot      bit rot sprinkle: a few dots flip in a small spot
"""
import numpy as np

# glitch amount per print: (probability, number of events)
AMOUNTS = [(0.25, 0), (0.35, 1), (0.25, 2), (0.12, 3), (0.03, 5)]
WEIGHTS = {'mosh': 0.26, 'ghost': 0.10, 'hair': 0.20, 'stall': 0.14,
           'stutter': 0.10, 'tear': 0.10, 'rot': 0.10}


def roll_amount(rng):
    p = np.array([a[0] for a in AMOUNTS])
    return AMOUNTS[int(rng.choice(len(AMOUNTS), p=p / p.sum()))][1]


def _place(rng, H, W, rw, rh, ctx):
    """Spot for a rw x rh patch, kept off the face core unless this hit
    rolls the (1 - protect) chance of being allowed onto it."""
    face = ctx.get('face')
    if face is None or rng.random() > ctx['protect']:
        return int(rng.integers(0, max(1, W - rw + 1))), int(rng.integers(0, max(1, H - rh + 1)))
    fx, fy, fw, fh = face
    fa, fb = (fx - fw * 0.36) * W, (fx + fw * 0.36) * W
    ga, gb = (fy - fh * 0.34) * H, (fy + fh * 0.34) * H
    best = None
    for _ in range(60):
        x0 = int(rng.integers(0, max(1, W - rw + 1)))
        y0 = int(rng.integers(0, max(1, H - rh + 1)))
        ov = max(0, min(x0 + rw, fb) - max(x0, fa)) * max(0, min(y0 + rh, gb) - max(y0, ga))
        if ov == 0:
            return x0, y0
        if best is None or ov < best[0]:
            best = (ov, x0, y0)
    return best[1], best[2]


def _drag(out, rng, x0, y0, rw, rh, b, steps):
    H, W = out.shape
    ang = rng.uniform(0, 2 * np.pi)
    base = np.array([np.sin(ang), np.cos(ang)]) * rng.uniform(1.0, 2.2)
    nby, nbx = (rh + b - 1) // b, (rw + b - 1) // b
    field = base + rng.normal(0, 0.5, (nby, nbx, 2))
    for _ in range(steps):
        cur = out.copy()
        for by in range(nby):
            for bx in range(nbx):
                vy, vx = np.round(field[by, bx]).astype(int)
                if vy == 0 and vx == 0:
                    continue
                ty, tx = y0 + by * b, x0 + bx * b
                sy, sx = ty - vy, tx - vx
                if not (0 <= sy < H and 0 <= sx < W and ty < H and tx < W):
                    continue
                hh, ww = min(b, H - ty, H - sy), min(b, W - tx, W - sx)
                out[ty:ty + hh, tx:tx + ww] = cur[sy:sy + hh, sx:sx + ww]
    return out


def mosh(c, rng, ctx):
    H, W = c.shape
    rw, rh = int(rng.integers(24, 96)), int(rng.integers(12, 44))
    x0, y0 = _place(rng, H, W, rw, rh, ctx)
    return _drag(c.copy(), rng, x0, y0, rw, rh, int(rng.choice([2, 3, 4])),
                 int(rng.integers(3, 9)))


def ghost(c, rng, ctx):
    prev = ctx.get('prev')
    if prev is None or prev.shape != c.shape or prev.dtype != c.dtype:
        return mosh(c, rng, ctx)
    H, W = c.shape
    rw, rh = int(rng.integers(30, 90)), int(rng.integers(14, 44))
    x0, y0 = _place(rng, H, W, rw, rh, ctx)
    out = c.copy()
    b = 4
    for y in range(y0, min(H, y0 + rh), b):
        for x in range(x0, min(W, x0 + rw), b):
            if rng.random() < 0.65:
                out[y:y + b, x:x + b] = prev[y:y + b, x:x + b]
    return _drag(out, rng, x0, y0, rw, rh, b, int(rng.integers(2, 6)))


def hair(c, rng, ctx):
    H, W = c.shape
    hh = int(rng.integers(1, 4))
    rw = W if rng.random() < 0.4 else int(rng.integers(60, 220))
    x0, y0 = _place(rng, H, W, rw, hh, ctx)
    k = int(rng.choice([-1, 1]) * rng.integers(3, 25))
    out = c.copy()
    out[y0:y0 + hh, x0:x0 + rw] = np.roll(c[y0:y0 + hh, x0:x0 + rw], k, axis=1)
    return out


def stall(c, rng, ctx):
    H, W = c.shape
    rw, run = int(rng.integers(20, 130)), int(rng.integers(4, 20))
    x0, y0 = _place(rng, H, W, rw, run, ctx)
    out = c.copy()
    out[y0:y0 + run, x0:x0 + rw] = c[y0, x0:x0 + rw][None]
    return out


def stutter(c, rng, ctx):
    H, W = c.shape
    b = int(rng.choice([3, 4, 6]))
    span = int(rng.integers(16, 72))
    x0, y0 = _place(rng, H, W, span + b, b, ctx)
    out = c.copy()
    blk = c[y0:y0 + b, x0:x0 + b]
    for x in range(x0 + b, min(W, x0 + b + span), b):
        ww = min(b, W - x)
        out[y0:y0 + b, x:x + ww] = blk[:, :ww]
    return out


def tear(c, rng, ctx):
    H, W = c.shape
    hh = int(rng.integers(6, 22))
    rw = W if rng.random() < 0.3 else int(rng.integers(80, 240))
    x0, y0 = _place(rng, H, W, rw, hh, ctx)
    k = int(rng.choice([-1, 1]) * rng.integers(1, 4))
    out = c.copy()
    for y in range(y0 + 1, min(H, y0 + hh), 2):
        out[y, x0:x0 + rw] = np.roll(c[y, x0:x0 + rw], k)
    return out


def rot(c, rng, ctx):
    H, W = c.shape
    rw, rh = int(rng.integers(12, 40)), int(rng.integers(4, 14))
    x0, y0 = _place(rng, H, W, rw, rh, ctx)
    out = c.copy()
    m = rng.random((rh, rw)) < 0.12
    region = out[y0:y0 + rh, x0:x0 + rw]
    m = m[:region.shape[0], :region.shape[1]]
    if c.dtype == bool:
        region[m] = ~region[m]
    else:
        region[m] = np.where(region[m] > 127, 0, 255)
    return out


EVENTS = {'mosh': mosh, 'ghost': ghost, 'hair': hair, 'stall': stall,
          'stutter': stutter, 'tear': tear, 'rot': rot}


def apply(canvas, rng, count, face=None, prev=None, protect=0.9):
    names = list(WEIGHTS)
    p = np.array([WEIGHTS[n] for n in names])
    if prev is None:
        p[names.index('ghost')] = 0
    ctx = {'face': face, 'prev': prev, 'protect': protect}
    log = []
    out = canvas
    for _ in range(count):
        name = str(rng.choice(names, p=p / p.sum()))
        out = EVENTS[name](out, rng, ctx)
        log.append(name)
    return out, log
