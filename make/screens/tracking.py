"""TRACKING look for the camera's screens - a still frame of MOTES 0.5's TRACKING
screen (motes.c track_prep): the red, green and blue plates apart, colour smeared
to the right with a faint ghost, a tracking band of torn noisy lines, every line
wandering a pixel, the top lines bent (flagging), the bottom few torn (head
switch), dropouts, and a few repeat blocks (the CACACA stutter), coarse blocks,
slid blocks and flat pink/green blocks. `amount` 0..1 keeps menus readable.

Palette is MOTES's TRACKING theme."""
import numpy as np
from PIL import Image

TRACK = {'bg': (6, 3, 12), 'wave': (66, 24, 74), 'core': (16, 54, 66), 'teal': (34, 124, 140),
         'cream': (255, 238, 214), 'pink': (255, 64, 168), 'orange': (255, 146, 20),
         'mint': (110, 196, 186), 'paper': (238, 238, 210), 'rose': (250, 70, 150), 'shadow': (38, 24, 56)}


def tint(rgb, keep=0.35):
    """Pull the colours toward the TRACKING tape: dark purple shadows, teal mids, cream highs."""
    a = rgb.astype(float)
    y = (0.3 * a[..., 0] + 0.59 * a[..., 1] + 0.11 * a[..., 2]) / 255.0
    stops = np.array([TRACK['bg'], TRACK['wave'], TRACK['teal'], TRACK['mint'], TRACK['cream']], float)
    pos = y * (len(stops) - 1)
    i = np.clip(pos.astype(int), 0, len(stops) - 2)
    f = (pos - i)[..., None]
    pal = stops[i] * (1 - f) + stops[i + 1] * f
    return pal * (1 - keep) + a * keep


def tracking(img, amount=0.6, seed=1, blocks=True, band_y=None):
    rng = np.random.default_rng(seed)
    a = tint(np.asarray(img.convert('RGB')), keep=0.45)
    H, W, _ = a.shape
    sev = amount
    # plates apart (trichrome): red right, blue left
    s = 1 + int(round(3 * sev))
    out = a.copy()
    out[:, :, 0] = np.roll(a[:, :, 0], s, axis=1)
    out[:, :, 2] = np.roll(a[:, :, 2], -s, axis=1)
    # colour running to the right + faint ghost
    y = 0.3 * out[..., 0] + 0.59 * out[..., 1] + 0.11 * out[..., 2]
    chroma = out - y[..., None]
    k = np.exp(-np.arange(10) / (2 + 4 * sev))
    k /= k.sum()
    sm = np.zeros_like(chroma)
    for j, w in enumerate(k):
        sm += w * np.roll(chroma, j, axis=1)
    out = y[..., None] + sm
    ghost = np.roll(out, 6 + int(8 * sev), axis=1)
    out = out * 0.86 + ghost * 0.14
    # per-line time-base wander, tracking band, flagging, head switch
    band_y = rng.integers(H // 5, H - H // 4) if band_y is None else band_y
    band_h = int(6 + 10 * sev)
    res = out.copy()
    for r in range(H):
        sh = int(rng.integers(-1, 2)) if rng.random() < 0.35 * sev else 0
        nz = 2 + 6 * sev
        d = r - band_y
        if 0 <= d < band_h:
            sh += int(rng.integers(-3, 4 + int(6 * sev)))
            nz += 22 * (1 - d / band_h) + 8
        if r < 10:
            sh += int((10 - r) * sev * 1.2)
        if r >= H - 7:
            sh += 5 + int(rng.integers(0, 3 + int(8 * sev)))
            nz += 26
        row = np.roll(out[r], sh, axis=0)
        row = row + rng.normal(0, nz, row.shape)
        res[r] = row
    out = res
    # dropouts: bright oxide streaks
    for _ in range(int(rng.integers(1, 2 + int(4 * sev)))):
        r, x0, L = rng.integers(0, H), rng.integers(0, W), rng.integers(6, 40)
        out[r, x0:x0 + L] = np.array(TRACK['paper']) * 0.9 + out[r, x0:x0 + L] * 0.1
    # blocks: one stutter (CACACA), and a few coarse / slid / flat
    if blocks:
        bw = int(rng.integers(6, 16))
        y0, hh = int(rng.integers(H // 6, H - 40)), 8 * int(rng.integers(1, 3))
        x0, span = int(rng.integers(0, W // 2)), int(rng.integers(60, 150))
        piece = out[y0:y0 + hh, x0:x0 + bw].copy()
        for x in range(x0 + bw, min(W, x0 + span), bw):
            w = min(bw, W - x)
            out[y0:y0 + hh, x:x + w] = piece[:, :w]
        for _ in range(int(rng.integers(1, 2 + int(3 * sev)))):
            kind = rng.integers(1, 4)
            bx, by = int(rng.integers(0, W - 48)), int(rng.integers(0, H - 16))
            bw2, bh2 = int(rng.integers(16, 48)), 8 * int(rng.integers(1, 3))
            blk = out[by:by + bh2, bx:bx + bw2]
            if kind == 1:                                   # coarse
                q = 4
                small = blk[::q, ::q]
                out[by:by + bh2, bx:bx + bw2] = np.repeat(np.repeat(small, q, 0), q, 1)[:blk.shape[0], :blk.shape[1]]
            elif kind == 2:                                 # slid
                out[by:by + bh2, bx:bx + bw2] = np.roll(blk, int(rng.integers(-24, 25)), axis=1)
            else:                                           # flat pink / green
                c = np.array(TRACK['rose'] if rng.random() < 0.5 else (60, 200, 120), float)
                out[by:by + bh2, bx:bx + bw2] = blk * 0.35 + c * 0.65
    # scanlines
    out[1::2] *= 0.86
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
