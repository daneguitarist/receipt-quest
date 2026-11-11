"""Adventure-game screen chrome for Receipt Quest prints: a status line across
the top (score / sound, like the old parser games) and a typed command at the
bottom with a cursor. Drawn at printer-dot level in a chunky pixel font so it
stays crisp. All the commands are our own."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

COMMANDS = [
    'look at face', 'take picture', 'eat receipt', 'talk to man',
    'wear glasses', 'smell camera', 'climb into printer', 'look at teeth',
    'ask about glitch', 'pet gerbil', 'feed hamster', 'read receipt',
    'print again', 'save game', 'restore game', 'push button', 'look',
    'inventory', 'get receipt', 'wake up', 'unglitch', 'apologize',
    'open mouth wider', 'hold still', 'blink', 'look at self',
    'use thermal paper', 'smile', 'stop smiling', 'remember',
]
MAX_SCORES = [158, 185, 210, 230, 255]


def _text_mask(text, scale_x, scale_y):
    f = ImageFont.load_default_imagefont()
    x0, y0, x1, y1 = f.getbbox(text)
    im = Image.new('L', (x1 + 1, 11), 255)
    ImageDraw.Draw(im).text((0, 0), text, font=f, fill=0)
    im = im.resize((im.width * scale_x, im.height * scale_y), Image.NEAREST)
    return np.asarray(im) < 128                       # True = ink


def _blit(canvas, mask, x, y, value):
    h, w = mask.shape
    h, w = min(h, canvas.shape[0] - y), min(w, canvas.shape[1] - x)
    region = canvas[y:y + h, x:x + w]
    region[mask[:h, :w]] = value


def sierra(canvas, rng, scale=(2, 1)):
    """canvas: bool (True = black) or uint8 grey.

    White bars with black text and a 2-dot rule against the picture - like
    the old status line, and safe on thermal paper: an all-black bar fires
    all 384 dots on every line and the printer weakens them (test print
    IMG00020 came out with a faded, broken bar)."""
    sx, sy = scale
    out = canvas.copy()
    black, white = (True, False) if out.dtype == bool else (0, 255)
    bar = 11 * sy + 3
    H, W = out.shape
    # status line
    out[:bar] = white
    out[bar:bar + 2] = black
    score = f'Score:{int(rng.integers(0, 40))} of {int(rng.choice(MAX_SCORES))}'
    sound = 'Sound:on' if rng.random() < 0.8 else 'Sound:off'
    _blit(out, _text_mask(score, sx, sy), 4, 2, black)
    m = _text_mask(sound, sx, sy)
    _blit(out, m, W - m.shape[1] - 4, 2, black)
    # parser line
    out[H - bar:] = white
    out[H - bar - 2:H - bar] = black
    cmd = '>' + str(rng.choice(COMMANDS)) + '_'
    _blit(out, _text_mask(cmd, sx, sy), 4, H - bar + 2, black)
    return out
