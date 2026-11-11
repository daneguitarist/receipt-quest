/* Hooks for the camera's print path. Delay slots hold l.nop, so this code is
 * correct on the no-delay-slot camera CPU.
 *
 * rq_wrap_jpeg / rq_wrap_mem replace the stock calls to printer_jpeg (0x0205f6d0,
 * from the photo screen and the gallery) and printer_jpeg_mem (0x0205f884, photo
 * screen). They make sure the RAM hook at printer_print is in place, then go on to
 * the stock function with the caller's own arguments and return address.
 *
 * rq_tramp is reached from that RAM hook ("l.j rq_tramp" in place of printer_print's
 * first instruction, l.sw -4(r1),r9): keeps r3..r9 for printer_print, runs the stub,
 * does the replaced instruction and continues at printer_print+4. */
        .section .text.tramp, "ax"
        .global rq_tramp, rq_wrap_jpeg, rq_wrap_mem
rq_tramp:
        l.addi  r1, r1, -32
        l.sw    0(r1), r3
        l.sw    4(r1), r4
        l.sw    8(r1), r5
        l.sw    12(r1), r6
        l.sw    16(r1), r7
        l.sw    20(r1), r8
        l.sw    24(r1), r9
        l.jal   rq_stub_main
        l.nop
        l.lwz   r3, 0(r1)
        l.lwz   r4, 4(r1)
        l.lwz   r5, 8(r1)
        l.lwz   r6, 12(r1)
        l.lwz   r7, 16(r1)
        l.lwz   r8, 20(r1)
        l.lwz   r9, 24(r1)
        l.addi  r1, r1, 32
        l.sw    -4(r1), r9              /* printer_print's own first instruction */
        l.j     printer_print_4         /* printer_print + 4 (set in stub.ld) */
        l.nop

        .macro WRAP name, target
\name:
        l.addi  r1, r1, -32
        l.sw    0(r1), r3
        l.sw    4(r1), r4
        l.sw    8(r1), r5
        l.sw    12(r1), r6
        l.sw    16(r1), r7
        l.sw    20(r1), r8
        l.sw    24(r1), r9
        l.jal   rq_ensure_hook
        l.nop
        l.lwz   r3, 0(r1)
        l.lwz   r4, 4(r1)
        l.lwz   r5, 8(r1)
        l.lwz   r6, 12(r1)
        l.lwz   r7, 16(r1)
        l.lwz   r8, 20(r1)
        l.lwz   r9, 24(r1)
        l.addi  r1, r1, 32
        l.j     \target                 /* returns straight to the stock caller */
        l.nop
        .endm
        WRAP rq_wrap_jpeg, printer_jpeg
        WRAP rq_wrap_mem, printer_jpeg_mem
