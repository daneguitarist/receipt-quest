#ifndef RQ_STUB_H
#define RQ_STUB_H
#include "rq_fx.h"
/* payload header at PAYLOAD_FLASH (64 bytes) */
typedef struct {
    u32 magic;          /* 'RQFX' */
    u32 version;        /* 1 */
    u32 image_size;     /* code + read-only data, multiple of 16 */
    u32 reloc_count;    /* 8-byte entries right after the image */
    u32 bss_size;
    u32 entry;          /* offset of fx_main */
    u32 sum;            /* checksum of image + relocations */
    u32 hdr_sum;        /* checksum of the 7 words above */
    u32 reserved[8];
} fx_header;
#define FX_VERSION 1
#define FX_MAX_IMAGE 0x10000u
#define FX_MAX_RELOCS 0x800u
#define FX_MAX_BSS 0x4000u
/* relocation entry: word0 = type << 28 | offset, word1 = link-time target (image-relative) */
#define RT_WORD 1u      /* 32-bit pointer */
#define RT_HI 2u        /* l.movhi: target >> 16 */
#define RT_AHI 3u       /* l.movhi for a signed low half: (target + 0x8000) >> 16 */
#define RT_LO 4u        /* low 16 bits of an I-type instruction */
#define RT_SLO 5u       /* low 16 bits of a store (split immediate) */
static inline u32 fx_sum(const u32 *p, u32 nwords, u32 h)
{
    for (u32 i = 0; i < nwords; i++) {
        h ^= p[i];
        h = (h << 7) | (h >> 25);
        h += 0x9e3779b9u;
    }
    return h;
}
#endif
