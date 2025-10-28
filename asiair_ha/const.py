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
    DEVICE_TYPE_ASIAIR: (
        [
            TYPE_SENSOR,
            "CPU Temperature",
            UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
            "mdi:thermometer",
            DEVICE_CLASS_TEMPERATURE,
            STATE_CLASS_MEASUREMENT,
            "asiair/PiStatus",
            "{{ value_json.temp }}"
        ],
        # Wifi
        [
            TYPE_SENSOR,
            "Wifi Station Signal Strength",
            "dB",
            "mdi:wifi",
            "signal_strength",
            STATE_CLASS_MEASUREMENT,
            "asiair/Station",
            "{{ value_json.sig_lev }}"
        ],
        [
            TYPE_SENSOR,
            "Wifi Station Frequency",
            "MHz",
            "mdi:wifi",
            "frequency",
            STATE_CLASS_NONE,
            "asiair/pi_station_state",
            "{{ value_json.freq }}"
        ],
        [
            TYPE_SENSOR,
            "Wifi Station SSID",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:wifi",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_station_state",
            "{{ value_json.ssid }}"
        ],
        [
            TYPE_SENSOR,
            "Wifi Station IP",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:wifi",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_station_state",
            "{{ value_json.ip }}"
        ],
        [
            TYPE_SENSOR,
            "Wifi Station Gateway",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:wifi",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_station_state",
            "{{ value_json.gateway }}"
        ],
        [
            TYPE_SENSOR,
            "Wifi Station Netmask",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:wifi",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_station_state",
            "{{ value_json.netmask }}"
        ],
        # pi_get_info - ASIAIR model
        [
            TYPE_SENSOR,
            "Model",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:raspberry-pi",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_get_info",
            "{{ value_json.model }}"
        ],
        [
            TYPE_SENSOR,
            "GUID",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:raspberry-pi",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_get_info",
            "{{ value_json.guid }}"
        ],
        [
            TYPE_SENSOR,
            "OS",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:raspberry-pi",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_get_info",
            "{{ value_json.uname }}"
        ],
        [
            TYPE_SENSOR,
            "CPU ID",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:raspberry-pi",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_get_info",
            "{{ value_json.cpuId }}"
        ],
        [
            TYPE_SENSOR,
            "Has BLE",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:bluetooth",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/pi_get_info",
            "{{ value_json.is_has_ble }}"
        ],
        # App status
        [
            TYPE_SENSOR,
            "Page",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:document",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/get_app_state",
            "{{ value_json.page }}"
        ],
        # Current sequence
        [
            TYPE_SENSOR,
            "Target",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:creation",
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/get_sequence_setting",
            "{{ value_json.group_name }}"
        ],
        # Power
        [
            TYPE_SENSOR,
            "Port 1 Voltage",
            "V",
            "mdi:creation",
            "voltage",
            STATE_CLASS_MEASUREMENT,
            "asiair/get_power_supply",
            "{{ value_json[0][0] | float }}",
            {
                "suggested_display_precision": 2
            }
        ],
        [
            TYPE_SENSOR,
            "Port 2 Voltage",
            "V",
            "mdi:creation",
            "voltage",
            STATE_CLASS_MEASUREMENT,
            "asiair/get_power_supply",
            "{{ value_json[1][0] | float }}",
            {
                "suggested_display_precision": 2
            }
        ],
        [
            TYPE_SENSOR,
            "Port 3 Voltage",
            "V",
            "mdi:creation",
            "voltage",
            STATE_CLASS_MEASUREMENT,
            "asiair/get_power_supply",
            "{{ value_json[2][0] | float }}",
            {
                "suggested_display_precision": 2
            }
        ],
        [
            TYPE_SENSOR,
            "Port 4 Voltage",
            "V",
            "mdi:creation",
            "voltage",
            STATE_CLASS_MEASUREMENT,
            "asiair/get_power_supply",
            "{{ value_json[3][0] | float }}",
            {
                "suggested_display_precision": 2
            }
        ],
        [
            TYPE_SENSOR,
            "Input Voltage",
            "V",
            "mdi:creation",
            "voltage",
            STATE_CLASS_MEASUREMENT,
            "asiair/get_power_supply",
            "{{ value_json[4][0] | float }}",
            {
                "suggested_display_precision": 2
            }
        ],
        [
            TYPE_SENSOR,
            "Input Current",
            "A",
            "mdi:creation",
            "current",
            STATE_CLASS_MEASUREMENT,
            "asiair/get_power_supply",
            "{{ value_json[4][1] | float }}",
            {
                "suggested_display_precision": 2
            }
        ],
        [
            TYPE_SENSOR,
            "Input Power",
            "W",
            "mdi:flash",
            DEVICE_CLASS_POWER,
            STATE_CLASS_MEASUREMENT,
            "asiair/get_power_supply",
            "{{ value_json[4][0] * value_json[4][1] | float }}",
            {
                "suggested_display_precision": 2,
                "entity_category": "diagnostic"
            }
        ],
    ),
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
        [
            TYPE_SENSOR,
            "Altitude",
            UNIT_OF_MEASUREMENT_DEGREE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/scope_get_horiz_coord",
            "{{ value_json[0] }}"
        ],
        [
            TYPE_SENSOR,
            "Azimuth",
            UNIT_OF_MEASUREMENT_DEGREE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/scope_get_horiz_coord",
            "{{ value_json[1] }}"
        ],
        [
            TYPE_SENSOR,
            "Declination",
            UNIT_OF_MEASUREMENT_DEGREE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/scope_get_ra_dec",
            "{{ value_json[1] }}"
        ],
        [
            TYPE_SENSOR,
            "Right ascension",
            UNIT_OF_MEASUREMENT_DEGREE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/scope_get_ra_dec",
            "{{ value_json[0] }}"
        ],
        [
            TYPE_SENSOR,
            "Side of pier",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/scope_get_pierside",
            "{{ value_json }}"
        ],
        [
            TYPE_SENSOR,
            "Tracking Mode",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/scope_get_track_mode",
            "{{ value_json['list'][value_json['index']] }}"
        ],
        [
            TYPE_BINARY_SENSOR,
            "Tracking",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_TELESCOPE_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/scope_get_track_state",
            "{% if value_json == False %}OFF{% else %}ON{% endif %}",
            {
                "json_attributes_topic": "asiair/scope_get_track_mode",
                "json_attributes_template": "{ \"tracking_mode\": \"{{ value_json['list'][value_json['index']] }}\" }",
            }
        ],
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
    DEVICE_TYPE_CAMERA: (
        [
            TYPE_SENSOR,
            "Name",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_CAMERA_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/get_camera_state",
            "{{ value_json.name }}"
        ],
        [
            TYPE_SENSOR,
            "Camera state",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_CAMERA_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/get_camera_state",
            "{{ value_json.state }}"
        ],
        [
            TYPE_SENSOR,
            "CCD temperature",
            UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
            DEVICE_TYPE_CAMERA_ICON,
            DEVICE_CLASS_TEMPERATURE,
            STATE_CLASS_MEASUREMENT,
            "asiair/Temperature",
            "{{ value_json.value }}"
        ],
        [
            TYPE_CLIMATE,
            "Cooling",
            UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
            DEVICE_TYPE_CAMERA_ICON,
            DEVICE_CLASS_TEMPERATURE,
            STATE_CLASS_MEASUREMENT,
            "asiair/Temperature",
            "{{ value_json.value }}"
        ],
        [
            TYPE_BINARY_SENSOR,
            "Cooler on",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_CAMERA_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_NONE,
            "asiair/cooleron",
            "{% if value_json.value == 0 %}OFF{% else %}ON{% endif %}"
        ],
        [
            TYPE_SENSOR,
            "Cooler Power",
            UNIT_OF_MEASUREMENT_PERCENTAGE,
            DEVICE_TYPE_CAMERA_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/coolpowerperc",
            "{{ value_json.value }}"
        ],
        [
            TYPE_SENSOR,
            "Gain",
            UNIT_OF_MEASUREMENT_NONE,
            DEVICE_TYPE_CAMERA_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/gain",
            "{{ value_json.value }}"
        ],
        [
            TYPE_SENSOR,
            "Exposure",
            UNIT_OF_MEASUREMENT_SECONDS,
            DEVICE_TYPE_CAMERA_ICON,
            DEVICE_CLASS_NONE,
            STATE_CLASS_MEASUREMENT,
            "asiair/exposure",
            "{{ value_json.value / (1000*1000) }}"
        ],
        [
            TYPE_SWITCH,
            "Dew Heater on",
            UNIT_OF_MEASUREMENT_NONE,
            "mdi:heating-coil",
            DEVICE_CLASS_SWITCH,
            STATE_CLASS_NONE,
            "asiair/antidewheater",
            "{% if value_json.value == 0 %}OFF{% else %}ON{% endif %}"
        ],
        #[
        #    TYPE_SENSOR,
        #    "Image array",
        #    UNIT_OF_MEASUREMENT_NONE,
        #    DEVICE_TYPE_CAMERA_ICON,
        #    DEVICE_CLASS_NONE,
        #    STATE_CLASS_MEASUREMENT,
        #],
        #[
        #    TYPE_BINARY_SENSOR,
        #    "Image ready",
        #    UNIT_OF_MEASUREMENT_NONE,
        #    DEVICE_TYPE_CAMERA_ICON,
        #    DEVICE_CLASS_NONE,
        #    STATE_CLASS_NONE,
        #],
        #[
        #    TYPE_SENSOR,
        #    "Last exposure duration",
        #    UNIT_OF_MEASUREMENT_SECONDS,
        #    DEVICE_TYPE_CAMERA_ICON,
        #    DEVICE_CLASS_DURATION,
        #    STATE_CLASS_MEASUREMENT,
        #],
        #[
        #    TYPE_SENSOR,
        #    "Last exposure start time",
        #    UNIT_OF_MEASUREMENT_NONE,
        #    DEVICE_TYPE_CAMERA_ICON,
        #    DEVICE_CLASS_TIMESTAMP,
        #    STATE_CLASS_MEASUREMENT,
        #],
        #[
        #    TYPE_SENSOR,
        #    "Percent completed",
        #    UNIT_OF_MEASUREMENT_PERCENTAGE,
        #    DEVICE_TYPE_CAMERA_ICON,
        #    DEVICE_CLASS_NONE,
        #    STATE_CLASS_MEASUREMENT,
        #],
        #[
        #    TYPE_SENSOR,
        #    "Readout mode",
        #    UNIT_OF_MEASUREMENT_NONE,
        #    DEVICE_TYPE_CAMERA_ICON,
        #    DEVICE_CLASS_NONE,
        #    STATE_CLASS_MEASUREMENT,
        #],
        #[
        #    TYPE_SENSOR,
        #    "Readout modes",
        #    UNIT_OF_MEASUREMENT_NONE,
        #    DEVICE_TYPE_CAMERA_ICON,
        #    DEVICE_CLASS_NONE,
        #    STATE_CLASS_MEASUREMENT,
        #],
        #[
        #    TYPE_SENSOR,
        #    "Sensor type",
        #    UNIT_OF_MEASUREMENT_NONE,
        #    DEVICE_TYPE_CAMERA_ICON,
        #    DEVICE_CLASS_NONE,
        #    STATE_CLASS_MEASUREMENT,
        #],
    ),
#    DEVICE_TYPE_ROTATOR: (
#        [
#            TYPE_SENSOR,
#            "Mechanical position",
#            UNIT_OF_MEASUREMENT_NONE,
#            DEVICE_TYPE_ROTATOR_ICON,
#            DEVICE_CLASS_NONE,
#            STATE_CLASS_MEASUREMENT,
#        ],
#        [
#            TYPE_SENSOR,
#            "Position",
#            UNIT_OF_MEASUREMENT_NONE,
#            DEVICE_TYPE_ROTATOR_ICON,
#            DEVICE_CLASS_NONE,
#            STATE_CLASS_MEASUREMENT,
#        ],
#    ),
}


