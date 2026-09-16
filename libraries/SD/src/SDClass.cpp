
#include "SDClass.h"

#include <limits.h>
#include <cpp/stcxx_allocator.h>

#if defined(STCXX_HOST_TEST) && STCXX_HOST_TEST && \
    (defined(__GNUC__) || defined(__clang__))
/* Keep older facade-only host probes linkable while the real backend owns the
 * strong definitions in production and in the FAT image integration test. */
extern "C" size_t SD_writeBytes(const uint8_t *, size_t)
    __attribute__((weak));
extern "C" uint8_t SD_flush(void) __attribute__((weak));
extern "C" uint8_t SD_remove(const char *) __attribute__((weak));
extern "C" uint8_t SD_mkdir(const char *) __attribute__((weak));
extern "C" uint8_t SD_rmdir(const char *) __attribute__((weak));
#endif

struct STCSDFileState {
    uint32_t references;
};

namespace {

STCSDFileState *currentState;
bool currentOpen;
bool currentWritable;
char currentName[13];

void copyFileName(const char *name)
{
    size_t length = 0u;
    const char *base = name;
    if (name == 0) {
        currentName[0] = '\0';
        return;
    }
    for (const char *cursor = name; *cursor != '\0'; ++cursor) {
        if (*cursor == '/' || *cursor == '\\') {
            base = cursor + 1;
        }
    }
    while (base[length] != '\0' && length < sizeof(currentName) - 1u) {
        currentName[length] = base[length];
        ++length;
    }
    currentName[length] = '\0';
}

} // namespace

SDClass SD;

File::File() : _state(0) {}

File::File(STCSDFileState *state) : _state(state)
{
}

File::File(const File &other) : _state(0)
{
    retain(other);
}

File::File(File &&other) : _state(other._state)
{
    other._state = 0;
}

File::~File()
{
    release();
}

File &File::operator=(const File &other)
{
    if (this != &other) {
        release();
        retain(other);
    }
    return *this;
}

File &File::operator=(File &&other)
{
    if (this != &other) {
        release();
        _state = other._state;
        other._state = 0;
    }
    return *this;
}

// Reuse this check across the File API instead of duplicating its loads in
// every caller. It also keeps the CBE boundary at a defined bool return;
// inlining into name() can introduce a freeze of unproven memory loads.
#if defined(__GNUC__) || defined(__clang__)
__attribute__((noinline))
#endif
bool File::valid() const
{
    return _state != 0 && _state == currentState && currentOpen;
}

void File::retain(const File &other)
{
    // Even a 24-bit address space cannot hold UINT32_MAX distinct File
    // objects. Keep an explicit guard so overflow can never revive owners.
    if (other.valid() && other._state->references != UINT32_MAX) {
        _state = other._state;
        ++_state->references;
    }
}

void File::release()
{
    if (_state == 0) return;
    STCSDFileState *state = _state;
    _state = 0;
    if (--state->references == 0) {
        if (state == currentState) {
            // A destructor releases storage even if writeback fails. Keep
            // currentOpen so the next reconfiguration retries the backend.
            (void)closeCurrent();
            currentState = 0;
        }
        stcxx_free(state);
    }
}

void File::invalidateHandles()
{
    currentState = 0;
    currentOpen = false;
    currentWritable = false;
    currentName[0] = '\0';
}

bool File::closeCurrent()
{
    if (currentOpen) {
        SD_close();
        if (SD_error() != SD_ERROR_NONE) return false;
    }
    invalidateHandles();
    return true;
}

size_t File::write(uint8_t value)
{
    return write(&value, 1u);
}

size_t File::write(const uint8_t *buffer, size_t size)
{
    size_t written;

    if (!valid() || !currentWritable ||
        (buffer == 0 && size != 0u)) {
        setWriteError(valid() ? SD_ERROR_READ_ONLY :
                      SD_ERROR_NOT_INITIALIZED);
        return 0u;
    }
#if defined(STCXX_HOST_TEST) && STCXX_HOST_TEST && \
    (defined(__GNUC__) || defined(__clang__))
    if (SD_writeBytes == 0) {
        setWriteError(SD_ERROR_READ_ONLY);
        return 0u;
    }
#endif
    written = SD_writeBytes(buffer, size);
    if (written != size) {
        setWriteError(SD_error());
    }
    return written;
}

int File::availableForWrite()
{
    return (valid() && currentWritable) ? INT_MAX : 0;
}

int File::available()
{
    unsigned long count;
    if (!valid()) {
        return 0;
    }
    count = SD_available();
    return count > (unsigned long)INT_MAX ? INT_MAX : (int)count;
}

int File::read()
{
    return valid() ? SD_read() : -1;
}

int File::read(void *buffer, uint16_t length)
{
    size_t count;
    if (!valid() || (buffer == 0 && length != 0u)) {
        return 0;
    }
    // int is 16-bit on the target. Never consume more bytes than the return
    // value can represent, otherwise a caller loses its position silently.
    size_t requested = (size_t)length;
    if (requested > (size_t)INT_MAX) requested = (size_t)INT_MAX;
    count = SD_readBytes(static_cast<uint8_t *>(buffer), requested);
    return (int)count;
}

int File::peek()
{
    return valid() ? SD_peek() : -1;
}

void File::flush()
{
    if (!valid()) {
        return;
    }
#if defined(STCXX_HOST_TEST) && STCXX_HOST_TEST && \
    (defined(__GNUC__) || defined(__clang__))
    if (SD_flush == 0) {
        return;
    }
#endif
    if (SD_flush() == 0u) {
        setWriteError(SD_error());
    }
}

bool File::seek(uint32_t position)
{
    return valid() && SD_seek((unsigned long)position) != 0u;
}

uint32_t File::position() const
{
    return valid() ? (uint32_t)SD_position() : 0u;
}

uint32_t File::size() const
{
    return valid() ? (uint32_t)SD_size() : 0u;
}

void File::close()
{
    if (valid() && _state->references == 1 && !closeCurrent()) {
        setWriteError(SD_error());
        return;
    }
    release();
}

File::operator bool() const
{
    return valid();
}

const char *File::name() const
{
    return valid() ? currentName : "";
}

File File::openNextFile(uint8_t)
{
    return File();
}

bool SDClass::begin()
{
    if (!File::closeCurrent()) return false;
    return SD_beginDefault() != 0u;
}

bool SDClass::begin(uint8_t select)
{
    if (!File::closeCurrent()) return false;
    return SD_begin(select) != 0u;
}

bool SDClass::begin(uint32_t clock, uint8_t select)
{
    if (!File::closeCurrent()) return false;
    return SD_beginClock(clock, select) != 0u;
}

void SDClass::end()
{
    if (!File::closeCurrent()) return;
    SD_end();
}

bool SDClass::setPins(uint8_t mosi, uint8_t miso, uint8_t clock,
                       uint8_t select)
{
    if (SD_setPins(mosi, miso, clock, select) == 0u) {
        return false;
    }

    /* A successful pin change tears down an active backend in SD_setPins().
     * Invalidate the facade handles as well so no File object can continue
     * to identify the now-closed global file.  A rejected pin set deliberately
     * leaves both the backend and existing handles untouched. */
    File::invalidateHandles();
    return true;
}

File SDClass::open(const char *name, uint8_t mode)
{
    if (name == 0) return File();
    STCSDFileState *state = static_cast<STCSDFileState *>(
        stcxx_malloc(sizeof(STCSDFileState)));
    // Allocate before closing: heap exhaustion must leave the old file usable.
    if (state == 0) return File();
    if (!File::closeCurrent() || SD_open(name, mode) == 0u) {
        stcxx_free(state);
        return File();
    }
    copyFileName(name);
    currentOpen = true;
    currentWritable = ((mode & 0x02u) != 0u);
    state->references = 1;
    currentState = state;
    return File(state);
}

bool SDClass::exists(const char *name)
{
    return name != 0 && SD_exists(name) != 0u;
}

bool SDClass::remove(const char *name)
{
    bool result;

    if (name == 0) {
        return false;
    }
#if defined(STCXX_HOST_TEST) && STCXX_HOST_TEST && \
    (defined(__GNUC__) || defined(__clang__))
    if (SD_remove == 0) {
        return false;
    }
#endif
    if (!File::closeCurrent()) return false;
    result = SD_remove(name) != 0u;
    return result;
}

bool SDClass::mkdir(const char *name)
{
    if (name == 0) {
        return false;
    }
#if defined(STCXX_HOST_TEST) && STCXX_HOST_TEST && \
    (defined(__GNUC__) || defined(__clang__))
    if (SD_mkdir == 0) {
        return false;
    }
#endif
    return SD_mkdir(name) != 0u;
}

bool SDClass::rmdir(const char *name)
{
    if (name == 0) {
        return false;
    }
#if defined(STCXX_HOST_TEST) && STCXX_HOST_TEST && \
    (defined(__GNUC__) || defined(__clang__))
    if (SD_rmdir == 0) {
        return false;
    }
#endif
    return SD_rmdir(name) != 0u;
}
