"""Constants for Hive."""

from homeassistant.const import Platform

CONF_CODE = "2fa"
CONFIG_ENTRY_VERSION = 1
DEFAULT_NAME = "Hive"
DOMAIN = "hive"
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.WATER_HEATER,
]
WATER_HEATER_MODES = ["on", "off"]
