"""Constant Definitions take from AstroLive, (C) 2022 Markus Winker (https://github.com/mawinkler/astrolive/blob/main/LICENSE)."""

COLOR_BLACK = "1;30"
COLOR_RED = "1;31"
COLOR_GREEN = "1;32"
COLOR_BROWN = "1;33"
COLOR_BLUE = "1;34"
COLOR_PURPLE = "1;35"
COLOR_CYAN = "1;36"
COLOR_STD = "0"


# #########################################################################
# Image Manipulation
# #########################################################################
CAMERA_SAMPLE_RESOLUTION = 16
IMAGE_PUBLISH_DIMENSIONS = (1920, 1080)

# Select Stretching Algorithm
# Valid Options: STF, AP
STRETCH_ALGORITHM = "STF"

# PixInsight STF Stretch
STRETCH_STF_ID = "STF"
STRETCH_STF_TARGET_BACKGROUND = 0.25
STRETCH_STF_CLIPPING_POINT = -2.8

# AstroPy Stretch
STRETCH_AP_ID = "AP"
STRETCH_AP_STRETCH_FUNCTION = "asinh"
STRETCH_AP_MINMAX_PERCENT = [15, 95]  # [0.5, 95]
STRETCH_AP_MINMAX_VALUE = None

# #########################################################################
# Devices
# #########################################################################
DEVICE_TYPE_ASIAIR = "asiair"
DEVICE_TYPE_TELESCOPE = "telescope"
DEVICE_TYPE_CAMERA = "camera"
DEVICE_TYPE_CAMERA_FILE = "camerafile"
DEVICE_TYPE_SWITCH = "switch"
DEVICE_TYPE_FOCUSER = "focuser"
DEVICE_TYPE_FILTERWHEEL = "filterwheel"
DEVICE_TYPE_DOME = "dome"
DEVICE_TYPE_ROTATOR = "rotator"
DEVICE_TYPE_SAFETYMONITOR = "safetymonitor"

DEVICE_TYPE_ASIAIR_ICON = "mdi:raspberry-pi"
DEVICE_TYPE_TELESCOPE_ICON = "mdi:telescope"
DEVICE_TYPE_CAMERA_ICON = "mdi:camera"
DEVICE_TYPE_CAMERA_FILE_ICON = "mdi:camera"
DEVICE_TYPE_FOCUSER_ICON = "mdi:focus-auto"
DEVICE_TYPE_SWITCH_ICON = "mdi:hubspot"
DEVICE_TYPE_FILTERWHEEL_ICON = "mdi:image-filter-black-white"
DEVICE_TYPE_DOME_ICON = "mdi:greenhouse"
DEVICE_TYPE_ROTATOR_ICON = "mdi:rotate-360"
DEVICE_TYPE_SAFETYMONITOR_ICON = "mdi:seatbelt"

# #########################################################################
# Entities
# #########################################################################
SENSOR_TYPE = 0
SENSOR_NAME = 1
SENSOR_UNIT = 2
SENSOR_ICON = 3
SENSOR_DEVICE_CLASS = 4
SENSOR_STATE_CLASS = 5
SENSOR_STATE_TOPIC = 6
SENSOR_VALUE_TEMPLATE = 7
SENSOR_EXTRA_FIELDS = 8

STATE_ON = "on"
STATE_OFF = "off"

TYPE_BINARY_SENSOR = "binary_sensor"
TYPE_SENSOR = "sensor"
TYPE_SWITCH = "switch"
TYPE_TEXT = "text"
TYPE_CAMERA = "camera"
TYPE_CLIMATE = "climate"
TYPE_DEVICE_TRACKER = "device_tracker"

UNIT_OF_MEASUREMENT_NONE = None
UNIT_OF_MEASUREMENT_ARCSEC_PER_SEC = '"/s'
UNIT_OF_MEASUREMENT_DEGREE = "°"
UNIT_OF_MEASUREMENT_DEGREE_PER_SEC = "°/s"
UNIT_OF_MEASUREMENT_METER = "m"
UNIT_OF_MEASUREMENT_MICROMETER = "µm"
UNIT_OF_MEASUREMENT_MILLIMETER = "mm"
UNIT_OF_MEASUREMENT_PERCENTAGE = "%"
UNIT_OF_MEASUREMENT_SECONDS = "s"
UNIT_OF_MEASUREMENT_TEMP_CELSIUS = "°C"
UNIT_OF_MEASUREMENT_VOLTAGE = "°C"


DEVICE_CLASS_NONE = None
DEVICE_CLASS_DISTANCE = "distance"
DEVICE_CLASS_DURATION = "duration"
DEVICE_CLASS_POWER = "power"
DEVICE_CLASS_SWITCH = "switch"
DEVICE_CLASS_TEMPERATURE = "temperature"
DEVICE_CLASS_TIMESTAMP = "timestamp"

STATE_CLASS_NONE = None
STATE_CLASS_MEASUREMENT = "measurement"

FUNCTIONS = {
    DEVICE_TYPE_TELESCOPE: (
#        [
#            TYPE_BINARY_SENSOR,
#            "At home",
#            UNIT_OF_MEASUREMENT_NONE,
#            DEVICE_TYPE_TELESCOPE_ICON,
#            DEVICE_CLASS_NONE,
#            STATE_CLASS_NONE,
#        ],
#        [
#            TYPE_BINARY_SENSOR,
#            "At park",
#            UNIT_OF_MEASUREMENT_NONE,
#            DEVICE_TYPE_TELESCOPE_ICON,
#            DEVICE_CLASS_NONE,
#            STATE_CLASS_NONE,
#        ],
#        [
#            TYPE_SENSOR,
#            "Site elevation",
#            UNIT_OF_MEASUREMENT_METER,
#            DEVICE_TYPE_TELESCOPE_ICON,
#            DEVICE_CLASS_DISTANCE,
#            STATE_CLASS_MEASUREMENT,
#        ],
        [
            TYPE_DEVICE_TRACKER,
            "Location",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/dummytopic",
            "",
            {
                "json_attributes_topic": "asiair/scope_get_location",
                "json_attributes_template": "{ \"latitude\": {{ value_json[0] }}, \"longitude\": {{ value_json[1] }} }",
            }
        ],
        [
            TYPE_SENSOR,
            "Site Latitude",
            UNIT_OF_MEASUREMENT_DEGREE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/scope_get_location",
            "{{ value_json[0] }}"
        ],
        [
            TYPE_SENSOR,
            "Site Longitude",
            UNIT_OF_MEASUREMENT_DEGREE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/scope_get_location",
            "{{ value_json[1] }}"
        ],
        [
            TYPE_BINARY_SENSOR,
            "Slewing",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/scope_is_moving",
            "{{ value_json != 'none' }}",
            {
                "payload_on": "none",
                "payload_off": "none",
            }
        ],
    ),
}


