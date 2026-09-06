#if defined(STCXX_CPP_CORE) && STCXX_CPP_CORE

#include "SDClass.h"

#include <limits.h>

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

namespace {

uint16_t currentGeneration;
uint8_t currentReferences;
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

uint16_t nextGeneration()
{
    ++currentGeneration;
    if (currentGeneration == 0u) {
        ++currentGeneration;
    }
    return currentGeneration;
}

void invalidateCurrentFile()
{
    if (currentOpen) {
        SD_close();
    }
    currentOpen = false;
    currentWritable = false;
    currentReferences = 0u;
    (void)nextGeneration();
    currentName[0] = '\0';
}

} // namespace

SDClass SD;

File::File() : _generation(0u) {}

File::File(uint16_t generation) : _generation(generation) {}

File::File(const File &other) : _generation(other._generation)
{
    retain();
}

File::File(File &&other) : _generation(other._generation)
{
    other._generation = 0u;
}

File::~File()
{
    release();
}

File &File::operator=(const File &other)
{
    if (this != &other) {
        release();
        _generation = other._generation;
        retain();
    }
    return *this;
}

File &File::operator=(File &&other)
{
    if (this != &other) {
        release();
        _generation = other._generation;
        other._generation = 0u;
    }
    return *this;
}

bool File::valid() const
{
    return _generation != 0u && currentOpen &&
           _generation == currentGeneration;
}

void File::retain()
{
    if (valid() && currentReferences != 0xffu) {
        ++currentReferences;
    } else {
        _generation = 0u;
    }
}

void File::release()
{
    if (valid() && currentReferences != 0u) {
        --currentReferences;
        if (currentReferences == 0u) {
            SD_close();
            currentOpen = false;
            currentWritable = false;
            currentName[0] = '\0';
        }
    }
    _generation = 0u;
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
    count = SD_readBytes(static_cast<uint8_t *>(buffer), (size_t)length);
    return count > (size_t)INT_MAX ? INT_MAX : (int)count;
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
    invalidateCurrentFile();
    return SD_beginDefault() != 0u;
}

bool SDClass::begin(uint8_t select)
{
    invalidateCurrentFile();
    return SD_begin(select) != 0u;
}

void SDClass::end()
{
    invalidateCurrentFile();
    SD_end();
}

bool SDClass::setPins(uint8_t mosi, uint8_t miso, uint8_t clock,
                       uint8_t select)
{
    if (SD_setPins(mosi, miso, clock, select) == 0u) {
        return false;
    }

    /* A successful pin change tears down an active backend in SD_setPins().
     * Advance the facade generation as well so no File object can continue
     * to identify the now-closed global file.  A rejected pin set deliberately
     * leaves both the backend and existing handles untouched. */
    invalidateCurrentFile();
    return true;
}

File SDClass::open(const char *name, uint8_t mode)
{
    invalidateCurrentFile();
    if (name == 0 || SD_open(name, mode) == 0u) {
        return File();
    }
    copyFileName(name);
    currentOpen = true;
    currentWritable = ((mode & 0x02u) != 0u);
    currentReferences = 1u;
    return File(currentGeneration);
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
    result = SD_remove(name) != 0u;
    currentOpen = false;
    currentWritable = false;
    currentReferences = 0u;
    (void)nextGeneration();
    currentName[0] = '\0';
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

#endif
