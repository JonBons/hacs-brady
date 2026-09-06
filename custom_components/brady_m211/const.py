"""Constants for the Brady M211 integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "brady_m211"

MANUFACTURER: Final = "Brady"
MODEL: Final = "M211"

# Bring-up: log connect / GATT / PICL / print milestones at info so they show
# up without changing logger config. Set False once the printer is reliable.
VERBOSE_LOGGING: Final = True

CONF_OWNERSHIP_ID: Final = "ownership_id"
CONF_KEEP_CONNECTED: Final = "keep_connected"
CONF_RELEASE_ON_DISCONNECT: Final = "release_on_disconnect"

DEFAULT_KEEP_CONNECTED: Final = False
DEFAULT_RELEASE_ON_DISCONNECT: Final = True
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=5)
KEEP_CONNECTED_SCAN_INTERVAL: Final = timedelta(seconds=30)

LOCAL_NAME_PREFIX: Final = "M211"

# Apollo GATT
APOLLO_SERVICE_UUID: Final = "0000fd1c-0000-1000-8000-00805f9b34fb"
CHAR_SESSION_ID: Final = "fc0018d8-cf12-46be-87b1-cce29b1e6c34"
CHAR_PRINT_JOB: Final = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"
CHAR_PICL_REQUEST: Final = "a61ae408-3273-420c-a9db-0669f4f23b69"
CHAR_PICL_RESPONSE: Final = "786af345-1b68-c594-c643-e2867da117e3"

COMPACT_PICL_GUID: Final = bytes(
    [150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211]
)

CHUNK_FLAG_MORE: Final = 1
CHUNK_FLAG_FLUSH: Final = 2
CHUNK_FLAG_LAST: Final = 3
FLUSH_EVERY_BYTES: Final = 4096
ATT_HEADER_BYTES: Final = 3
CHUNK_HEADER_BYTES: Final = 3

DPI: Final = 203
MIN_LABEL_LENGTH_IN: Final = 1.0
MAX_LABEL_LENGTH_IN: Final = 36.0
DEFAULT_PRINTABLE_WIDTH_IN: Final = 0.63
HEADER_IN: Final = 0.435
TRAILER_IN: Final = 0.435

# Compact PICL property IDs
PROP_BATTERY: Final = "0001"
PROP_CUT: Final = "0004"
PROP_CUT_ERROR: Final = "0005"
PROP_FATAL_ERROR: Final = "0006"
PROP_FEED: Final = "0007"
PROP_PRINT_JOB_ERROR: Final = "0009"
PROP_MEDIA_INVALID: Final = "000A"
PROP_PRINTABLE_WIDTH: Final = "000C"
PROP_LEFT_OFFSET: Final = "000D"
PROP_PRINTABLE_HEIGHT: Final = "000E"
PROP_VERTICAL_OFFSET: Final = "000F"
PROP_BLACK_STRIPED: Final = "0012"
PROP_DIE_CUT: Final = "0013"
PROP_PERMASLEEVE: Final = "0014"
PROP_SELF_LAM: Final = "0015"
PROP_MEDIA_REMAINING: Final = "0016"
PROP_MEDIA_LOW: Final = "001C"
PROP_JOB_COMPLETE: Final = "001F"
PROP_FIRMWARE: Final = "0020"
PROP_LOW_POWER: Final = "0021"
PROP_AC_CONNECTED: Final = "0024"
PROP_MEDIA_OUT: Final = "0025"
PROP_SHUTDOWN_TIMEOUT: Final = "0026"
PROP_DISMISSIBLE_ERROR: Final = "0027"
PROP_JOB_STATUS: Final = "0029"
PROP_UNIQUE_ID: Final = "002A"

PICL_PROP_NAMES: Final = {
    PROP_BATTERY: "battery",
    PROP_CUT: "cut",
    PROP_CUT_ERROR: "cut_error",
    PROP_FATAL_ERROR: "fatal_error",
    PROP_FEED: "feed",
    PROP_PRINT_JOB_ERROR: "print_job_error",
    PROP_MEDIA_INVALID: "media_invalid",
    PROP_PRINTABLE_WIDTH: "printable_width",
    PROP_LEFT_OFFSET: "left_offset",
    PROP_PRINTABLE_HEIGHT: "printable_height",
    PROP_VERTICAL_OFFSET: "vertical_offset",
    PROP_BLACK_STRIPED: "black_striped",
    PROP_DIE_CUT: "die_cut",
    PROP_PERMASLEEVE: "permasleeve",
    PROP_SELF_LAM: "self_lam",
    PROP_MEDIA_REMAINING: "media_remaining",
    PROP_MEDIA_LOW: "media_low",
    PROP_JOB_COMPLETE: "job_complete",
    PROP_FIRMWARE: "firmware",
    PROP_LOW_POWER: "low_power",
    PROP_AC_CONNECTED: "ac_connected",
    PROP_MEDIA_OUT: "media_out",
    PROP_SHUTDOWN_TIMEOUT: "shutdown_timeout",
    PROP_DISMISSIBLE_ERROR: "dismissible_error",
    PROP_JOB_STATUS: "job_status",
    PROP_UNIQUE_ID: "unique_id",
}

M211_SUBSCRIBE_IDS: Final = (
    PROP_FATAL_ERROR,
    PROP_CUT_ERROR,
    PROP_MEDIA_INVALID,
    PROP_MEDIA_LOW,
    PROP_LOW_POWER,
    PROP_DISMISSIBLE_ERROR,
    PROP_MEDIA_OUT,
    PROP_PRINT_JOB_ERROR,
    PROP_JOB_STATUS,
    PROP_BATTERY,
    PROP_AC_CONNECTED,
    PROP_SHUTDOWN_TIMEOUT,
    PROP_PRINTABLE_WIDTH,
    PROP_LEFT_OFFSET,
    PROP_PRINTABLE_HEIGHT,
    PROP_VERTICAL_OFFSET,
    PROP_BLACK_STRIPED,
    PROP_DIE_CUT,
    PROP_PERMASLEEVE,
    PROP_SELF_LAM,
    PROP_UNIQUE_ID,
    PROP_MEDIA_REMAINING,
    PROP_JOB_COMPLETE,
    PROP_FIRMWARE,
)
