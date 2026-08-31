/*
 * SPDX-License-Identifier: MIT
 *
 * Clean-room SPI SD-card and read-only FAT16/FAT32 implementation for the
 * arduino-stc51 plain-C core. No code from Arduino's C++ SD/SdFat stack is used.
 */
#include "SD.h"

#if defined(__SDCC)
# define STC_SD_XDATA __xdata
#else
# define STC_SD_XDATA
#endif

#define SD_CMD0_GO_IDLE_STATE         0u
#define SD_CMD8_SEND_IF_COND          8u
#define SD_CMD13_SEND_STATUS         13u
#define SD_CMD16_SET_BLOCKLEN        16u
#define SD_CMD17_READ_SINGLE_BLOCK   17u
#define SD_CMD24_WRITE_BLOCK         24u
#define SD_CMD41_SD_SEND_OP_COND     41u
#define SD_CMD55_APP_CMD             55u
#define SD_CMD58_READ_OCR            58u

#define SD_R1_IDLE_STATE       0x01u
#define SD_R1_ILLEGAL_COMMAND  0x04u
#define SD_DATA_START_TOKEN    0xfeu
#define SD_WRITE_DATA_ACCEPTED 0x05u

#define SD_SECTOR_SIZE 512u
#define SD_INIT_CLOCK_HZ 100000UL
#define SD_DATA_CLOCK_HZ 400000UL

#define SD_READY_ATTEMPT_LIMIT 60000u
#define SD_READY_TIMEOUT_MS      600UL
#define SD_R1_ATTEMPT_LIMIT       32u
#define SD_R1_TIMEOUT_MS         100UL
#define SD_TOKEN_ATTEMPT_LIMIT 60000u
#define SD_TOKEN_TIMEOUT_MS      600UL
#define SD_INIT_ATTEMPT_LIMIT   1000u
#define SD_INIT_TIMEOUT_MS      2000UL
#define SD_ROOT_SCAN_SECTOR_LIMIT 4096UL
#define SD_UINT32_MAX     0xffffffffUL

#define SD_DIR_ENTRY_SIZE        32u
#define SD_DIR_ENTRIES_PER_SECTOR 16u
#define SD_DIR_ATTRIBUTE          11u
#define SD_DIR_CLUSTER_HIGH       20u
#define SD_DIR_CLUSTER_LOW        26u
#define SD_DIR_FILE_SIZE          28u
#define SD_ATTRIBUTE_DIRECTORY  0x10u
#define SD_ATTRIBUTE_VOLUME_ID  0x08u
#define SD_ATTRIBUTE_LONG_NAME  0x0fu

typedef struct {
    uint8_t mosi_pin;
    uint8_t miso_pin;
    uint8_t sck_pin;
    uint8_t cs_pin;
    uint8_t pins_loaded;

    uint8_t spi_active;
    uint8_t card_ready;
    uint8_t mounted;
    uint8_t card_type;
    uint8_t fat_type;
    uint8_t last_error;

    uint8_t sectors_per_cluster;
    uint8_t fat_count;
    unsigned int root_entry_count;
    unsigned long volume_start;
    unsigned long volume_sectors;
    unsigned long fat_start;
    unsigned long fat_sectors;
    unsigned long root_dir_start;
    unsigned long root_dir_sectors;
    unsigned long data_start;
    unsigned long cluster_count;
    unsigned long root_cluster;

    uint8_t cache_valid;
    unsigned long cache_sector;

    uint8_t file_open;
    unsigned long file_first_cluster;
    unsigned long file_size;
    unsigned long file_position;
    unsigned long file_cluster;
    unsigned long file_cluster_index;
} STCSDState;

/* The library owns exactly one sector cache and keeps all bulky state out of
 * scarce DATA/IDATA. The public header enforces a 1 KiB XDATA floor. */
static STC_SD_XDATA uint8_t sd_sector[SD_SECTOR_SIZE];
static STC_SD_XDATA STCSDState sd_state;

static void sd_set_error(uint8_t error)
{
    sd_state.last_error = error;
}

static void sd_load_default_pins(void)
{
    if (sd_state.pins_loaded == 0u) {
        sd_state.mosi_pin = SD_DEFAULT_MOSI_PIN;
        sd_state.miso_pin = SD_DEFAULT_MISO_PIN;
        sd_state.sck_pin = SD_DEFAULT_SCK_PIN;
        sd_state.cs_pin = SD_DEFAULT_CS_PIN;
        sd_state.pins_loaded = 1u;
    }
}

static void sd_clear_file(void)
{
    sd_state.file_open = 0u;
    sd_state.file_first_cluster = 0UL;
    sd_state.file_size = 0UL;
    sd_state.file_position = 0UL;
    sd_state.file_cluster = 0UL;
    sd_state.file_cluster_index = 0UL;
}

static void sd_clear_volume(void)
{
    sd_state.mounted = 0u;
    sd_state.fat_type = SD_FAT_NONE;
    sd_state.sectors_per_cluster = 0u;
    sd_state.fat_count = 0u;
    sd_state.root_entry_count = 0u;
    sd_state.volume_start = 0UL;
    sd_state.volume_sectors = 0UL;
    sd_state.fat_start = 0UL;
    sd_state.fat_sectors = 0UL;
    sd_state.root_dir_start = 0UL;
    sd_state.root_dir_sectors = 0UL;
    sd_state.data_start = 0UL;
    sd_state.cluster_count = 0UL;
    sd_state.root_cluster = 0UL;
    sd_state.cache_valid = 0u;
    sd_state.cache_sector = 0UL;
    sd_clear_file();
}

static uint8_t sd_pins_conflict(uint8_t left, uint8_t right)
{
    if (left == right) {
        return 1u;
    }
    return (digitalPinsSharePhysicalPad(left, right) != 0) ? 1u : 0u;
}

static uint8_t sd_validate_pins(uint8_t mosi_pin, uint8_t miso_pin,
                                uint8_t sck_pin, uint8_t cs_pin)
{
    if ((digitalPinIsValid(mosi_pin) == 0u) ||
        (digitalPinIsValid(miso_pin) == 0u) ||
        (digitalPinIsValid(sck_pin) == 0u) ||
        (digitalPinIsValid(cs_pin) == 0u)) {
        return SD_ERROR_INVALID_PIN;
    }

    if ((sd_pins_conflict(mosi_pin, miso_pin) != 0u) ||
        (sd_pins_conflict(mosi_pin, sck_pin) != 0u) ||
        (sd_pins_conflict(mosi_pin, cs_pin) != 0u) ||
        (sd_pins_conflict(miso_pin, sck_pin) != 0u) ||
        (sd_pins_conflict(miso_pin, cs_pin) != 0u) ||
        (sd_pins_conflict(sck_pin, cs_pin) != 0u)) {
        return SD_ERROR_PIN_CONFLICT;
    }
    return SD_ERROR_NONE;
}

static uint8_t sd_time_expired(unsigned long start, unsigned long timeout)
{
    return ((unsigned long)(millis() - start) >= timeout) ? 1u : 0u;
}

static void sd_deselect(void)
{
    if (sd_state.spi_active != 0u) {
        digitalWrite(sd_state.cs_pin, HIGH);
        (void)SPI.transfer(0xffu);
    }
}

static uint8_t sd_wait_ready(void)
{
    unsigned int attempts = 0u;
    unsigned long started = millis();

    while ((attempts < SD_READY_ATTEMPT_LIMIT) &&
           (sd_time_expired(started, SD_READY_TIMEOUT_MS) == 0u)) {
        if (SPI.transfer(0xffu) == 0xffu) {
            return 1u;
        }
        ++attempts;
    }
    return 0u;
}

static uint8_t sd_wait_r1(void)
{
    unsigned int attempts = 0u;
    unsigned long started = millis();
    uint8_t response;

    while ((attempts < SD_R1_ATTEMPT_LIMIT) &&
           (sd_time_expired(started, SD_R1_TIMEOUT_MS) == 0u)) {
        response = SPI.transfer(0xffu);
        if ((response & 0x80u) == 0u) {
            return response;
        }
        ++attempts;
    }
    return 0xffu;
}

static uint8_t sd_wait_data_token(void)
{
    unsigned int attempts = 0u;
    unsigned long started = millis();
    uint8_t token = 0xffu;

    while ((attempts < SD_TOKEN_ATTEMPT_LIMIT) &&
           (sd_time_expired(started, SD_TOKEN_TIMEOUT_MS) == 0u)) {
        token = SPI.transfer(0xffu);
        if (token != 0xffu) {
            break;
        }
        ++attempts;
    }
    return token;
}

/* Leaves CS asserted only after receiving an R1 response. Any timeout path
 * releases CS before returning. */
static uint8_t sd_send_command(uint8_t command, unsigned long argument)
{
    uint8_t crc = 0x01u;
    uint8_t response;

    /* Another SPI client may have changed clock, bit order, or mode since the
     * preceding SD operation. Reassert the card transaction on every command. */
    SPI.beginTransaction((sd_state.card_ready != 0u) ?
                         SD_DATA_CLOCK_HZ : SD_INIT_CLOCK_HZ,
                         MSBFIRST, SPI_MODE0);
    digitalWrite(sd_state.cs_pin, LOW);
    if (sd_wait_ready() == 0u) {
        sd_set_error(SD_ERROR_CARD_TIMEOUT);
        sd_deselect();
        return 0xffu;
    }

    if (command == SD_CMD0_GO_IDLE_STATE) {
        crc = 0x95u;
    } else if (command == SD_CMD8_SEND_IF_COND) {
        crc = 0x87u;
    }

    (void)SPI.transfer((uint8_t)(0x40u | command));
    (void)SPI.transfer((uint8_t)(argument >> 24));
    (void)SPI.transfer((uint8_t)(argument >> 16));
    (void)SPI.transfer((uint8_t)(argument >> 8));
    (void)SPI.transfer((uint8_t)argument);
    (void)SPI.transfer(crc);

    response = sd_wait_r1();
    if (response == 0xffu) {
        sd_set_error(SD_ERROR_CARD_TIMEOUT);
        sd_deselect();
    }
    return response;
}

static uint8_t sd_initialize_card(void)
{
    unsigned int attempts;
    unsigned long started;
    uint8_t response = 0xffu;
    uint8_t card_is_v2 = 0u;
    uint8_t index;
    uint8_t r7[4];

    digitalWrite(sd_state.cs_pin, HIGH);
    delay(1UL);
    for (index = 0u; index < 10u; ++index) {
        (void)SPI.transfer(0xffu);
    }

    attempts = 0u;
    started = millis();
    while ((attempts < SD_INIT_ATTEMPT_LIMIT) &&
           (sd_time_expired(started, SD_INIT_TIMEOUT_MS) == 0u)) {
        response = sd_send_command(SD_CMD0_GO_IDLE_STATE, 0UL);
        sd_deselect();
        if (response == SD_R1_IDLE_STATE) {
            break;
        }
        ++attempts;
    }
    if (response != SD_R1_IDLE_STATE) {
        sd_set_error(SD_ERROR_CARD_TIMEOUT);
        return 0u;
    }

    response = sd_send_command(SD_CMD8_SEND_IF_COND, 0x000001aaUL);
    if (response == SD_R1_IDLE_STATE) {
        for (index = 0u; index < 4u; ++index) {
            r7[index] = SPI.transfer(0xffu);
        }
        sd_deselect();
        if ((r7[2] != 0x01u) || (r7[3] != 0xaau)) {
            sd_set_error(SD_ERROR_CARD_UNSUPPORTED);
            return 0u;
        }
        card_is_v2 = 1u;
    } else {
        sd_deselect();
        if (response != (SD_R1_IDLE_STATE | SD_R1_ILLEGAL_COMMAND)) {
            if (response != 0xffu) {
                sd_set_error(SD_ERROR_CARD_RESPONSE);
            }
            return 0u;
        }
    }

    attempts = 0u;
    started = millis();
    response = 0xffu;
    while ((attempts < SD_INIT_ATTEMPT_LIMIT) &&
           (sd_time_expired(started, SD_INIT_TIMEOUT_MS) == 0u)) {
        response = sd_send_command(SD_CMD55_APP_CMD, 0UL);
        sd_deselect();
        if (response > SD_R1_IDLE_STATE) {
            sd_set_error(SD_ERROR_CARD_RESPONSE);
            return 0u;
        }

        response = sd_send_command(SD_CMD41_SD_SEND_OP_COND,
                                   (card_is_v2 != 0u) ?
                                   0x40000000UL : 0UL);
        sd_deselect();
        if (response == 0u) {
            break;
        }
        if (response != SD_R1_IDLE_STATE) {
            sd_set_error(SD_ERROR_CARD_RESPONSE);
            return 0u;
        }
        ++attempts;
    }
    if (response != 0u) {
        sd_set_error(SD_ERROR_CARD_TIMEOUT);
        return 0u;
    }

    if (card_is_v2 != 0u) {
        response = sd_send_command(SD_CMD58_READ_OCR, 0UL);
        if (response != 0u) {
            sd_deselect();
            if (response != 0xffu) {
                sd_set_error(SD_ERROR_CARD_RESPONSE);
            }
            return 0u;
        }
        for (index = 0u; index < 4u; ++index) {
            r7[index] = SPI.transfer(0xffu);
        }
        sd_deselect();
        if ((r7[0] & 0x80u) == 0u) {
            sd_set_error(SD_ERROR_CARD_RESPONSE);
            return 0u;
        }
        sd_state.card_type = ((r7[0] & 0x40u) != 0u) ?
            SD_CARD_SDHC : SD_CARD_SD2;
    } else {
        sd_state.card_type = SD_CARD_SD1;
    }

    if (sd_state.card_type != SD_CARD_SDHC) {
        response = sd_send_command(SD_CMD16_SET_BLOCKLEN,
                                   (unsigned long)SD_SECTOR_SIZE);
        sd_deselect();
        if (response != 0u) {
            if (response != 0xffu) {
                sd_set_error(SD_ERROR_CARD_RESPONSE);
            }
            return 0u;
        }
    }

    sd_state.card_ready = 1u;
    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

static uint8_t sd_sector_argument(unsigned long sector,
                                  unsigned long *argument)
{
    if (sd_state.card_type == SD_CARD_SDHC) {
        *argument = sector;
        return 1u;
    }
    if (sector > 0x007fffffUL) {
        sd_set_error(SD_ERROR_ADDRESS_OVERFLOW);
        return 0u;
    }
    *argument = sector << 9;
    return 1u;
}

static uint8_t sd_read_block_internal(unsigned long sector, uint8_t *buffer)
{
    unsigned long argument;
    unsigned int index;
    uint8_t response;
    uint8_t token;

    if (sd_state.card_ready == 0u) {
        sd_set_error(SD_ERROR_NOT_INITIALIZED);
        return 0u;
    }
    if (buffer == NULL) {
        sd_set_error(SD_ERROR_INVALID_ARGUMENT);
        return 0u;
    }
    if (sd_sector_argument(sector, &argument) == 0u) {
        return 0u;
    }

    response = sd_send_command(SD_CMD17_READ_SINGLE_BLOCK, argument);
    if (response != 0u) {
        sd_deselect();
        if (response != 0xffu) {
            sd_set_error(SD_ERROR_CARD_RESPONSE);
        }
        return 0u;
    }

    token = sd_wait_data_token();
    if (token != SD_DATA_START_TOKEN) {
        sd_deselect();
        sd_set_error((token == 0xffu) ? SD_ERROR_CARD_TIMEOUT :
                     SD_ERROR_READ_TOKEN);
        return 0u;
    }

    for (index = 0u; index < SD_SECTOR_SIZE; ++index) {
        buffer[index] = SPI.transfer(0xffu);
    }
    (void)SPI.transfer(0xffu);
    (void)SPI.transfer(0xffu);
    sd_deselect();
    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

static uint8_t sd_write_block_internal(unsigned long sector,
                                       const uint8_t *buffer)
{
    unsigned long argument;
    unsigned int index;
    uint8_t response;
    uint8_t data_response;
    uint8_t card_status;

    if (sd_state.card_ready == 0u) {
        sd_set_error(SD_ERROR_NOT_INITIALIZED);
        return 0u;
    }
    if (buffer == NULL) {
        sd_set_error(SD_ERROR_INVALID_ARGUMENT);
        return 0u;
    }
    if (sd_sector_argument(sector, &argument) == 0u) {
        return 0u;
    }

    response = sd_send_command(SD_CMD24_WRITE_BLOCK, argument);
    if (response != 0u) {
        sd_deselect();
        if (response != 0xffu) {
            sd_set_error(SD_ERROR_CARD_RESPONSE);
        }
        return 0u;
    }

    (void)SPI.transfer(0xffu);
    (void)SPI.transfer(SD_DATA_START_TOKEN);
    for (index = 0u; index < SD_SECTOR_SIZE; ++index) {
        (void)SPI.transfer(buffer[index]);
    }
    (void)SPI.transfer(0xffu);
    (void)SPI.transfer(0xffu);

    data_response = (uint8_t)(SPI.transfer(0xffu) & 0x1fu);
    if (data_response != SD_WRITE_DATA_ACCEPTED) {
        sd_deselect();
        sd_set_error(SD_ERROR_WRITE_REJECTED);
        return 0u;
    }
    if (sd_wait_ready() == 0u) {
        sd_deselect();
        sd_set_error(SD_ERROR_CARD_TIMEOUT);
        return 0u;
    }
    sd_deselect();

    response = sd_send_command(SD_CMD13_SEND_STATUS, 0UL);
    if (response != 0u) {
        sd_deselect();
        if (response != 0xffu) {
            sd_set_error(SD_ERROR_CARD_RESPONSE);
        }
        return 0u;
    }
    card_status = SPI.transfer(0xffu);
    sd_deselect();
    if (card_status != 0u) {
        sd_set_error(SD_ERROR_WRITE_STATUS);
        return 0u;
    }

    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

/* FAT fields are decoded byte by byte. This is required for the big-endian
 * MCS251 backend as well as for unaligned BPB and directory fields. */
static unsigned int sd_load_le16(const uint8_t *value)
{
    return (unsigned int)value[0] |
        ((unsigned int)value[1] << 8);
}

static unsigned long sd_load_le32(const uint8_t *value)
{
    return (unsigned long)value[0] |
        ((unsigned long)value[1] << 8) |
        ((unsigned long)value[2] << 16) |
        ((unsigned long)value[3] << 24);
}

static uint8_t sd_add_u32(unsigned long left, unsigned long right,
                          unsigned long *result)
{
    if (left > (SD_UINT32_MAX - right)) {
        return 0u;
    }
    *result = left + right;
    return 1u;
}

static uint8_t sd_boot_sector_plausible(void)
{
    uint8_t sectors_per_cluster = sd_sector[13];
    unsigned int reserved = sd_load_le16(&sd_sector[14]);
    uint8_t fats = sd_sector[16];
    unsigned long total = (unsigned long)sd_load_le16(&sd_sector[19]);
    unsigned long fat_size = (unsigned long)sd_load_le16(&sd_sector[22]);

    if (total == 0UL) {
        total = sd_load_le32(&sd_sector[32]);
    }
    if (fat_size == 0UL) {
        fat_size = sd_load_le32(&sd_sector[36]);
    }

    return ((sd_sector[510] == 0x55u) &&
            (sd_sector[511] == 0xaau) &&
            (sd_load_le16(&sd_sector[11]) == SD_SECTOR_SIZE) &&
            (sectors_per_cluster != 0u) &&
            ((sectors_per_cluster &
              (uint8_t)(sectors_per_cluster - 1u)) == 0u) &&
            (sectors_per_cluster <= 128u) &&
            (reserved != 0u) &&
            ((fats == 1u) || (fats == 2u)) &&
            (total != 0UL) &&
            (fat_size != 0UL)) ? 1u : 0u;
}

static uint8_t sd_mbr_partition_type_supported(uint8_t type)
{
    switch (type) {
    case 0x01u: /* FAT12; parser will return FAT12_UNSUPPORTED explicitly. */
    case 0x04u: /* FAT16, less than 32 MiB */
    case 0x06u: /* FAT16 */
    case 0x0bu: /* FAT32 CHS */
    case 0x0cu: /* FAT32 LBA */
    case 0x0eu: /* FAT16 LBA */
    case 0x11u: /* Hidden FAT12 */
    case 0x14u: /* Hidden FAT16, less than 32 MiB */
    case 0x16u: /* Hidden FAT16 */
    case 0x1bu: /* Hidden FAT32 CHS */
    case 0x1cu: /* Hidden FAT32 LBA */
    case 0x1eu: /* Hidden FAT16 LBA */
        return 1u;
    default:
        return 0u;
    }
}

static uint8_t sd_load_sector(unsigned long sector)
{
    if ((sd_state.cache_valid != 0u) &&
        (sd_state.cache_sector == sector)) {
        return 1u;
    }
    if (sd_read_block_internal(sector, sd_sector) == 0u) {
        sd_state.cache_valid = 0u;
        return 0u;
    }
    sd_state.cache_sector = sector;
    sd_state.cache_valid = 1u;
    return 1u;
}

static uint8_t sd_parse_volume(unsigned long volume_start,
                               unsigned long partition_sectors)
{
    uint8_t sectors_per_cluster;
    uint8_t fat_count;
    unsigned int reserved;
    unsigned int root_entries;
    unsigned long total_sectors;
    unsigned long fat_sectors;
    unsigned long root_dir_sectors;
    unsigned long fat_area_sectors;
    unsigned long root_relative;
    unsigned long data_relative;
    unsigned long data_sectors;
    unsigned long cluster_count;
    unsigned long required_fat_sectors;
    unsigned long fat_relative;
    unsigned long value;
    unsigned long volume_end;
    unsigned int fat32_flags;
    uint8_t active_fat = 0u;
    uint8_t fat_type;

    if (sd_boot_sector_plausible() == 0u) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }

    sectors_per_cluster = sd_sector[13];
    reserved = sd_load_le16(&sd_sector[14]);
    fat_count = sd_sector[16];
    root_entries = sd_load_le16(&sd_sector[17]);
    total_sectors = (unsigned long)sd_load_le16(&sd_sector[19]);
    if (total_sectors == 0UL) {
        total_sectors = sd_load_le32(&sd_sector[32]);
    }
    fat_sectors = (unsigned long)sd_load_le16(&sd_sector[22]);
    if (fat_sectors == 0UL) {
        fat_sectors = sd_load_le32(&sd_sector[36]);
    }

    if ((partition_sectors != 0UL) &&
        (total_sectors > partition_sectors)) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }
    if (sd_add_u32(volume_start, total_sectors, &volume_end) == 0u) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }
    (void)volume_end;

    root_dir_sectors =
        (((unsigned long)root_entries * SD_DIR_ENTRY_SIZE) +
         (SD_SECTOR_SIZE - 1u)) / SD_SECTOR_SIZE;
    if (fat_sectors > (SD_UINT32_MAX / (unsigned long)fat_count)) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }
    fat_area_sectors = fat_sectors * (unsigned long)fat_count;
    if (sd_add_u32((unsigned long)reserved, fat_area_sectors,
                   &root_relative) == 0u ||
        sd_add_u32(root_relative, root_dir_sectors,
                   &data_relative) == 0u ||
        (data_relative >= total_sectors)) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }

    data_sectors = total_sectors - data_relative;
    cluster_count = data_sectors / (unsigned long)sectors_per_cluster;
    if (cluster_count < 4085UL) {
        sd_set_error(SD_ERROR_FAT12_UNSUPPORTED);
        return 0u;
    }
    fat_type = (cluster_count < 65525UL) ? SD_FAT16 : SD_FAT32;

    if (fat_type == SD_FAT16) {
        if ((root_entries == 0u) ||
            (sd_load_le16(&sd_sector[22]) == 0u)) {
            sd_set_error(SD_ERROR_BAD_VOLUME);
            return 0u;
        }
        required_fat_sectors =
            (cluster_count + 2UL + 255UL) / 256UL;
    } else {
        if ((root_entries != 0u) ||
            (sd_load_le16(&sd_sector[22]) != 0u) ||
            (sd_load_le16(&sd_sector[42]) != 0u) ||
            (cluster_count > 0x0ffffff5UL)) {
            sd_set_error(SD_ERROR_BAD_VOLUME);
            return 0u;
        }
        fat32_flags = sd_load_le16(&sd_sector[40]);
        if ((fat32_flags & 0x0080u) != 0u) {
            active_fat = (uint8_t)(fat32_flags & 0x000fu);
            if (active_fat >= fat_count) {
                sd_set_error(SD_ERROR_BAD_VOLUME);
                return 0u;
            }
        }
        required_fat_sectors =
            (cluster_count + 2UL + 127UL) / 128UL;
    }
    if (fat_sectors < required_fat_sectors) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }

    fat_relative = fat_sectors * (unsigned long)active_fat;
    if (sd_add_u32((unsigned long)reserved, fat_relative,
                   &fat_relative) == 0u ||
        sd_add_u32(volume_start, fat_relative, &value) == 0u) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }
    sd_state.fat_start = value;
    if (sd_add_u32(volume_start, root_relative, &value) == 0u) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }
    sd_state.root_dir_start = value;
    if (sd_add_u32(volume_start, data_relative, &value) == 0u) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
        return 0u;
    }
    sd_state.data_start = value;

    sd_state.root_cluster = 0UL;
    if (fat_type == SD_FAT32) {
        sd_state.root_cluster = sd_load_le32(&sd_sector[44]) & 0x0fffffffUL;
        if ((sd_state.root_cluster < 2UL) ||
            (sd_state.root_cluster > (cluster_count + 1UL))) {
            sd_set_error(SD_ERROR_BAD_VOLUME);
            return 0u;
        }
    }

    sd_state.volume_start = volume_start;
    sd_state.volume_sectors = total_sectors;
    sd_state.fat_sectors = fat_sectors;
    sd_state.root_dir_sectors = root_dir_sectors;
    sd_state.sectors_per_cluster = sectors_per_cluster;
    sd_state.fat_count = fat_count;
    sd_state.root_entry_count = root_entries;
    sd_state.cluster_count = cluster_count;
    sd_state.fat_type = fat_type;
    sd_state.cache_valid = 0u;
    sd_state.mounted = 1u;
    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

static uint8_t sd_mount(void)
{
    unsigned long volume_start;
    unsigned long partition_sectors;
    uint8_t first_error;
    uint8_t mbr_candidate;

    sd_clear_volume();
    if (sd_read_block_internal(0UL, sd_sector) == 0u) {
        return 0u;
    }
    sd_state.cache_sector = 0UL;
    sd_state.cache_valid = 1u;

    /* Match the conventional SD layout probe order: MBR partition 1 first,
     * then sector-zero superfloppy. Re-read LBA0 before fallback because the
     * one cache buffer was overwritten by the partition boot-sector attempt. */
    volume_start = sd_load_le32(&sd_sector[454]);
    partition_sectors = sd_load_le32(&sd_sector[458]);
    mbr_candidate = ((sd_sector[510] == 0x55u) &&
                     (sd_sector[511] == 0xaau) &&
                     ((sd_sector[446] == 0x00u) ||
                      (sd_sector[446] == 0x80u)) &&
                     (sd_mbr_partition_type_supported(sd_sector[450]) != 0u) &&
                     (volume_start != 0UL) &&
                     (partition_sectors != 0UL) &&
                     (volume_start <=
                      (SD_UINT32_MAX - partition_sectors))) ? 1u : 0u;
    first_error = SD_ERROR_NONE;

    if (mbr_candidate != 0u) {
        if (sd_read_block_internal(volume_start, sd_sector) != 0u) {
            sd_state.cache_sector = volume_start;
            sd_state.cache_valid = 1u;
            if (sd_parse_volume(volume_start, partition_sectors) != 0u) {
                return 1u;
            }
        }
        first_error = sd_state.last_error;

        if (sd_read_block_internal(0UL, sd_sector) == 0u) {
            if (first_error != SD_ERROR_NONE) {
                sd_set_error(first_error);
            }
            return 0u;
        }
        sd_state.cache_sector = 0UL;
        sd_state.cache_valid = 1u;
    }

    if ((sd_boot_sector_plausible() != 0u) &&
        (sd_parse_volume(0UL, 0UL) != 0u)) {
        return 1u;
    }
    if (first_error != SD_ERROR_NONE) {
        sd_set_error(first_error);
    } else if (sd_state.last_error == SD_ERROR_NONE) {
        sd_set_error(SD_ERROR_BAD_VOLUME);
    }
    return 0u;
}

static uint8_t sd_cluster_to_sector(unsigned long cluster,
                                    unsigned long *sector)
{
    unsigned long relative;

    if ((cluster < 2UL) ||
        (cluster > (sd_state.cluster_count + 1UL))) {
        sd_set_error(SD_ERROR_BAD_CLUSTER);
        return 0u;
    }
    relative = cluster - 2UL;
    if (relative >
        (SD_UINT32_MAX / (unsigned long)sd_state.sectors_per_cluster)) {
        sd_set_error(SD_ERROR_BAD_CLUSTER);
        return 0u;
    }
    relative *= (unsigned long)sd_state.sectors_per_cluster;
    if (sd_add_u32(sd_state.data_start, relative, sector) == 0u) {
        sd_set_error(SD_ERROR_BAD_CLUSTER);
        return 0u;
    }
    return 1u;
}

static uint8_t sd_next_cluster(unsigned long cluster,
                               unsigned long *next_cluster,
                               uint8_t *is_end)
{
    unsigned long byte_offset;
    unsigned long fat_sector;
    unsigned int offset_in_sector;
    unsigned long value;

    if ((cluster < 2UL) ||
        (cluster > (sd_state.cluster_count + 1UL))) {
        sd_set_error(SD_ERROR_BAD_CLUSTER);
        return 0u;
    }

    if (sd_state.fat_type == SD_FAT16) {
        byte_offset = cluster << 1;
    } else {
        if (cluster > 0x3fffffffUL) {
            sd_set_error(SD_ERROR_BAD_CLUSTER);
            return 0u;
        }
        byte_offset = cluster << 2;
    }
    if ((byte_offset / SD_SECTOR_SIZE) >= sd_state.fat_sectors ||
        sd_add_u32(sd_state.fat_start,
                   byte_offset / SD_SECTOR_SIZE, &fat_sector) == 0u) {
        sd_set_error(SD_ERROR_BAD_CLUSTER);
        return 0u;
    }
    if (sd_load_sector(fat_sector) == 0u) {
        return 0u;
    }
    offset_in_sector = (unsigned int)(byte_offset & 0x01ffUL);

    if (sd_state.fat_type == SD_FAT16) {
        value = (unsigned long)sd_load_le16(&sd_sector[offset_in_sector]);
        if (value >= 0xfff8UL) {
            *is_end = 1u;
            *next_cluster = 0UL;
            return 1u;
        }
        if ((value < 2UL) || (value == 0xfff7UL) ||
            (value > (sd_state.cluster_count + 1UL))) {
            sd_set_error(SD_ERROR_BAD_CLUSTER);
            return 0u;
        }
    } else {
        value = sd_load_le32(&sd_sector[offset_in_sector]) & 0x0fffffffUL;
        if (value >= 0x0ffffff8UL) {
            *is_end = 1u;
            *next_cluster = 0UL;
            return 1u;
        }
        if ((value < 2UL) || (value == 0x0ffffff7UL) ||
            (value > (sd_state.cluster_count + 1UL))) {
            sd_set_error(SD_ERROR_BAD_CLUSTER);
            return 0u;
        }
    }

    *is_end = 0u;
    *next_cluster = value;
    return 1u;
}

static uint8_t sd_short_name_character_valid(uint8_t value)
{
    if ((value <= 0x20u) || (value >= 0x7fu)) {
        return 0u;
    }
    switch (value) {
    case '"':
    case '*':
    case '+':
    case ',':
    case '/':
    case ':':
    case ';':
    case '<':
    case '=':
    case '>':
    case '?':
    case '[':
    case '\\':
    case ']':
    case '|':
        return 0u;
    default:
        return 1u;
    }
}

static uint8_t sd_format_short_name(const char *name, uint8_t *formatted)
{
    uint8_t index;
    uint8_t base_length = 0u;
    uint8_t extension_length = 0u;
    uint8_t in_extension = 0u;
    uint8_t value;

    if ((name == NULL) || (formatted == NULL)) {
        return 0u;
    }
    if (*name == '/') {
        ++name;
    }
    if (*name == '\0') {
        return 0u;
    }
    for (index = 0u; index < 11u; ++index) {
        formatted[index] = (uint8_t)' ';
    }

    while (*name != '\0') {
        value = (uint8_t)*name++;
        if (value == (uint8_t)'.') {
            if ((in_extension != 0u) || (base_length == 0u)) {
                return 0u;
            }
            in_extension = 1u;
            continue;
        }
        if (sd_short_name_character_valid(value) == 0u) {
            return 0u;
        }
        if ((value >= (uint8_t)'a') && (value <= (uint8_t)'z')) {
            value = (uint8_t)(value - ((uint8_t)'a' - (uint8_t)'A'));
        }
        if (in_extension == 0u) {
            if (base_length >= 8u) {
                return 0u;
            }
            formatted[base_length++] = value;
        } else {
            if (extension_length >= 3u) {
                return 0u;
            }
            formatted[8u + extension_length++] = value;
        }
    }
    if ((base_length == 0u) ||
        ((in_extension != 0u) && (extension_length == 0u))) {
        return 0u;
    }
    return 1u;
}

/* 0: continue, 1: found, 2: end marker. */
static uint8_t sd_search_loaded_directory_sector(
    const uint8_t *target, unsigned int entry_limit,
    unsigned long *cluster, unsigned long *size, uint8_t *attribute)
{
    unsigned int entry;
    unsigned int offset;
    uint8_t index;
    uint8_t match;
    uint8_t first;
    uint8_t attr;

    if (entry_limit > SD_DIR_ENTRIES_PER_SECTOR) {
        entry_limit = SD_DIR_ENTRIES_PER_SECTOR;
    }
    for (entry = 0u; entry < entry_limit; ++entry) {
        offset = entry * SD_DIR_ENTRY_SIZE;
        first = sd_sector[offset];
        if (first == 0x00u) {
            return 2u;
        }
        if (first == 0xe5u) {
            continue;
        }
        attr = sd_sector[offset + SD_DIR_ATTRIBUTE];
        if ((attr == SD_ATTRIBUTE_LONG_NAME) ||
            ((attr & SD_ATTRIBUTE_VOLUME_ID) != 0u)) {
            continue;
        }

        match = 1u;
        for (index = 0u; index < 11u; ++index) {
            if (sd_sector[offset + index] != target[index]) {
                match = 0u;
                break;
            }
        }
        if (match != 0u) {
            *cluster = (unsigned long)
                sd_load_le16(&sd_sector[offset + SD_DIR_CLUSTER_LOW]);
            if (sd_state.fat_type == SD_FAT32) {
                *cluster |= ((unsigned long)
                    sd_load_le16(&sd_sector[offset + SD_DIR_CLUSTER_HIGH]))
                    << 16;
                *cluster &= 0x0fffffffUL;
            }
            *size = sd_load_le32(&sd_sector[offset + SD_DIR_FILE_SIZE]);
            *attribute = attr;
            return 1u;
        }
    }
    return 0u;
}

static uint8_t sd_find_root_entry(const uint8_t *target,
                                  unsigned long *cluster,
                                  unsigned long *size,
                                  uint8_t *attribute)
{
    unsigned long sector;
    unsigned long cluster_value;
    unsigned long cluster_sector;
    unsigned long next_cluster;
    unsigned long hops;
    unsigned long sectors_scanned;
    unsigned int remaining_entries;
    unsigned int limit;
    uint8_t sector_in_cluster;
    uint8_t is_end;
    uint8_t result;

    if (sd_state.fat_type == SD_FAT16) {
        remaining_entries = sd_state.root_entry_count;
        sector = sd_state.root_dir_start;
        while (remaining_entries != 0u) {
            if (sd_load_sector(sector) == 0u) {
                return 0u;
            }
            limit = (remaining_entries > SD_DIR_ENTRIES_PER_SECTOR) ?
                SD_DIR_ENTRIES_PER_SECTOR : remaining_entries;
            result = sd_search_loaded_directory_sector(
                target, limit, cluster, size, attribute);
            if (result == 1u) {
                return 1u;
            }
            if (result == 2u) {
                break;
            }
            remaining_entries -= limit;
            ++sector;
        }
        sd_set_error(SD_ERROR_NOT_FOUND);
        return 0u;
    }

    cluster_value = sd_state.root_cluster;
    hops = 0UL;
    sectors_scanned = 0UL;
    while (hops < sd_state.cluster_count) {
        if (sd_cluster_to_sector(cluster_value, &cluster_sector) == 0u) {
            return 0u;
        }
        for (sector_in_cluster = 0u;
             sector_in_cluster < sd_state.sectors_per_cluster;
             ++sector_in_cluster) {
            if (sectors_scanned >= SD_ROOT_SCAN_SECTOR_LIMIT) {
                sd_set_error(SD_ERROR_BAD_CLUSTER);
                return 0u;
            }
            if (sd_load_sector(cluster_sector +
                               (unsigned long)sector_in_cluster) == 0u) {
                return 0u;
            }
            ++sectors_scanned;
            result = sd_search_loaded_directory_sector(
                target, SD_DIR_ENTRIES_PER_SECTOR,
                cluster, size, attribute);
            if (result == 1u) {
                return 1u;
            }
            if (result == 2u) {
                sd_set_error(SD_ERROR_NOT_FOUND);
                return 0u;
            }
        }
        if (sd_next_cluster(cluster_value, &next_cluster, &is_end) == 0u) {
            return 0u;
        }
        if (is_end != 0u) {
            sd_set_error(SD_ERROR_NOT_FOUND);
            return 0u;
        }
        cluster_value = next_cluster;
        ++hops;
    }

    sd_set_error(SD_ERROR_BAD_CLUSTER);
    return 0u;
}

static uint8_t sd_prepare_file_sector(void)
{
    unsigned long cluster_bytes;
    unsigned long target_cluster_index;
    unsigned long next_cluster;
    unsigned long sector;
    uint8_t is_end;

    if ((sd_state.file_open == 0u) ||
        (sd_state.file_position >= sd_state.file_size)) {
        return 0u;
    }

    cluster_bytes = (unsigned long)sd_state.sectors_per_cluster *
        (unsigned long)SD_SECTOR_SIZE;
    target_cluster_index = sd_state.file_position / cluster_bytes;
    if (target_cluster_index >= sd_state.cluster_count) {
        sd_set_error(SD_ERROR_BAD_CLUSTER);
        return 0u;
    }

    if ((sd_state.file_cluster < 2UL) ||
        (target_cluster_index < sd_state.file_cluster_index)) {
        sd_state.file_cluster = sd_state.file_first_cluster;
        sd_state.file_cluster_index = 0UL;
    }
    while (sd_state.file_cluster_index < target_cluster_index) {
        if (sd_next_cluster(sd_state.file_cluster, &next_cluster,
                            &is_end) == 0u) {
            return 0u;
        }
        if (is_end != 0u) {
            sd_set_error(SD_ERROR_BAD_CLUSTER);
            return 0u;
        }
        sd_state.file_cluster = next_cluster;
        ++sd_state.file_cluster_index;
    }

    if (sd_cluster_to_sector(sd_state.file_cluster, &sector) == 0u) {
        return 0u;
    }
    sector += (sd_state.file_position / SD_SECTOR_SIZE) %
        (unsigned long)sd_state.sectors_per_cluster;
    return sd_load_sector(sector);
}

uint8_t SD_setPins(uint8_t mosi_pin, uint8_t miso_pin, uint8_t sck_pin,
                   uint8_t cs_pin) STC_SD_REENTRANT
{
    uint8_t validation = sd_validate_pins(mosi_pin, miso_pin, sck_pin, cs_pin);

    if (validation != SD_ERROR_NONE) {
        sd_set_error(validation);
        return 0u;
    }
    if (sd_state.spi_active != 0u) {
        SD_end();
    }
    sd_state.mosi_pin = mosi_pin;
    sd_state.miso_pin = miso_pin;
    sd_state.sck_pin = sck_pin;
    sd_state.cs_pin = cs_pin;
    sd_state.pins_loaded = 1u;
    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

uint8_t SD_begin(uint8_t cs_pin) STC_SD_REENTRANT
{
    uint8_t validation;
    uint8_t saved_error;

    sd_load_default_pins();
    validation = sd_validate_pins(sd_state.mosi_pin, sd_state.miso_pin,
                                  sd_state.sck_pin, cs_pin);
    if (validation != SD_ERROR_NONE) {
        sd_set_error(validation);
        return 0u;
    }
    if (sd_state.spi_active != 0u) {
        SD_end();
    }

    sd_state.cs_pin = cs_pin;
    sd_state.card_ready = 0u;
    sd_state.card_type = SD_CARD_NONE;
    sd_clear_volume();

    SPI.setPins(sd_state.mosi_pin, sd_state.miso_pin,
                sd_state.sck_pin, sd_state.cs_pin);
    digitalWrite(sd_state.cs_pin, HIGH);
    SPI.begin();
    SPI.beginTransaction(SD_INIT_CLOCK_HZ, MSBFIRST, SPI_MODE0);
    sd_state.spi_active = 1u;

    if (sd_initialize_card() == 0u) {
        saved_error = sd_state.last_error;
        sd_deselect();
        SPI.endTransaction();
        SPI.end();
        sd_state.spi_active = 0u;
        sd_state.card_ready = 0u;
        sd_state.card_type = SD_CARD_NONE;
        sd_clear_volume();
        sd_set_error(saved_error);
        return 0u;
    }

    SPI.beginTransaction(SD_DATA_CLOCK_HZ, MSBFIRST, SPI_MODE0);
    if (sd_mount() == 0u) {
        /* The card remains available to readBlock/writeBlock so a caller can
         * inspect a non-FAT or damaged layout after begin() reports failure. */
        return 0u;
    }
    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

uint8_t SD_beginDefault(void) STC_SD_REENTRANT
{
    sd_load_default_pins();
    return SD_begin(sd_state.cs_pin);
}

void SD_end(void) STC_SD_REENTRANT
{
    if (sd_state.spi_active != 0u) {
        sd_deselect();
        SPI.endTransaction();
        SPI.end();
    }
    sd_state.spi_active = 0u;
    sd_state.card_ready = 0u;
    sd_state.card_type = SD_CARD_NONE;
    sd_clear_volume();
    sd_set_error(SD_ERROR_NONE);
}

uint8_t SD_cardType(void) STC_SD_REENTRANT
{
    return sd_state.card_type;
}

uint8_t SD_fatType(void) STC_SD_REENTRANT
{
    return sd_state.fat_type;
}

uint8_t SD_error(void) STC_SD_REENTRANT
{
    return sd_state.last_error;
}

uint8_t SD_readBlock(unsigned long sector, uint8_t *buffer)
                     STC_SD_REENTRANT
{
    return sd_read_block_internal(sector, buffer);
}

uint8_t SD_writeBlock(unsigned long sector, const uint8_t *buffer)
                      STC_SD_REENTRANT
{
    uint8_t result = sd_write_block_internal(sector, buffer);

    sd_state.cache_valid = 0u;
    return result;
}

uint8_t SD_exists(const char *name) STC_SD_REENTRANT
{
    uint8_t target[11];
    unsigned long cluster;
    unsigned long size;
    uint8_t attribute;

    if (sd_state.mounted == 0u) {
        sd_set_error(SD_ERROR_NOT_INITIALIZED);
        return 0u;
    }
    if (sd_format_short_name(name, target) == 0u) {
        sd_set_error(SD_ERROR_INVALID_ARGUMENT);
        return 0u;
    }
    if (sd_find_root_entry(target, &cluster, &size, &attribute) == 0u) {
        return 0u;
    }
    (void)cluster;
    (void)size;
    (void)attribute;
    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

uint8_t SD_open(const char *name, uint8_t mode) STC_SD_REENTRANT
{
    uint8_t target[11];
    unsigned long cluster;
    unsigned long size;
    uint8_t attribute;

    if (sd_state.mounted == 0u) {
        sd_set_error(SD_ERROR_NOT_INITIALIZED);
        return 0u;
    }
    if (mode != FILE_READ) {
        sd_set_error(((mode == FILE_WRITE) || ((mode & 0x02u) != 0u)) ?
                     SD_ERROR_READ_ONLY : SD_ERROR_INVALID_ARGUMENT);
        return 0u;
    }
    if (sd_format_short_name(name, target) == 0u) {
        sd_set_error(SD_ERROR_INVALID_ARGUMENT);
        return 0u;
    }
    sd_clear_file();
    if (sd_find_root_entry(target, &cluster, &size, &attribute) == 0u) {
        return 0u;
    }
    if ((attribute & SD_ATTRIBUTE_DIRECTORY) != 0u) {
        sd_set_error(SD_ERROR_NOT_A_FILE);
        return 0u;
    }
    if ((size != 0UL) &&
        ((cluster < 2UL) ||
         (cluster > (sd_state.cluster_count + 1UL)))) {
        sd_set_error(SD_ERROR_BAD_CLUSTER);
        return 0u;
    }

    sd_state.file_open = 1u;
    sd_state.file_first_cluster = cluster;
    sd_state.file_size = size;
    sd_state.file_position = 0UL;
    sd_state.file_cluster = cluster;
    sd_state.file_cluster_index = 0UL;
    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

int SD_peek(void) STC_SD_REENTRANT
{
    if (sd_state.file_open == 0u) {
        sd_set_error(SD_ERROR_NOT_INITIALIZED);
        return -1;
    }
    if (sd_state.file_position >= sd_state.file_size) {
        sd_set_error(SD_ERROR_NONE);
        return -1;
    }
    if (sd_prepare_file_sector() == 0u) {
        return -1;
    }
    sd_set_error(SD_ERROR_NONE);
    return (int)sd_sector[(unsigned int)
        (sd_state.file_position & 0x01ffUL)];
}

int SD_read(void) STC_SD_REENTRANT
{
    int value = SD_peek();

    if (value >= 0) {
        ++sd_state.file_position;
    }
    return value;
}

size_t SD_readBytes(uint8_t *buffer, size_t length) STC_SD_REENTRANT
{
    size_t count = 0u;
    int value;

    if (sd_state.file_open == 0u) {
        sd_set_error(SD_ERROR_NOT_INITIALIZED);
        return 0u;
    }
    if ((buffer == NULL) && (length != 0u)) {
        sd_set_error(SD_ERROR_INVALID_ARGUMENT);
        return 0u;
    }
    if (length == 0u) {
        sd_set_error(SD_ERROR_NONE);
        return 0u;
    }
    while (count < length) {
        value = SD_read();
        if (value < 0) {
            break;
        }
        buffer[count++] = (uint8_t)value;
    }
    return count;
}

unsigned long SD_available(void) STC_SD_REENTRANT
{
    if (sd_state.file_open == 0u) {
        sd_set_error(SD_ERROR_NOT_INITIALIZED);
        return 0UL;
    }
    sd_set_error(SD_ERROR_NONE);
    return sd_state.file_size - sd_state.file_position;
}

uint8_t SD_seek(unsigned long position) STC_SD_REENTRANT
{
    if (sd_state.file_open == 0u) {
        sd_set_error(SD_ERROR_NOT_INITIALIZED);
        return 0u;
    }
    if (position > sd_state.file_size) {
        sd_set_error(SD_ERROR_INVALID_ARGUMENT);
        return 0u;
    }
    sd_state.file_position = position;
    sd_state.file_cluster = sd_state.file_first_cluster;
    sd_state.file_cluster_index = 0UL;
    sd_set_error(SD_ERROR_NONE);
    return 1u;
}

unsigned long SD_position(void) STC_SD_REENTRANT
{
    return (sd_state.file_open != 0u) ? sd_state.file_position : 0UL;
}

unsigned long SD_size(void) STC_SD_REENTRANT
{
    return (sd_state.file_open != 0u) ? sd_state.file_size : 0UL;
}

void SD_close(void) STC_SD_REENTRANT
{
    sd_clear_file();
    sd_set_error(SD_ERROR_NONE);
}

STC_SD_CODE const STCSDClass SD = {
    SD_setPins,
    SD_begin,
    SD_beginDefault,
    SD_end,
    SD_cardType,
    SD_fatType,
    SD_error,
    SD_readBlock,
    SD_writeBlock,
    SD_exists,
    SD_open,
    SD_read,
    SD_readBytes,
    SD_peek,
    SD_available,
    SD_seek,
    SD_position,
    SD_size,
    SD_close
};
