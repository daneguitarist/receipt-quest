"""Receipt Quest - one-click camera converter (Windows).

Plug the camera in (it shows up as a USB drive), double-click MAKE_PRINTS.bat.

For every photo the CAMERA took (not ones we already made):
  1. copy the original to originals\\<date>\\ on this PC (and check the copy)
  2. turn it into a Receipt Quest print: pixel art, subtle glitch layer,
     sometimes the adventure-game bars, no date stamp
  3. put the print back on the card under the SAME name, so Playback shows
     it in the same place - then print it from Playback as usual
  4. read it back off the card to check it landed
Then it safely ejects the camera.

Prints carry a hidden JPEG comment "GHR-RQ", so they are never converted
twice. Everything that happened goes in prints_log.csv (with the seed, so a
favourite can be made again) and last_run_log.txt.
"""
import csv
import datetime as dt
import hashlib
import os
import shutil
import string
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'rq'))

LOG_LINES = []


def log(msg=''):
    print(msg, flush=True)
    LOG_LINES.append(msg)


def save_log():
    with open(os.path.join(HERE, 'last_run_log.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(LOG_LINES) + '\n')


def read_settings():
    s = {'style': 'random', 'glitch': 'random', 'bars': 'random',
         'replace_on_card': 'yes', 'eject_when_done': 'yes'}
    p = os.path.join(HERE, 'settings.txt')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.split('#', 1)[0].strip()
            if '=' in line:
                k, v = (x.strip().lower() for x in line.split('=', 1))
                s[k] = v
    return s


def find_card(override=None):
    if override:
        return override if os.path.isdir(os.path.join(override, 'PHOTO')) else None
    for L in string.ascii_uppercase[3:]:
        root = f'{L}:\\'
        if os.path.isdir(os.path.join(root, 'PHOTO')) and os.path.isfile(os.path.join(root, 'VIDEO.LST')):
            return root
    return None


def is_ours(path):
    with open(path, 'rb') as f:
        head = f.read(65536)
    return b'GHR-RQ' in head or b'c2pa' in head


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def eject(root):
    letter = root[0]
    cmd = ("(New-Object -ComObject Shell.Application).Namespace(17)"
           f".ParseName('{letter}:').InvokeVerb('Eject')")
    try:
        subprocess.run(['powershell', '-NoProfile', '-Command', cmd], timeout=30,
                       capture_output=True)
    except Exception as e:
        log(f'  (eject command failed: {e})')
    # Windows can take a while to let go of the drive
    for _ in range(40):
        time.sleep(1)
        try:
            if not os.path.exists(root) or not os.listdir(root):
                return True
        except OSError:
            return True
    return False


def main(card_override=None):
    import numpy as np
    from PIL import Image
    import receipt_quest as rq

    s = read_settings()
    log('RECEIPT QUEST  ' + dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    log(f"settings: style={s['style']} glitch={s['glitch']} bars={s['bars']}")
    root = find_card(card_override)
    if not root:
        log('No camera found. Plug the camera in (with its SD card) and try again.')
        return 1
    photo_dir = os.path.join(root, 'PHOTO')
    log(f'camera card: {root}')

    names = sorted(n for n in os.listdir(photo_dir)
                   if n.upper().startswith('IMG') and n.lower().endswith('.jpg'))
    todo = [n for n in names if not is_ours(os.path.join(photo_dir, n))]
    log(f'{len(names)} photos on the card, {len(todo)} new from the camera')

    backup_dir = os.path.join(HERE, 'originals', dt.date.today().isoformat())
    state = os.path.join(HERE, 'last_print.npy')
    prev = np.load(state) if os.path.exists(state) else None
    csv_path = os.path.join(HERE, 'prints_log.csv')
    new_csv = not os.path.exists(csv_path)
    rng = np.random.default_rng()
    done = 0
    with open(csv_path, 'a', newline='', encoding='utf-8') as cf:
        w = csv.writer(cf)
        if new_csv:
            w.writerow(['when', 'file', 'style', 'seed', 'what happened', 'original backup'])
        for n in todo:
            src = os.path.join(photo_dir, n)
            try:
                # 1. back up the original and check the copy
                os.makedirs(backup_dir, exist_ok=True)
                bak = os.path.join(backup_dir, n)
                if os.path.exists(bak) and sha(bak) != sha(src):
                    bak = os.path.join(backup_dir, n[:-4] + f'_{int(time.time())}.jpg')
                if not os.path.exists(bak):
                    shutil.copy2(src, bak)
                if sha(bak) != sha(src):
                    log(f'  {n}: backup copy did not match - skipped, card untouched')
                    continue

                # 2. convert
                style = s['style']
                if style not in rq.STYLES:
                    style = str(rng.choice(['agi-grey', 'agi']))
                seed = int(rng.integers(1, 10**9))
                fine = 'random' if s['glitch'] != 'off' else 0
                chrome = {'on': 'sierra', 'off': None}.get(s['bars'], 'random')
                img = rq.strip_camera_stamp(Image.open(bak))
                events, mem = [], {}
                main_bw, _ = rq.convert(img, style, seed=seed, log=events, chrome=chrome,
                                        fine=fine, fine_prev=prev, memory=mem)
                alt_bw, _ = rq.convert(img, style, lines=216, seed=seed, chrome=chrome,
                                       fine=fine, fine_prev=prev)
                tmp_local = os.path.join(HERE, '_print.tmp')
                rq.camera_jpeg(main_bw, alt_bw, tmp_local, note=f'{style} seed={seed}')

                # 3. onto the card under the same name, keeping the date
                if s['replace_on_card'] == 'yes':
                    st = os.stat(src)
                    tmp_card = os.path.join(photo_dir, n[:-4] + '.TMP')
                    shutil.copyfile(tmp_local, tmp_card)
                    with open(tmp_card, 'rb+') as f:
                        os.fsync(f.fileno())
                    os.replace(tmp_card, src)
                    os.utime(src, (st.st_atime, st.st_mtime))
                    # 4. read back
                    if sha(src) != sha(tmp_local):
                        log(f'  {n}: print did NOT read back right - original is safe in {bak}')
                        continue
                else:
                    out_dir = os.path.join(HERE, 'prints')
                    os.makedirs(out_dir, exist_ok=True)
                    shutil.copyfile(tmp_local, os.path.join(out_dir, n))
                os.remove(tmp_local)
                if 'canvas' in mem:
                    prev = mem['canvas']
                    np.save(state, prev)
                what = ' '.join(e for e in events if e != 'face') or 'clean'
                log(f'  {n}: {style}, {what}')
                w.writerow([dt.datetime.now().isoformat(timespec='seconds'), n, style,
                            seed, what, os.path.relpath(bak, HERE)])
                done += 1
            except Exception:
                log(f'  {n}: something went wrong, card copy left as it was')
                log(traceback.format_exc())

    log(f'made {done} prints. Originals are in {backup_dir}')
    if card_override is None and s['eject_when_done'] == 'yes':
        log('ejecting the camera...')
        log('  ejected - safe to unplug' if eject(root)
            else '  still ejecting - wait until the USB drive disappears from This PC, then unplug')
    return 0


if __name__ == '__main__':
    try:
        code = main(sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception:
        log(traceback.format_exc())
        code = 2
    save_log()
    sys.exit(code)
