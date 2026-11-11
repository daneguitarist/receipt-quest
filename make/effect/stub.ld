/* The stub replaces unreachable Game-menu window code. It is placed inside flash
 * sector 0x18000 only (RAM 0x02015a00 .. 0x0201657c), so no other sector changes. */
printer_print_4 = 0x0205ef00;
printer_jpeg = 0x0205f6d0;
printer_jpeg_mem = 0x0205f884;
SECTIONS
{
  . = 0x02015a00;
  .text : { *(.text.tramp) *(.text .text.*) *(.rodata .rodata.*) *(.data .data.* .sdata .sdata.*) *(.bss .bss.* .sbss .sbss.* COMMON) }
  __stub_end = .;
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
