# SD library for the STC plain-C and experimental C++ cores

This clean-room MIT implementation supports SD version 1, SD version 2 and
SDHC cards in SPI mode. It requests 100 kHz for card initialization and then a
400 kHz target from the software SPI layer. It provides bounded `CMD17`/`CMD24`
single-sector I/O. Every card-response, data-token and busy wait has both a byte-attempt
limit and a `millis()` deadline; chip select is released on every exit path.

`SD.begin(cs)` also mounts a 512-byte-sector FAT16 or FAT32 volume. Sector zero
may be either a FAT boot sector (a superfloppy) or an MBR whose first partition
contains FAT. The file layer is intentionally small and deterministic:

If card initialization succeeds but FAT mounting fails, `begin` returns zero,
`fatType` remains `SD_FAT_NONE`, and bounded raw block I/O remains available for
diagnostics until `end` is called.

- one 512-byte cache plus state in XDATA, with a compile-time minimum of 1 KiB
  XDATA;
- one card and one open file at a time;
- root-directory, ASCII short 8.3 names only;
- file reads through `exists`, `open`, `peek`, `read`, `readBytes`, `available`,
  `seek`, `position`, `size`, and `close`;
- `FILE_WRITE` creation and append, seek-then-overwrite, `flush`/`close`
  writeback, and `remove`, including cluster allocation and release;
- no long-file names, subdirectories or directory iteration, FAT12, exFAT,
  formatting, sparse files, or power-loss-atomic metadata updates.

The default plain-C profile exposes these operations through the `SD` function
table. With the explicit `cppcore=enabled` profile, the library additionally
exposes `SDClass SD` and a writable `File : public Stream` facade, including
`Print`/`println` inherited from `Print`. The class layer uses the same global
backend, so it does not add concurrent cards or files. Its Arduino-shaped
surface includes `String` overloads for `open`/`exists`; `remove` performs a
real root-file deletion, while `mkdir` and `rmdir` fail with
`SD_ERROR_UNSUPPORTED`. `isDirectory()` is always false, `openNextFile()`
returns an invalid handle, and `rewindDirectory()` is a no-op: their presence
does not imply directory support. `begin(clock, cs)` accepts but currently
ignores `clock` before using the same fixed software-SPI policy as `begin(cs)`.
A successful `setPins()` closes the active backend and invalidates every
outstanding `File` facade; a rejected pin configuration leaves the mounted
backend and its handles unchanged.

Root-directory scans have a hard 4096-sector ceiling in addition to the FAT
cluster-count bound, so a corrupt cyclic directory chain cannot cause an
effectively unbounded lookup. File reads are bounded by the directory entry's
declared size and the volume cluster count. File growth updates mirrored FAT
copies (or the selected active FAT when FAT32 mirroring is disabled) and the
root-directory entry, but those writes are not a transaction and an I/O
failure or sudden power loss can leave a damaged filesystem. This small
implementation is not a FAT repair tool or full `fsck`; do not treat data from
a damaged volume as trusted.

The raw `readBlock` and `writeBlock` calls always transfer exactly 512 bytes.
`writeBlock` bypasses FAT consistency and can irreversibly corrupt the mounted
volume; use it only when the caller owns the on-card layout. Normal writable
file access instead maintains the supported FAT16/FAT32 root-file structures.

Cards and breakout boards must use 3.3 V signaling. Provide proper level
translation when the selected STC device is operated at 5 V.
