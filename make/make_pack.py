"""Make a Receipt Quest patch pack: the difference between a stock flash backup and
a modded image, limited to the sectors the mod is allowed to touch.

    python make_pack.py STOCK.bin OURS.bin packs/NAME --title "PRINT EFFECT" \
        --windows 0xe-0x10,0x18-0x19,0x380-0x384 [--last-install 0xe000,0xf000] \
        [--last-undo ...] [--requires other-pack] [--note "..."]

Windows are in 4 KiB sector numbers, end exclusive (0xe-0x10 = sectors 0xe000 and
0xf000). They must be the same windows the flash writer helper is fenced to
(install/rq_stub_w.py).

The pack never carries the camera's own firmware: every run of 32+ bytes that
already exists somewhere in the stock flash is stored as "copy from stock offset
X", and the installer rebuilds it from the person's own backup. Only new bytes
(your sounds, pictures, code) are stored.

Output: NAME.rqp (records) + NAME.json (manifest with sha256 of every sector
before and after, so the installer can prove it rebuilt exactly this image).
"""
import argparse
import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'install'))
import rq_packs  # noqa: E402  (the installer's own pack reader, so both sides agree)

SECTOR = 0x1000
MAGIC = b'RQP1'
LITERAL = 0xFFFFFFFF
MIN_COPY = 32


def parse_windows(s):
    out = []
    for part in s.split(','):
        lo, hi = part.split('-')
        out.append((int(lo, 16), int(hi, 16)))
    return out


def parse_sectors(s):
    return sorted(int(x, 16) for x in s.split(',')) if s else []


def stock_index(stock, skip):
    """32-byte windows of the stock flash at every 8th offset (enough to find any
    shared run of 39+ bytes), ignoring runs of one repeated byte."""
    idx = {}
    for o in range(0, len(stock) - MIN_COPY, 8):
        if any(lo <= o < hi for lo, hi in skip):
            continue
        w = stock[o:o + MIN_COPY]
        if w.count(w[0]) == MIN_COPY:
            continue
        idx.setdefault(w, o)
    return idx


def records_for(stock, ours, sectors, idx, skip):
    recs = []
    for s in sectors:
        new, old = ours[s:s + SECTOR], stock[s:s + SECTOR]
        i = 0
        while i < SECTOR:
            if new[i] == old[i]:
                i += 1
                continue
            j = i                                   # changed region, small equal gaps merged
            while j < SECTOR:
                if new[j] != old[j]:
                    j += 1
                    continue
                k = j
                while k < SECTOR and new[k] == old[k] and k - j < 8:
                    k += 1
                if k < SECTOR and k - j < 8:
                    j = k
                else:
                    break
            # split [i, j) into copies from stock and literals
            lit = i
            p = i
            while p < j:
                w = new[p:p + MIN_COPY]
                src = idx.get(w) if p + MIN_COPY <= j else None
                if src is not None:
                    n = MIN_COPY
                    while p + n < j and src + n < len(stock) and new[p + n] == stock[src + n] and \
                            not any(lo <= src + n < hi for lo, hi in skip):
                        n += 1
                    if lit < p:
                        recs.append((s + lit, p - lit, LITERAL, new[lit:p]))
                    recs.append((s + p, n, src, b''))
                    p += n
                    lit = p
                else:
                    p += 1
            if lit < j:
                recs.append((s + lit, j - lit, LITERAL, new[lit:j]))
            i = j
    return recs


def encode(recs):
    out = bytearray(MAGIC + struct.pack('<I', len(recs)))
    for dst, n, src, data in recs:
        out += struct.pack('<III', dst, n, src) + data
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stock')
    ap.add_argument('ours')
    ap.add_argument('out')
    ap.add_argument('--title', required=True)
    ap.add_argument('--windows', required=True)
    ap.add_argument('--last-install', default='')
    ap.add_argument('--last-undo', default='')
    ap.add_argument('--first-undo', default='', help='sectors to put back FIRST on undo (all others last)')
    ap.add_argument('--requires', default='')
    ap.add_argument('--note', default='')
    ap.add_argument('--variable', default='0x2ff-0x300', help='sector windows that differ between cameras')
    ap.add_argument('--splice', action='store_true',
                    help='take only the windows from OURS and ignore its other changes (e.g. one stage of the screens)')
    a = ap.parse_args()
    stock, ours = open(a.stock, 'rb').read(), open(a.ours, 'rb').read()
    assert len(stock) == len(ours)
    wins = parse_windows(a.windows)
    if a.splice:
        spliced = bytearray(stock)
        for lo, hi in wins:
            spliced[lo * SECTOR:hi * SECTOR] = ours[lo * SECTOR:hi * SECTOR]
        ours = bytes(spliced)
    import rq_stub_w
    rq_stub_w.image(tuple(wins))      # the writer helper must build for these windows: never the boot,
                                      # boot-time code, resource table or settings sectors; at most ~3 windows
    variable = [(lo * SECTOR, hi * SECTOR) for lo, hi in parse_windows(a.variable)]
    allowed = [s for lo, hi in wins for s in range(lo * SECTOR, hi * SECTOR, SECTOR)]
    outside = [hex(s) for s in range(0, len(stock), SECTOR)
               if s not in allowed and stock[s:s + SECTOR] != ours[s:s + SECTOR]]
    assert not outside, f'image changes sectors outside the windows: {outside}'
    assert not any(lo <= s < hi for s in allowed for lo, hi in variable), 'a window overlaps a variable sector'
    changed = [s for s in allowed if stock[s:s + SECTOR] != ours[s:s + SECTOR]]
    recs = records_for(stock, ours, changed, stock_index(stock, variable), variable)
    blob = encode(recs)
    # self-check: rebuild from stock
    rebuilt = rq_packs.apply(stock, blob, allowed)
    assert rebuilt == ours, 'pack does not rebuild the image'
    sha = lambda b: hashlib.sha256(b).hexdigest()
    copy_bytes = sum(n for _, n, src, _ in recs if src != LITERAL)
    first_undo = parse_sectors(a.first_undo)
    last_undo = parse_sectors(a.last_undo) or ([s for s in changed if s not in first_undo] if first_undo else [])
    man = {
        'format': 'receipt-quest-pack/1',
        'name': os.path.basename(a.out),
        'title': a.title,
        'firmware': 'AX3291A 20240822_V1.9',
        'windows': [[lo, hi] for lo, hi in wins],
        'sectors': {hex(s): {'stock': sha(stock[s:s + SECTOR]), 'ours': sha(ours[s:s + SECTOR])} for s in changed},
        'last_install': [hex(s) for s in parse_sectors(a.last_install)],
        'last_undo': [hex(s) for s in last_undo],
        'requires': [x for x in a.requires.split(',') if x],
        'patch_sha256': sha(blob),
        'patch_bytes': len(blob),
        'new_bytes': sum(n for _, n, src, _ in recs if src == LITERAL),
        'copied_from_stock_bytes': copy_bytes,
        'note': a.note,
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out + '.rqp', 'wb').write(blob)
    with open(a.out + '.json', 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=1)
    print(f"{man['name']}: {len(changed)} sectors, {len(recs)} records, {man['new_bytes']} new bytes, "
          f"{copy_bytes} bytes rebuilt from the stock flash, pack {len(blob)} bytes")


if __name__ == '__main__':
    main()
