/* PC stress test of rq_fx.c under AddressSanitizer/UBSan: many seeds, sizes, layouts. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rq_fx.h"
static long live;
static void *h_malloc(u32 n, u32 a) { (void)a; live++; return malloc(n); }
static void h_free(void *p) { live--; free(p); }
static u32 xs = 12345;
static u32 rnd(void) { xs ^= xs << 13; xs ^= xs >> 17; xs ^= xs << 5; return xs; }
int main(int argc, char **argv)
{
    int iters = argc > 1 ? atoi(argv[1]) : 2000;
    static int sizes[][2] = {{384, 224}, {384, 216}, {384, 240}, {384, 336}, {384, 672}, {384, 2},
                                   {224, 384}, {216, 384}, {672, 384}, {320, 240}, {384, 17}, {384, 1600}, {16, 384}};
    int nsz = sizeof(sizes) / sizeof(sizes[0]);
    unsigned long reports[16] = {0};
    for (int it = 0; it < iters; it++) {
        int w = sizes[it % nsz][0], h = sizes[it % nsz][1];
        if (it % 7 == 6) { if (rnd() & 1) { w = 384; h = 1 + rnd() % 1700; } else { h = 384; w = 1 + rnd() % 1700; } }
        u8 *buf = malloc((size_t)w * h);
        int kind = rnd() % 4;
        for (int i = 0; i < w * h; i++)
            buf[i] = kind == 0 ? (u8)rnd() : kind == 1 ? (u8)(i * 7 / (w + 1)) : kind == 2 ? 0 : 255;
        fx_ctx c = {FX_CTX_MAGIC, h_malloc, h_free, rnd(), rnd() % 50, rnd() % 3, rnd() % 3};
        u32 r = fx_main(&c, buf, w, h, 2, 1);
        reports[(r >> 4) & 15]++;
        free(buf);
        if (live) { printf("leak at it %d\n", it); return 1; }
    }
    printf("ok, %d runs; glitch-count histogram:", iters);
    for (int i = 0; i < 16; i++) if (reports[i]) printf(" %d:%lu", i, reports[i]);
    printf("\n");
    return 0;
}
