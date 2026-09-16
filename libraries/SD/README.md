# SD library for the STC C++ core

This clean-room MIT implementation supports SD version 1, SD version 2 and
SDHC cards in SPI mode. It requests 100 kHz for card initialization, then
4 MHz on bus-layout-1 devices or 400 kHz on other devices by default.
`begin(clock, cs)` selects a nonzero data-clock request; SPI chooses the
supported hardware divider or software fallback. It provides bounded `CMD17`/`CMD24`
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

The library exposes `SDClass SD` and a writable `File : public Stream` facade, including
`Print`/`println` inherited from `Print`. The class layer uses the same global
backend, so it does not add concurrent cards or files. Its Arduino-shaped
surface includes `String` overloads for `open`/`exists`; `remove` performs a
real root-file deletion, while `mkdir` and `rmdir` fail with
`SD_ERROR_UNSUPPORTED`. `isDirectory()` is always false, `openNextFile()`
returns an invalid handle, and `rewindDirectory()` is a no-op: their presence
does not imply directory support.
A successful `setPins()` closes the active backend and invalidates every
outstanding `File` facade; a rejected pin configuration leaves the mounted
backend and its handles unchanged.

Copies of a `File` share the single open backend. Closing the last live copy
flushes it; opening another file invalidates all existing handles. Live
handles share a small heap-allocated state, retained until the last owner
releases it, so repeated opens cannot revive an old handle through a wrapping
generation counter. `open()` returns an invalid File if this allocation fails
and leaves the existing file usable. Releasing stale File objects also releases
their state; applications should not retain unbounded stale handles. All calls remain foreground
operations; this is not a thread-safe or interrupt-safe filesystem API.

If the last handle's explicit `close()` fails to flush, the handle stays valid
and `getWriteError()` records the failure. Correct the I/O problem, call
`clearWriteError()`, and retry `flush()`/`close()`. A failed close also prevents
`SD.open()`/`begin()`/`end()`/`remove()` from discarding the existing handle.
A destructor cannot preserve its own handle, but pending backend state is
retained for the next open or reconfiguration to retry. This is recovery from
a transient I/O failure, not a guarantee against power loss. `File.read(buffer,
length)` returns at most `INT_MAX` bytes per call (32767 on MCS251).

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
