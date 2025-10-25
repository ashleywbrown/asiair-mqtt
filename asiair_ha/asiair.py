import asyncio
import struct
import tempfile
import socket, time, sys, json, time
import zipfile
import paho.mqtt.client as mqtt
import logging
from astrolive.image import ImageManipulation
from const import (
#    CAMERA_SENSOR_TYPES,
#    CAMERA_STATES,
    DEVICE_CLASS_SWITCH,
    DEVICE_TYPE_ASIAIR,
    DEVICE_TYPE_CAMERA,
    DEVICE_TYPE_FILTERWHEEL,
    DEVICE_TYPE_FOCUSER,
    DEVICE_TYPE_CAMERA_FILE,
    DEVICE_TYPE_TELESCOPE,
    FUNCTIONS,
#    MANUFACTURER,
    SENSOR_DEVICE_CLASS,
    SENSOR_ICON,
    SENSOR_NAME,
    SENSOR_STATE_CLASS,
    SENSOR_STATE_TOPIC,
    SENSOR_TYPE,
    SENSOR_UNIT,
    SENSOR_VALUE_TEMPLATE,
    STATE_OFF,
    STATE_ON,
    STRETCH_ALGORITHM,
    STRETCH_AP_ID,
    STRETCH_STF_ID,
    TYPE_CLIMATE,
    TYPE_TEXT,
)

import cv2
import numpy as np

_debug = True
_trace = True


logging.basicConfig(#filename="./ASIAIR_"+str(sys.argv[2])+".log",
                    #filemode="a",
                    format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S",
                    level=logging.DEBUG)

# get connection details from params
asisair_host  = str(sys.argv[1])
mqtt_host     = str(sys.argv[2])
mqtt_port     = int(sys.argv[3])
mqtt_username     = str(sys.argv[4])
mqtt_password     = str(sys.argv[5])

# Commands to interrogate the system:
# https://www.cloudynights.com/topic/900861-seestar-s50asiair-jailbreak-ssh/page-4
# These can be sent on connection or every X seconds.
#
# The ideal protocol here is to:
# - get_pi_info => get IDs for device registration
# - send device config messages
# - poll and save certain commands that can be updated by events
# - on the event, send the event topic and the command response update
#
# For certain things, e.g. the filter wheel, it makes sense to cache the
# list response and send a friendlier name for the filterwheel slot.
FILTER_WHEEL_COMMANDS_4700 = ["get_wheel_slot_name", "get_wheel_state", "get_wheel_setting", "get_wheel_position"]
CAMERA_COMMANDS_4700 = [
    "get_camera_state",
    "get_camera_info", # camera capabilities - pixel size, dimensions, cooling etc
    "get_camera_exp_and_bin",
    "get_subframe",
    ("get_control_value", ["Gain"]),
    ("get_control_value", ["CoolerOn"]),
    ("get_control_value", ["CoolPowerPerc"]),
    ("get_control_value", ["TargetTemp"]),
    ("get_control_value", ["AntiDewHeater"]),
    ]
SEQUENCE_COMMANDS_4700 = ["get_sequence", "get_sequence_number", "get_sequence_setting"]
TELESCOPE_COMMANDS_4400 = [
    "scope_get_ra_dec", "scope_get_location", "scope_get_pierside", "scope_get_track_state", "scope_is_moving", "scope_get_horiz_coord", "scope_get_track_mode" # 4400
    ]
TELESCOPE_COMMANDS_4700 = [
    "get_focal_length",
]
FOCUSER_COMMANDS_4700 = ["get_focuser_state", "get_focuser_caps", "get_focuser_value", "get_focuser_position"]
PI_STATUS_COMMANDS_4700 = [
    "pi_station_state",
    "pi_is_verified",
    "get_app_state", # Returns everything needed to configure the UI, including active page
    "pi_get_time",
    "pi_get_info",
    "pi_get_ap",
    "get_power_supply",
    "get_connected",
    ]
DEVICE_LIST_COMMANDS_4700 = ["get_connected_cameras"]

COMMANDS_PORT_4700 = (FILTER_WHEEL_COMMANDS_4700 +
    SEQUENCE_COMMANDS_4700 +
    TELESCOPE_COMMANDS_4700 +
    FOCUSER_COMMANDS_4700 +
    PI_STATUS_COMMANDS_4700 + 
    CAMERA_COMMANDS_4700)

COMMANDS_PORT_4400 = (TELESCOPE_COMMANDS_4400)
COMMANDS_PORT_4800 = ["get_current_img"]

COMMANDS = {}
COMMANDS["4400"] = COMMANDS_PORT_4400
COMMANDS["4700"] = COMMANDS_PORT_4700


# PORT 4400 = Guiding & Telescope
# PORT 4700 = Imaging, FindStar, Annotate, PlateSolve, CameraControlChange, PiStatus
# Topics to include (wildcard for all)
'''
Alert
Annotate
AutoFocus
AutoGoto
AviRecord
Calibrating
CalibrationComplete
CalibrationFailed
CalibrationFailed
CalibrationFailed
CameraControlChange
CoolerPower
Exposure
FocuserMove
GuideStarLostTooMuch
GuideStep
GuidingStopped
INDIServer
LockPositionLost
LockPositionSet
LoopingExposures
LoopingExposuresStopped
LoopingFrames
PiStatus
PlateSolve
RestartGuide
ScopeHome
ScopeTrack
SettleBegin
SettleDone
Settling
StarLost
StarSelected
StartCalibration
StartGuiding
Temperature
Version

Nginx                       // Related to video stacking
RTMP                        // Related to video stacking
'''
topics = ['*']




STRETCH_STF_TARGET_BACKGROUND = 0.25
STRETCH_STF_CLIPPING_POINT = -2.8

CAMERA_SAMPLE_RESOLUTION = 16
IMAGE_PUBLISH_DIMENSIONS = (1920, 1080)

def mqtt_publish(mqtt, type, message):
    logging.debug(asisair_host + " -> " + type + "->" + str(json.dumps(message)))
    y = mqtt.publish(asisair_host + "/" + type, str(json.dumps(message)), retain=True)

cmdid = 0

def make_jsonrpc_command(id, command):
    if isinstance(command, tuple):
        (method, params) = command
        return {"id": id, "method": method, "params": params}
    else:
        return {"id": id, "method": command}
    
async def poll_and_keepalive(writer: asyncio.StreamWriter, cmd_q: asyncio.Queue, commands, interval_seconds: int):
    id = 1
    for command in commands:
        await cmd_q.put(command)
    while True:
        try:
            command = await asyncio.wait_for(cmd_q.get(), interval_seconds)
            writer.write((json.dumps(make_jsonrpc_command(id, command)) + "\r\n").encode())
            id += 1
        except asyncio.TimeoutError:
            for command in commands:
                writer.write((json.dumps(make_jsonrpc_command(id, command)) + "\r\n").encode())
                id += 1
        except Exception as ex:
            logging.error("Failed in command handling: %s", ex)
        #await asyncio.sleep(interval_seconds)


async def read_events(q, cmd_q, port: int):
    print("Connecting to port " + str(port))
    reader, writer = await asyncio.open_connection('asiair', port)
    keepalive = asyncio.create_task(poll_and_keepalive(writer, cmd_q, COMMANDS[str(port)], 8))
    while True:
        message = await reader.readline()
        if not message:
            print("EOF on port " + str(port))
            break
        #print("Putting on Q: " + message.decode())
        await q.put(message)
    await keepalive

async def read_images(q, image_available, port=4800):
    id = 1
    while True:
        try:
            await image_available.wait()
            image_available.clear()
            reader, writer = await asyncio.open_connection('asiair', port)
            command = "get_current_img"
            writer.write((json.dumps({"id": id, "method": command}) + "\r\n").encode())
            await writer.drain()
            id = id + 1
            print(str(port) + " Reading 80")
            header = await reader.readexactly(80) # Header, discard for now
            # Byte 6-9 - size
            # Byte 16,17 - width
            # Byte 18,19 - height
            if len(header) < 80:
                print(str(port) + " Failed to read header")
            else:
                (size, width, height) = struct.unpack("!xxxxxxIxxxxxxHHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", header)
                remaining = size
                print(str(port) + " Header " + str((size, width, height)))
                if width > 0:
                    logging.debug(str(port) + " Zipped Image Size: " + str(size) + " " + str(width) + "x" + str(height))
                    with tempfile.TemporaryFile("w+b") as f:
                        while remaining > 0:
                            chunkSize = min(remaining, 4*1024*1024)
                            chunk = await reader.read(chunkSize)
                            f.write(chunk)
                            remaining = remaining - len(chunk)
                            print(str(port) + " Downloading... " + str(remaining))
                        f.seek(0)
                        z = zipfile.ZipFile(f)
                        with z.open("raw_data", mode="r") as rawData:
                            rawImage = np.ndarray(shape=(height, width), dtype=">u2", buffer=rawData.read())
                            print(rawImage.dtype)
                            cv2.imwrite("raw-asiair.png", rawImage)
                            imageData = await ImageManipulation.normalize_image(rawImage)
                            print(imageData.dtype)
                            cv2.imwrite("norm-asiair.png", (np.multiply(imageData, 2**CAMERA_SAMPLE_RESOLUTION)).astype(np.uint8))
                            imageData = await ImageManipulation.compute_astropy_stretch(imageData)
                            print(imageData.dtype)
                            #imageData *= 255
                            print("Pre resize range: "+ str(np.min(imageData)) + "-" +  str(np.max(imageData)))
                            imageData = await ImageManipulation.resize_image(imageData)#resize_image(np.multiply(imageData, 2**CAMERA_SAMPLE_RESOLUTION)) #.astype(np.uint8)
                            cv2.imwrite("stretch-asiair.png", imageData)
                            (result, imageData) = cv2.imencode(".png", imageData)
                            byteArray = bytearray(imageData)
                            print("MQTT publish result: " + str(result) + "; Len: " + str(len(byteArray)))
                            await q.put(byteArray)
                else:
                    print(str(port) + " Width <= 0")
                    print(str(port) + " => " + str(header))
        except Exception as ex:
            logging.error(ex)

async def create_mqtt_config(mqtt, sys_id, device_type, device_friendly_name, device_functions, cmd_q_4700: asyncio.Queue = None):
    """Creates configuration topics within the homeassistant sensor and camera topics.

    Args:
        sys_id (string): ID of the device.
        device_type (string): Type of the device.
        device_friendly_name (string): Friendly name of the device.
        device_functions (list): List of functions provided by the device.

    Returns:
        True if thread is alive
    """

    logging.debug("Creating MQTT Config for a %s", device_type)
    logging.debug("  Friendly name %s", device_friendly_name)
    logging.debug("  Functions %s", device_functions)

    sys_id_ = sys_id.replace(".", "_")
    device_friendly_name_cap = device_friendly_name
    device_friendly_name_low = device_friendly_name.lower().replace(" ", "_")

    for function in device_functions:
        # Generic for all devices one configuration topic for each functionality
        device_function_cap = function[SENSOR_NAME]
        device_function_low = function[SENSOR_NAME].lower().replace(" ", "_")

 #- name: "ASIAIR CPU Temperature"
    #unique_id: fe9ffd4f-8f5b-4cad-aa6a-ad81067b46ba
    #icon: mdi:memory
    #state_topic: "asiair/PiStatus"
    #value_template: "{{ value_json.temp }}"
    #device_class: temperature
    #unit_of_measurement: "°C"
    #suggested_display_precision: 0

        root_topic = (
            "homeassistant/"
            + function[SENSOR_TYPE]
            + "/asiair/"
            + device_friendly_name_low
            + "_"
            + device_function_low
            + "/"
        )
        config = {
            "name": device_function_cap,
            "state_topic": function[SENSOR_STATE_TOPIC], # set the correct host
            "state_class": function[SENSOR_STATE_CLASS],
            "device_class": function[SENSOR_DEVICE_CLASS],
            "icon": function[SENSOR_ICON],
            #"availability_topic": "astrolive/" + device_type + "/" + sys_id_ + "/lwt",
            #"payload_available": "ON",
            #"payload_not_available": "OFF",
            #"payload_on": STATE_ON,
            #"payload_off": STATE_OFF,
            "unique_id": device_type + "_" + sys_id_ + "_" + device_function_low,
            "value_template": function[SENSOR_VALUE_TEMPLATE],
            #"suggested_display_precision": 2,
            "device": {
                "identifiers": [sys_id],
                "name": "ASIAIR " + device_friendly_name_cap,
                "model": device_friendly_name_cap,
                "manufacturer": "ASIAIR-MQTT Bridge",
            },
        }
        if function[SENSOR_UNIT] != "" and function[SENSOR_UNIT] is not None:
            config["unit_of_measurement"] = function[SENSOR_UNIT]

        if function[SENSOR_TYPE] == TYPE_CLIMATE:
            config["action_topic"] = "asiair/coolpowerperc"
            config["action_template"] = "{% if value_json.value == 0 %}off{% else %}cooling{% endif %}"
            config["mode_state_topic"] = "asiair/cooleron"
            config["mode_state_template"] = "{% if value_json.value == 0 %}off{% else %}cool{% endif %}"
            config["modes"] = ["off", "cool"]
            config["min_temp"] = -40
            config["max_temp"] = 40
            config["current_temperature_topic"] = "asiair/Temperature"
            config["current_temperature_template"] = "{{ value_json.value }}"
            config["temperature_state_topic"] = "asiair/targettemp"
            config["temperature_state_template"] = "{{ value_json.value }}"
            if cmd_q_4700 is not None:
                config["temperature_command_topic"] = "asiair/set_control_value/cmd"
                config["temperature_command_template"] = "[\"TargetTemp\", {{ value }}]"

                config["mode_command_topic"] = "asiair/set_control_value/cmd"
                config["mode_command_template"] = "[\"CoolerOn\", {% if value == 'off' %}0{% else %}1{% endif %}]"

                mqtt.subscribe("asiair/set_control_value/cmd")

        #if function[SENSOR_TYPE] == TYPE_TEXT:
        #    config["command_topic"] = ("astrolive/" + device_type + "/" + sys_id_ + "/cmd",)

        if function[SENSOR_DEVICE_CLASS] == DEVICE_CLASS_SWITCH:
            logging.debug("Device friendly name %s", device_function_low)
            if device_function_low == "dew_heater_on":
                config["command_topic"] = "asiair/set_control_value/cmd"
                config["command_template"] = "[\"AntiDewHeater\", {% if value == 'ON' %}1{% else %}0{% endif %}]"
                mqtt.subscribe("asiair/set_control_value/cmd")
            
        #    config["command_topic"] = (
        #        "astrolive/" + device_type + "/" + sys_id_ + "/set" + "_" + device_function_low
        #    )
        #    # Subscribe to command topic of the switch
        #    await self._publisher.subsribe_mqtt(
        #        "astrolive/" + device_type + "/" + sys_id_ + "/set" + "_" + device_function_low
        #    )

        mqtt.publish(root_topic + "config", json.dumps(config), qos=0, retain=True)

    logging.debug("Published MQTT Config for a %s", device_type)

    if device_type in (DEVICE_TYPE_CAMERA, DEVICE_TYPE_CAMERA_FILE):
        # If the device is a camera or camera_file we create a camera entity configuration
        root_topic = "homeassistant/camera/asiair/" + device_friendly_name_low + "/"
        config = {
            "name": device_friendly_name_cap,
            "topic": "asiair/image/latestImage",
            #"availability_topic": "astrolive/" + device_type + "/" + sys_id_ + "/lwt",
            #"payload_available": "ON",
            #"payload_not_available": "OFF",
            "unique_id": device_type + "_" + device_friendly_name_low + "_" + sys_id_,
            "device": {
                "identifiers": [sys_id],
                "name": "ASIAIR " + device_friendly_name_cap,
                "model": device_friendly_name_cap,
                "manufacturer": "ASIAIR-MQTT Bridge",
            },
        }
        mqtt.publish(root_topic + "config", json.dumps(config), qos=0, retain=True)
        logging.debug("Published MQTT Camera Config for a %s", device_type)

    return None

async def mqtt_publisher(q, image_available, cmd_q_4700):
    # Cached values
    wheel_names = None
    pi_info = None

    def on_message(client, userdata, message: mqtt.MQTTMessage):
        cmd_q_4700: asyncio.Queue = userdata.get("cmd_q_4700", None)
        if (cmd_q_4700):
            logging.debug(">>>>>>>>>>> %s: %s", message.topic, message.payload)
            if message.topic == "asiair/set_control_value/cmd":
                cmd_q_4700.put_nowait(("set_control_value", json.loads(message.payload)))
        #logging.info(message)

    userdata = {
        "cmd_q_4700": cmd_q_4700,
    }

    # setup
    print("connecting MQTT: " + str(mqtt_host) + ':' + str(mqtt_port))
    clientMQTT = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, userdata=userdata)
    clientMQTT.username_pw_set(username=mqtt_username, password=mqtt_password)
    clientMQTT.connect(mqtt_host, mqtt_port, 60)
    clientMQTT.on_message = on_message
    clientMQTT.loop_start()

    # Set up MQTT Home Assistant config.
    try:
        asyncio.create_task(create_mqtt_config(clientMQTT, "asiair.asiair", DEVICE_TYPE_ASIAIR, "ASIAIR", FUNCTIONS[DEVICE_TYPE_ASIAIR]))
        asyncio.create_task(create_mqtt_config(clientMQTT, "asiair.camera", DEVICE_TYPE_CAMERA, "Camera", FUNCTIONS[DEVICE_TYPE_CAMERA], cmd_q_4700))
        asyncio.create_task(create_mqtt_config(clientMQTT, "asiair.filterwheel", DEVICE_TYPE_FILTERWHEEL, "FilterWheel", FUNCTIONS[DEVICE_TYPE_FILTERWHEEL]))
        asyncio.create_task(create_mqtt_config(clientMQTT, "asiair.focuser", DEVICE_TYPE_FOCUSER, "Focuser", FUNCTIONS[DEVICE_TYPE_FOCUSER]))
        asyncio.create_task(create_mqtt_config(clientMQTT, "asiair.telescope", DEVICE_TYPE_TELESCOPE, "Telescope", FUNCTIONS[DEVICE_TYPE_TELESCOPE]))
    except Exception as e:
        logging.debug(e)
        raise
    while True:
        message = await q.get()
        if isinstance(message, bytearray):
            mqttMsg = clientMQTT.publish("asiair/image/latestImage", message, qos=1, retain=True)
            print("Waiting to publish image...")
            mqttMsg.wait_for_publish()
            print("... done")
        else:
            x = message
            # replace bad characters - from asiair_mqtt - need to test if needed
            message = message.replace(b"<\x90\xadE\xb6>", b"???")
            message = message.replace(b"<\xe8>", b"???")
            message = message.decode('iso-8859-1')
            try:
                message = json.loads(message)
                message['utime'] = int(time.time())
                message['instance'] = asisair_host
                try:
                    if message["Event"] == "Exposure" and message["state"] == "complete":
                        image_available.set()
                except KeyError:
                    pass
                if "method" in message and message["code"] == 0:
                    if message["method"] == "get_control_value":
                        message["method"] = str(message["result"]["name"]).lower()
                    if message["method"] == "pi_get_info":
                        pi_info = message["result"] # Send HA device discovery message.
                    elif message["method"] == "get_wheel_slot_name":
                        wheel_names = message["result"] # Send HA device discovery message.
                    elif message["method"] == "get_wheel_position":
                        if wheel_names != None:
                            mqtt_publish(clientMQTT, "WheelName", wheel_names[message["result"]])
                elif "Event" in message:
                    if message["Event"] == "WheelMove" and message["state"] == "complete":
                        mqtt_publish(clientMQTT, "WheelName", wheel_names[message["position"]])
                        mqtt_publish(clientMQTT, "get_wheel_position", message["position"])
                    elif message["Event"] == "CameraControlChange":
                        for command in CAMERA_COMMANDS_4700:
                            await cmd_q_4700.put(command)
                else:
                    logging.error("Unknown response: %s", str(x))

                if "Event" in message and (message["Event"] in topics or "*" in topics):
                    mqtt_publish(clientMQTT, message["Event"], message)
                elif "method" in message and message["code"] == 0:
                    mqtt_publish(clientMQTT, message["method"], message["result"])
                else:
                    #if _debug: print(str(asisair_host) + ":" + str(asisair_port) + "(ignored : " + str(json.dumps(message)))
                    pass
            except Exception as ex:
                logging.debug("Failed: %s", ex)
        q.task_done()

async def main():
    #async with asyncio.TaskGroup() as tg:
    q = asyncio.Queue()
    cmd_q_4400 = asyncio.Queue()
    cmd_q_4700 = asyncio.Queue()
    image_available = asyncio.Event()
    port4400 = asyncio.create_task(read_events(q, cmd_q_4400, 4400))
    port4700 = asyncio.create_task(read_events(q, cmd_q_4700, 4700))
    images = asyncio.create_task(read_images(q, image_available))
    printer = asyncio.create_task(mqtt_publisher(q, image_available, cmd_q_4700))

    await port4400
    await port4700
    await images
    await printer

asyncio.run(main())