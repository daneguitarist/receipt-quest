/* Receipt Quest in-camera print effect (AX3291A, firmware 20240822_V1.9).
 *
 * Runs at the start of the camera's printer_print(): turns the decoded grey
 * print picture (384 dots across, 8-bit, 255 = white) into Sierra AGI-style
 * pixel art in place, adds a subtle dot-level glitch layer and sometimes the
 * adventure-game status line + parser prompt. Port of receipt_quest.py
 * ('agi' / 'agi-grey'), glitch_dots.py and chrome.py, in integer maths.
 *
 * Built twice from this same file: for the camera (or1k, loaded from flash by
 * the stub, relocated) and for the PC (reference + previews), so both give the
 * same dots for the same picture and seed.
 */
#include "rq_fx.h"
#ifndef CLIP_X1000
#define CLIP_X1000 45
#endif
#ifndef MX0
#define MX0 30
#define MX1 70
#define MY0 15
#define MY1 85
#endif
#ifndef MPCT
#define MPCT 600
#endif
#ifndef MTARGET
#define MTARGET 150
#endif

/* ---------------------------------------------------------------- tiny libc */
#ifdef HOST
#include <string.h>
#else
void *memset(void *d, int v, unsigned n)
{
    u8 *p = d;
    while (n--)
        *p++ = (u8)v;
    return d;
}

void *memcpy(void *d, const void *s, unsigned n)
{
    u8 *p = d;
    const u8 *q = s;
    while (n--)
        *p++ = *q++;
    return d;
}
#endif

/* hide a constant from the optimiser: the vendor's compiler never emits l.muli
 * (multiply by immediate), so the camera's CPU may not have it - keep to l.mul */
static inline u32 opq(u32 x)
{
#ifndef HOST
    __asm__("" : "+r"(x));
#endif
    return x;
}

/* ---------------------------------------------------------------- random */
typedef struct { u32 s; } rng_t;

static u32 rnd(rng_t *r)
{
    u32 x = r->s;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    r->s = x;
    return x;
}

/* uniform integer in [lo, hi) */
static int rr(rng_t *r, int lo, int hi)
{
    if (hi <= lo)
        return lo;
    u32 d = opq((u32)(hi - lo)), x = rnd(r);
    return lo + (int)(x - (x / d) * d);
}

/* true with probability num/den */
static int chance(rng_t *r, int num, int den)
{
    u32 d = opq((u32)den), x = rnd(r);
    return (int)(x - (x / d) * d) < num;
}

static int clampi(int v, int lo, int hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

/* ---------------------------------------------------------------- tables */
/* Every constant table is bytes only: the compiler is big-endian, the camera
 * little-endian, and the build swaps instruction words only. */

/* -ln(i/255) in Q10 for i = 1..255 (index 0 = big), for the exposure curve */
static const u8 NEGLN_HI[256] = {
#include "negln_hi.inc"
};
static const u8 NEGLN_LO[256] = {
#include "negln_lo.inc"
};
#define NEGLN(i) ((int)NEGLN_HI[i] << 8 | NEGLN_LO[i])

/* the PIL default bitmap font (the PC tool's chrome font), ASCII 32..126,
 * 11 rows each, bit 5 = leftmost of 6 columns */
static const u8 FONT[95][11] = {
#include "font.inc"
};

/* the PC tool's parser commands, one string, NUL-separated (no pointer table) */
static const char COMMANDS[] =
    "look at face\0take picture\0eat receipt\0talk to man\0"
    "wear glasses\0smell camera\0climb into printer\0look at teeth\0"
    "ask about glitch\0pet gerbil\0feed hamster\0read receipt\0"
    "print again\0save game\0restore game\0push button\0look\0"
    "inventory\0get receipt\0wake up\0unglitch\0apologize\0"
    "open mouth wider\0hold still\0blink\0look at self\0"
    "use thermal paper\0smile\0stop smiling\0remember\0";
#define NCOMMANDS 30
static const u8 MAX_SCORES[5] = {158, 185, 210, 230, 255};

static const char *command(int k)
{
    const char *s = COMMANDS;
    while (k-- > 0)
        while (*s++)
            ;
    return s;
}
static const u8 GREY_TONES[4] = {255, 120, 80, 0};     /* agi-grey: darkness level -> printed tone */

/* ---------------------------------------------------------------- picture */
typedef struct {
    u8 *px;        /* print-oriented: W dots per line, H lines */
    int W, H;
    fx_ctx *c;
    rng_t rng;
} pic_t;

/* -------- exposure curve: out = 255 * (v/255)^g with g = ln(t)/ln(m) */
static void tone_curve(u8 *lut, int median, int target)
{
    median = clampi(median, 13, 242);
    int lm = NEGLN(median), lt = NEGLN(target);
    /* g in Q8, clipped to 0.5 .. 2.5 like the PC tool */
    int g = (lt << 8) / (lm ? lm : 1);
    g = clampi(g, 128, 640);
    lut[0] = 0;
    for (int v = 1; v < 256; v++) {
        int want = (NEGLN(v) * g) >> 8;        /* -ln(out/255) in Q10 */
        /* NEGLN falls as v rises: find the largest u with NEGLN[u] >= want */
        int lo = 1, hi = 255;
        while (lo < hi) {
            int mid = (lo + hi + 1) >> 1;
            if (NEGLN(mid) >= want)
                lo = mid;
            else
                hi = mid - 1;
        }
        lut[v] = (u8)lo;
    }
}

static int percentile(const u32 *hist, int total, int pct_x10)
{
    int want = (int)((u32)total * opq((u32)pct_x10) / opq(1000)), acc = 0;
    for (int i = 0; i < 256; i++) {
        acc += (int)hist[i];
        if (acc > want)
            return i;
    }
    return 255;
}

/* separable box blur with edge clamping, radius r: src -> dst (u8, gw x gh) */
static void box_blur(const u8 *src, u8 *dst, u16 *tmp, int gw, int gh, int r)
{
    int n = 2 * r + 1;
    for (int y = 0; y < gh; y++) {
        for (int x = 0; x < gw; x++) {
            int s = 0;
            for (int k = -r; k <= r; k++)
                s += src[y * gw + clampi(x + k, 0, gw - 1)];
            tmp[y * gw + x] = (u16)s;
        }
    }
    for (int y = 0; y < gh; y++) {
        for (int x = 0; x < gw; x++) {
            int s = 0;
            for (int k = -r; k <= r; k++)
                s += tmp[clampi(y + k, 0, gh - 1) * gw + x];
            dst[y * gw + x] = (u8)((s + (n * n) / 2) / (n * n));
        }
    }
}

/* ---------------------------------------------------------------- CLAHE */
/* contrast-limited adaptive histogram equalisation on the fat-pixel grid, the
 * PC tool's skimage equalize_adapthist(kernel ~32, clip_limit) in integers:
 * tx x ty tiles, histogram clipped at clip_x1000/1000 of the tile size, excess
 * spread evenly, per-tile maps blended bilinearly between tile centres. */
static void clahe(u8 *L, int gw, int gh, int tx, int ty, int clip_x1000, u8 *maps, u32 *hist)
{
    for (int j = 0; j < ty; j++)
        for (int i = 0; i < tx; i++) {
            int x0 = i * gw / tx, x1 = (i + 1) * gw / tx, y0 = j * gh / ty, y1 = (j + 1) * gh / ty;
            int nt = (x1 - x0) * (y1 - y0);
            memset(hist, 0, 256 * sizeof(u32));
            for (int y = y0; y < y1; y++)
                for (int x = x0; x < x1; x++)
                    hist[L[y * gw + x]]++;
            int clim = (clip_x1000 * nt) / 1000;
            if (clim < 1)
                clim = 1;
            int excess = 0;
            for (int v = 0; v < 256; v++)
                if ((int)hist[v] > clim) {
                    excess += (int)hist[v] - clim;
                    hist[v] = (u32)clim;
                }
            int add = excess / 256, rest = excess - add * 256;
            for (int v = 0; v < 256; v++)
                hist[v] += (u32)(add + (v < rest ? 1 : 0));
            u8 *m = maps + (j * tx + i) * 256;
            int acc = 0;
            for (int v = 0; v < 256; v++) {
                acc += (int)hist[v];
                m[v] = (u8)clampi((acc * 255 + nt / 2) / (nt ? nt : 1), 0, 255);
            }
        }
    for (int y = 0; y < gh; y++) {
        /* position between tile centres, Q8 */
        int fy = ((2 * y + 1) * ty * 128) / gh - 128;
        int j0 = fy >> 8, wy = fy & 255;
        if (fy < 0) { j0 = 0; wy = 0; }
        if (j0 >= ty - 1) { j0 = ty - 1; wy = 0; }
        int j1 = j0 + 1 < ty ? j0 + 1 : j0;
        for (int x = 0; x < gw; x++) {
            int fx = ((2 * x + 1) * tx * 128) / gw - 128;
            int i0 = fx >> 8, wx = fx & 255;
            if (fx < 0) { i0 = 0; wx = 0; }
            if (i0 >= tx - 1) { i0 = tx - 1; wx = 0; }
            int i1 = i0 + 1 < tx ? i0 + 1 : i0;
            int v = L[y * gw + x];
            int a = maps[(j0 * tx + i0) * 256 + v], b = maps[(j0 * tx + i1) * 256 + v];
            int c = maps[(j1 * tx + i0) * 256 + v], d = maps[(j1 * tx + i1) * 256 + v];
            int top = a * (256 - wx) + b * wx, bot = c * (256 - wx) + d * wx;
            L[y * gw + x] = (u8)((top * (256 - wy) + bot * wy + 32768) >> 16);
        }
    }
}

/* ---------------------------------------------------------------- pixel art */
typedef struct { int levels, ink_pct, clean, punch_q8; } style_t;

static int pixel_art(pic_t *p, int grey)
{
    /* agi: 5 levels, punch 1.35; agi-grey: 4 levels, punch 1.2; both 4% ink, 2 clean passes */
    style_t stv;
    stv.levels = grey ? 4 : 5;
    stv.ink_pct = 4;
    stv.clean = 2;
    stv.punch_q8 = grey ? 307 : 346;
    const style_t *st = &stv;
    int gw = p->W / 4, gh = p->H / 2;
    int n = gw * gh;
    /* one heap block: 6 byte planes, a u16 plane, two histograms and the tone table
     * (kept off the stack - the print task's stack size is unknown) */
    u32 n4 = ((u32)n + 3) & ~3u;
    u8 *L = p->c->malloc(n4 * 6 + n4 * 2 + 2 * 1024 + 256 + 64, 32);
    if (!L)
        return -1;
    u8 *B = L + n4, *lvl = L + 2 * n4, *ink = L + 3 * n4, *S = L + 4 * n4, *T = L + 5 * n4;
    u16 *tmp = (u16 *)(L + 6 * n4);
    u32 *hist = (u32 *)(L + 8 * n4), *ghist = hist + 256;
    u8 *lut = (u8 *)(ghist + 256);

    /* 1. luminance per fat pixel (4 x 2 dots) */
    for (int y = 0; y < gh; y++)
        for (int x = 0; x < gw; x++) {
            const u8 *q = p->px + (2 * y) * p->W + 4 * x;
            int s = q[0] + q[1] + q[2] + q[3] + q[p->W] + q[p->W + 1] + q[p->W + 2] + q[p->W + 3];
            L[y * gw + x] = (u8)((s + 4) >> 3);
        }
    /* 2. auto levels, 1% .. 99% */
    memset(hist, 0, 256 * sizeof(u32));
    for (int i = 0; i < n; i++)
        hist[L[i]]++;
    int lo = percentile(hist, n, 10), hi = percentile(hist, n, 990);
    if (hi - lo < 24) {
        int mid = (hi + lo) >> 1;
        lo = clampi(mid - 12, 0, 231);
        hi = lo + 24;
    }
    for (int i = 0; i < n; i++)
        L[i] = (u8)clampi(((L[i] - lo) * 255) / (hi - lo), 0, 255);
    /* 3. local contrast: CLAHE, tiles ~32 fat pixels like the PC tool */
    {
        int tx = gw >= 64 ? 3 : 2, ty = clampi(gh / 32, 2, 5);     /* at most 15 tiles */
        u8 *maps = p->c->malloc((u32)(tx * ty) * 256 + 32, 32);
        if (maps) {
            clahe(L, gw, gh, tx, ty, CLIP_X1000, maps, hist);
            p->c->free(maps);
        }
    }
    /* 4. exposure, metered on the middle of the picture (where a face usually is; the PC tool
     *    metered on the detected face): its middle tone goes to 0.62 */
    memset(hist, 0, 256 * sizeof(u32));
    int cn = 0;
    int my0 = gh * (int)opq(MY0) / 100, my1 = gh * (int)opq(MY1) / 100;
    int mx0 = gw * (int)opq(MX0) / 100, mx1 = gw * (int)opq(MX1) / 100;
    for (int y = my0; y < my1; y++)
        for (int x = mx0; x < mx1; x++, cn++)
            hist[L[y * gw + x]]++;
    tone_curve(lut, percentile(hist, cn, MPCT), MTARGET);
    /* 5. punch + 6. posterise */
    for (int i = 0; i < n; i++) {
        int v = 128 + (((int)lut[L[i]] - 128) * st->punch_q8) / 256;
        v = clampi(v, 0, 255);
        L[i] = (u8)v;
        lvl[i] = (u8)(((255 - v) * (st->levels - 1) + 127) / 255);
    }
    /* 7. majority filter, 'clean' passes (3x3, edges clamped) */
    for (int pass = 0; pass < st->clean; pass++) {
        for (int y = 0; y < gh; y++)
            for (int x = 0; x < gw; x++) {
                int cnt[5] = {0, 0, 0, 0, 0};
                for (int dy = -1; dy <= 1; dy++)
                    for (int dx = -1; dx <= 1; dx++)
                        cnt[lvl[clampi(y + dy, 0, gh - 1) * gw + clampi(x + dx, 0, gw - 1)]]++;
                int best = 0;
                for (int k = 1; k < st->levels; k++)
                    if (cnt[k] > cnt[best])
                        best = k;
                T[y * gw + x] = cnt[best] >= 5 ? (u8)best : lvl[y * gw + x];
            }
        memcpy(lvl, T, n);
    }
    /* 8. ink outlines: strongest edges (top ink_pct %), on their darker side */
    for (int y = 0; y < gh; y++)            /* [1 2 1] smoothing */
        for (int x = 0; x < gw; x++) {
            int s = 0;
            for (int dy = -1; dy <= 1; dy++)
                for (int dx = -1; dx <= 1; dx++) {
                    int wgt = (dy ? 1 : 2) * (dx ? 1 : 2);
                    s += wgt * L[clampi(y + dy, 0, gh - 1) * gw + clampi(x + dx, 0, gw - 1)];
                }
            S[y * gw + x] = (u8)((s + 8) >> 4);
        }
    box_blur(S, B, tmp, gw, gh, 1);         /* local mean for 'darker side' */
    memset(ghist, 0, 256 * sizeof(u32));
    for (int y = 0; y < gh; y++)
        for (int x = 0; x < gw; x++) {
#define SS(dx, dy) ((int)S[clampi(y + (dy), 0, gh - 1) * gw + clampi(x + (dx), 0, gw - 1)])
            int gx = SS(1, -1) + 2 * SS(1, 0) + SS(1, 1) - SS(-1, -1) - 2 * SS(-1, 0) - SS(-1, 1);
            int gy = SS(-1, 1) + 2 * SS(0, 1) + SS(1, 1) - SS(-1, -1) - 2 * SS(0, -1) - SS(1, -1);
#undef SS
            gx = gx < 0 ? -gx : gx;
            gy = gy < 0 ? -gy : gy;
            int mx = gx > gy ? gx : gy, mn = gx > gy ? gy : gx;
            int g = (mx + (mn * 3) / 8) >> 2;     /* ~hypot / 4 */
            g = clampi(g, 0, 255);
            T[y * gw + x] = (u8)g;
            ghist[g]++;
        }
    int thr = percentile(ghist, n, 1000 - st->ink_pct * 10);
    for (int i = 0; i < n; i++)
        ink[i] = (u8)(T[i] > thr && T[i] > 6 && S[i] < B[i]);
    /* 9. render: each fat pixel -> 4 x 2 dots */
    for (int y = 0; y < gh; y++)
        for (int x = 0; x < gw; x++) {
            int i = y * gw + x, v;
            if (grey)
                v = ink[i] ? 0 : GREY_TONES[lvl[i]];
            else {
                static const u8 BAYER2[2][2] = {{0, 2}, {3, 1}};
                v = (ink[i] || BAYER2[y & 1][x & 1] < lvl[i]) ? 0 : 255;
            }
            u8 *q = p->px + (2 * y) * p->W + 4 * x;
            q[0] = q[1] = q[2] = q[3] = (u8)v;
            q[p->W] = q[p->W + 1] = q[p->W + 2] = q[p->W + 3] = (u8)v;
        }
    p->c->free(L);
    return 0;
}

/* ---------------------------------------------------------------- fine glitch layer */
/* spot for a rw x rh patch; keeps off the middle of the picture (where the
 * face usually is) unless this hit rolls the 15% chance of being allowed on */
static void place(pic_t *p, int rw, int rh, int *ox, int *oy)
{
    int W = p->W, H = p->H;
    int protect = !chance(&p->rng, 15, 100);
    int fa = W * (int)opq(30) / 100, fb = W * (int)opq(70) / 100;
    int ga = H * (int)opq(20) / 100, gb = H * (int)opq(80) / 100;
    int bx = 0, by = 0, best = 0x7fffffff;
    for (int t = 0; t < (protect ? 60 : 1); t++) {
        int x0 = rr(&p->rng, 0, W - rw + 1 > 1 ? W - rw + 1 : 1);
        int y0 = rr(&p->rng, 0, H - rh + 1 > 1 ? H - rh + 1 : 1);
        if (!protect) {
            bx = x0, by = y0;
            break;
        }
        int ow = (x0 + rw < fb ? x0 + rw : fb) - (x0 > fa ? x0 : fa);
        int oh = (y0 + rh < gb ? y0 + rh : gb) - (y0 > ga ? y0 : ga);
        int ov = (ow > 0 && oh > 0) ? ow * oh : 0;
        if (ov < best) {
            best = ov, bx = x0, by = y0;
            if (!ov)
                break;
        }
    }
    *ox = bx, *oy = by;
}

static void g_hair(pic_t *p, u8 *row)
{
    int hh = rr(&p->rng, 1, 4);
    int rw = chance(&p->rng, 40, 100) ? p->W : rr(&p->rng, 60, 220);
    int x0, y0;
    place(p, rw, hh, &x0, &y0);
    int k = rr(&p->rng, 3, 25) * (chance(&p->rng, 1, 2) ? -1 : 1);
    for (int y = y0; y < y0 + hh && y < p->H; y++) {
        u8 *r = p->px + y * p->W + x0;
        int w = rw < p->W - x0 ? rw : p->W - x0;
        memcpy(row, r, w);
        for (int x = 0; x < w; x++)
            r[x] = row[((x - k) % w + w) % w];
    }
}

static void g_stall(pic_t *p)
{
    int rw = rr(&p->rng, 20, 130), run = rr(&p->rng, 4, 20), x0, y0;
    place(p, rw, run, &x0, &y0);
    for (int y = y0 + 1; y < y0 + run && y < p->H; y++)
        for (int x = x0; x < x0 + rw && x < p->W; x++)
            p->px[y * p->W + x] = p->px[y0 * p->W + x];
}

static void g_stutter(pic_t *p)
{
    static const u8 SIZES[3] = {3, 4, 6};
    int b = SIZES[rr(&p->rng, 0, 3)], span = rr(&p->rng, 16, 72), x0, y0;
    place(p, span + b, b, &x0, &y0);
    for (int x = x0 + b; x < x0 + b + span && x < p->W; x += b)
        for (int y = 0; y < b && y0 + y < p->H; y++)
            for (int k = 0; k < b && x + k < p->W && x0 + k < p->W; k++)
                p->px[(y0 + y) * p->W + x + k] = p->px[(y0 + y) * p->W + x0 + k];
}

static void g_tear(pic_t *p, u8 *row)
{
    int hh = rr(&p->rng, 6, 22);
    int rw = chance(&p->rng, 30, 100) ? p->W : rr(&p->rng, 80, 240);
    int x0, y0;
    place(p, rw, hh, &x0, &y0);
    int k = rr(&p->rng, 1, 4) * (chance(&p->rng, 1, 2) ? -1 : 1);
    for (int y = y0 + 1; y < y0 + hh && y < p->H; y += 2) {
        u8 *r = p->px + y * p->W + x0;
        int w = rw < p->W - x0 ? rw : p->W - x0;
        memcpy(row, r, w);
        for (int x = 0; x < w; x++)
            r[x] = row[((x - k) % w + w) % w];
    }
}

static void g_rot(pic_t *p)
{
    int rw = rr(&p->rng, 12, 40), rh = rr(&p->rng, 4, 14), x0, y0;
    place(p, rw, rh, &x0, &y0);
    for (int y = y0; y < y0 + rh && y < p->H; y++)
        for (int x = x0; x < x0 + rw && x < p->W; x++)
            if (chance(&p->rng, 12, 100)) {
                u8 *q = p->px + y * p->W + x;
                *q = *q > 127 ? 0 : 255;
            }
}

#define MOSH_COPY ((96 + 16) * (44 + 16))   /* patch + margin copy */

/* micro datamosh: a patch of b x b blocks, each dragged a dot or two per step */
static void g_mosh(pic_t *p, u8 *scratch)
{
    static const u8 SIZES[3] = {2, 3, 4};
    int rw = rr(&p->rng, 24, 96), rh = rr(&p->rng, 12, 44);
    int b = SIZES[rr(&p->rng, 0, 3)], steps = rr(&p->rng, 3, 9), x0, y0;
    place(p, rw, rh, &x0, &y0);
    /* base drift direction (8 ways) and speed 1..2, plus per-block jitter */
    static const s8 DIRS[8][2] = {{0, 1}, {1, 1}, {1, 0}, {1, -1}, {0, -1}, {-1, -1}, {-1, 0}, {-1, 1}};
    int d = rr(&p->rng, 0, 8), sp = rr(&p->rng, 1, 3);
    int nby = (rh + b - 1) / b, nbx = (rw + b - 1) / b;
    if (nby > 24) nby = 24;
    if (nbx > 48) nbx = 48;
    s8 *vy = (s8 *)scratch + MOSH_COPY, *vx = vy + 24 * 48;      /* per-block drift, in the heap scratch */
    for (int by = 0; by < nby; by++)
        for (int bx = 0; bx < nbx; bx++) {
            vy[by * 48 + bx] = (s8)(DIRS[d][0] * sp + rr(&p->rng, -1, 2) * chance(&p->rng, 1, 2));
            vx[by * 48 + bx] = (s8)(DIRS[d][1] * sp + rr(&p->rng, -1, 2) * chance(&p->rng, 1, 2));
        }
    int W = p->W, H = p->H;
    /* work on a copy of the patch area plus a margin, like the PC version's cur = out.copy() */
    int mx0 = clampi(x0 - 8, 0, W), my0 = clampi(y0 - 8, 0, H);
    int mx1 = clampi(x0 + rw + 8, 0, W), my1 = clampi(y0 + rh + 8, 0, H);
    int cw = mx1 - mx0;
    for (int s = 0; s < steps; s++) {
        for (int y = my0; y < my1; y++)
            memcpy(scratch + (y - my0) * cw, p->px + y * W + mx0, cw);
        for (int by = 0; by < nby; by++)
            for (int bx = 0; bx < nbx; bx++) {
                int dvy = vy[by * 48 + bx], dvx = vx[by * 48 + bx];
                if (!dvy && !dvx)
                    continue;
                int ty = y0 + by * b, tx = x0 + bx * b, sy = ty - dvy, sx = tx - dvx;
                if (sy < my0 || sx < mx0 || ty >= H || tx >= W || sy >= my1 || sx >= mx1)
                    continue;
                for (int yy = 0; yy < b && ty + yy < H && sy + yy < my1; yy++)
                    for (int xx = 0; xx < b && tx + xx < W && sx + xx < mx1; xx++)
                        p->px[(ty + yy) * W + tx + xx] = scratch[(sy + yy - my0) * cw + sx + xx - mx0];
            }
    }
}

static int glitch_amount(rng_t *r)
{
    /* 25% clean, 35% 1, 25% 2, 12% 3, 3% 5 */
    int x = rr(r, 0, 100);
    return x < 25 ? 0 : x < 60 ? 1 : x < 85 ? 2 : x < 97 ? 3 : 5;
}

static int glitch_layer(pic_t *p)
{
    int count = glitch_amount(&p->rng);
    if (!count)
        return 0;
    /* ghost needs the previous print: not kept on the camera, so its weight goes to the others */
    u8 *scratch = p->c->malloc(MOSH_COPY + 2 * 24 * 48 + p->W + 64, 32);
    if (!scratch)
        return -1;
    u8 *row = scratch + MOSH_COPY + 2 * 24 * 48;
    for (int i = 0; i < count; i++) {
        int x = rr(&p->rng, 0, 90);          /* mosh 26, hair 20, stall 14, stutter 10, tear 10, rot 10 */
        if (x < 26)
            g_mosh(p, scratch);
        else if (x < 46)
            g_hair(p, row);
        else if (x < 60)
            g_stall(p);
        else if (x < 70)
            g_stutter(p);
        else if (x < 80)
            g_tear(p, row);
        else
            g_rot(p);
    }
    p->c->free(scratch);
    return count;
}

/* ---------------------------------------------------------------- adventure-game chrome */
static int text_width(const char *s)
{
    int n = 0;
    while (*s++)
        n++;
    return n * 6 * 2;
}

static void text(pic_t *p, const char *s, int x, int y)
{
    for (; *s; s++, x += 12) {
        int ch = (u8)*s;
        if (ch < 32 || ch > 126)
            ch = '?';
        const u8 *g = FONT[ch - 32];
        for (int r = 0; r < 11; r++) {
            if (y + r < 0 || y + r >= p->H)
                continue;
            for (int c = 0; c < 6; c++)
                if (g[r] & (0x20 >> c))
                    for (int k = 0; k < 2; k++)
                        if (x + 2 * c + k >= 0 && x + 2 * c + k < p->W)
                            p->px[(y + r) * p->W + x + 2 * c + k] = 0;
        }
    }
}

static char *put_num(char *o, int v)
{
    char t[12];
    int n = 0;
    if (v < 0)
        v = 0;
    do {
        t[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v && n < 11);
    while (n)
        *o++ = t[--n];
    return o;
}

static char *put_str(char *o, const char *s)
{
    while (*s)
        *o++ = *s++;
    return o;
}

static void chrome(pic_t *p)
{
    int W = p->W, H = p->H, bar = 11 + 3;
    if (H < 4 * bar)
        return;
    /* white bars with black text and a 2-dot rule (an all-black bar prints weak) */
    memset(p->px, 255, bar * W);
    memset(p->px + bar * W, 0, 2 * W);
    memset(p->px + (H - bar) * W, 255, bar * W);
    memset(p->px + (H - bar - 2) * W, 0, 2 * W);
    char buf[48], *o;
    int top = MAX_SCORES[rr(&p->rng, 0, 5)];
    int score = (int)p->c->count * 5 + rr(&p->rng, 0, 5);      /* goes up with every print */
    if (score > top)
        score = top;
    o = put_str(buf, "Score:");
    o = put_num(o, score);
    o = put_str(o, " of ");
    o = put_num(o, top);
    *o = 0;
    text(p, buf, 4, 2);
    const char *snd = chance(&p->rng, 80, 100) ? "Sound:on" : "Sound:off";
    text(p, snd, W - text_width(snd) - 4, 2);
    o = put_str(buf, ">");
    o = put_str(o, command(rr(&p->rng, 0, NCOMMANDS)));
    o = put_str(o, "_");
    *o = 0;
    text(p, buf, 4, H - bar + 2);
}

/* ---------------------------------------------------------------- entry */
/* buf: decoded grey print picture. Stock printer_print prints w=384 row by
 * row; with h=384 (and w != 384) it prints column by column, dot k of line L
 * being buf[(383-k)*w + L]. Returns a small report word (for the tests). */
u32 fx_main(fx_ctx *c, u8 *buf, int w, int h, int level, int mode)
{
    (void)level;
    (void)mode;
    if (c->magic != FX_CTX_MAGIC || !buf)
        return 0xE0;
    int rotated;
    if (w == 384 && h >= 16 && h <= 1600)
        rotated = 0;
    else if (h == 384 && w >= 16 && w <= 1600)
        rotated = 1;
    else
        return 0xE1;
    pic_t P;
    P.c = c;
    P.rng.s = c->seed ? c->seed : 0x1234567u;
    for (int i = 0; i < 4; i++)
        rnd(&P.rng);
    P.W = 384;
    P.H = rotated ? w : h;
    P.H &= ~1;
    u8 *work = buf;
    if (rotated) {
        work = c->malloc(384 * P.H + 32, 32);
        if (!work)
            return 0xE2;
        for (int L = 0; L < P.H; L++)
            for (int k = 0; k < 384; k++)
                work[L * 384 + k] = buf[(383 - k) * w + L];
    }
    P.px = work;
    /* the look for this print: style, chrome, glitch amount */
    int grey = c->force_style ? c->force_style == 2 : chance(&P.rng, 55, 100);
    int sierra = c->force_chrome ? c->force_chrome == 2 : chance(&P.rng, 45, 100);
    u32 report = 0x100 | (grey ? 2 : 1);
    if (pixel_art(&P, grey) < 0)
        report |= 0x80;
    int g = glitch_layer(&P);
    report |= (u32)(g < 0 ? 0xf : g) << 4;
    if (sierra && !rotated) {
        chrome(&P);
        report |= 0x200;
    }
    if (rotated) {
        for (int L = 0; L < P.H; L++)
            for (int k = 0; k < 384; k++)
                buf[(383 - k) * w + L] = work[L * 384 + k];
        c->free(work);
    }
    return report;
}
