import asyncio
import struct
import sys
import tempfile
import json, time
import zipfile
import paho.mqtt.client as mqtt
import logging
from components import climate, sensor, switch
from astrolive.image import ImageManipulation
from const import (
    CAMERA_SAMPLE_RESOLUTION,
    DEVICE_CLASS_NONE,
    DEVICE_CLASS_SWITCH,
    DEVICE_TYPE_CAMERA_ICON,
    DEVICE_TYPE_FILTERWHEEL_ICON,
    DEVICE_TYPE_FOCUSER_ICON,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_NONE,
    TYPE_SENSOR,
    TYPE_SWITCH,
    UNIT_OF_MEASUREMENT_NONE,
    UNIT_OF_MEASUREMENT_PERCENTAGE,
    UNIT_OF_MEASUREMENT_SECONDS,
    UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
)
import jsonrpc


import cv2
import numpy as np
from observatory_software import Device, ObservatorySoftware

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
 #   ("get_control_value", ["Gain"]),
    ("get_control_value", ["CoolerOn"]),
 #   ("get_control_value", ["CoolPowerPerc"]),
    ("get_control_value", ["TargetTemp"]),
 #   ("get_control_value", ["AntiDewHeater"]),
#    ("get_control_value", ["Exposure"]),
    ]
SEQUENCE_COMMANDS_4700 = ["get_sequence", "get_sequence_number", "get_sequence_setting"]
TELESCOPE_COMMANDS_4400 = [
    "scope_get_ra_dec", "scope_get_location", "scope_get_pierside", "scope_get_track_state", "scope_is_moving", "scope_get_horiz_coord", "scope_get_track_mode" # 4400
    ]
TELESCOPE_COMMANDS_4700 = [
    "get_focal_length",
]
FOCUSER_COMMANDS_4700 = [
    "get_focuser_state",
    "get_focuser_caps",
    "get_focuser_value",
    ]

PI_STATUS_COMMANDS_4700 = [
    "pi_station_state",
    #"pi_is_verified",
    "get_app_state", # Returns everything needed to configure the UI, including active page
    #"pi_get_time",
    "pi_get_info",
    "pi_get_ap",
    "get_power_supply",
    ]
DEVICE_LIST_COMMANDS_4700 = ["get_connected_cameras"]

COMMANDS_PORT_4700 = (
    #FILTER_WHEEL_COMMANDS_4700 +
    SEQUENCE_COMMANDS_4700 +
    TELESCOPE_COMMANDS_4700 +
    #FOCUSER_COMMANDS_4700 +
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

def command_args(command):
    if isinstance(command, tuple):
        (method, args) = command
    else:
        (method, args) = (command, [])
    return (method, args)

class FromJson:
    def __init__(self, json_dict):
        self.__dict__ = json_dict

class ZwoAsiair(ObservatorySoftware):

    def __init__(self, name, address):
        self._address = address
        self.rpc_command_id = 1

        # Cache some information - factor this out to device later.
        self.wheel_names = None
        self.pi_info = None
        self.devices = {
            'asiair': ZwoAsiairDevice(self, 'asiair'),
            'focuser': Focuser(self, 'focuser'),
            'efw': FilterWheel(self, 'efw'),
            'camera': Camera(self, 'camera'),
        }
        super().__init__(name)

    @staticmethod
    def create(name: str, address: str, **kwargs):
        return ZwoAsiair(name, address=address)
     
    async def connect(self):
        self.update_q = asyncio.Queue()
        self.cmd_q_4400 = asyncio.Queue()
        self.cmd_q_4700 = asyncio.Queue()
        self.event_q = asyncio.Queue()
        self.image_available = asyncio.Event()
        self.port4400 = asyncio.create_task(self.read_events(self.cmd_q_4400, 4400))
        self.port4700 = asyncio.create_task(self.read_events(self.cmd_q_4700, 4700))
        self.images = asyncio.create_task(self.read_images())

    async def jsonrpc_call_async(self, port: int, command: str, *args):
        if port == 4400:
            cmd_q = self.cmd_q_4400
        elif port == 4700:
            cmd_q = self.cmd_q_4700
        else:
            return NotImplementedError
        await cmd_q.put((command, args))

    async def jsonrpc_call(self, port: int, command: str, *args):
        if port == 4400:
            cmd_q = self.cmd_q_4400
        elif port == 4700:
            cmd_q = self.cmd_q_4700
        else:
            return NotImplementedError
        event = asyncio.Event()
        await cmd_q.put((command, args, event))
        # would be better as a single-item queue
        await event.wait()
        if event.result is not None:
            return event.result
        else:
            logging.error('Error during synchronous call: %s', event.error)
            sys.exit(0)

    async def discover(self):
        self.pi_info = FromJson(await self.jsonrpc_call(4700, 'pi_get_info'))
        logging.debug(self.pi_info)
        return self.devices
  
    async def poll(self):
        try:
            logging.debug(">>>>>>>>>>>>>>>>>>> Getting filter wheel")
            (self.wheel_names, position) = await asyncio.gather(
                self.jsonrpc_call(4700, 'get_wheel_slot_name'),
                self.jsonrpc_call(4700, 'get_wheel_position')
            )
            if len(self.wheel_names) > 0:
                await self.update_q.put({'method': 'WheelName', 'code': 0, 'result': self.wheel_names[position]}),

            # Process events from the event queue.
            async def event_loop():
                while True:
                    try:
                        (event, payload) = await self.event_q.get()
                        await self._handle_event(event, payload)
                    except Exception as ex:
                        logging.error(ex)
                        sys.exit(0)

            async def poll_loop():
                while True:
                    # Publish all components.
                    try:
                        for device in self.devices.values():
                            for component in device.components():
                                logging.debug(component)
                                await component.publish(device)

                        for port in [4400, 4700]:
                            for command in COMMANDS[str(port)]:
                                (method, args) = command_args(command)
                                await self.jsonrpc_call_async(port, method, *args)
                        await asyncio.sleep(45)
                    except Exception as ex:
                        logging.error(ex)
                        sys.exit(0)
            logging.debug(">>>>>>>>>>>>>>>>>>> Polling")
            asyncio.gather(poll_loop(), event_loop(), self.port4400, self.port4700, self.images)
        except Exception as ex:
            logging.error("Poll error %s", ex)

    async def _handle_event(self, event, payload):
        if event == "Exposure" and payload["state"] == "complete":
            self.image_available.set()
        if event == "WheelMove" and payload["state"] == "complete":
            if self.wheel_names is None:
                self.wheel_names = await self.jsonrpc_call(4700, 'get_wheel_slot_name')
            asyncio.gather(
                self.update_q.put({'method': 'WheelName', 'code': 0, 'result': self.wheel_names[payload["position"]]}),
                self.update_q.put({'method': 'get_wheel_position', 'code': 0, 'result': payload["position"]})
            )
        elif event == "CameraControlChange":
            camera = self.devices['camera']
            logging.debug('CameraControlChange - publishing updates.')
            for component in [camera.gain, camera.exposure_seconds, camera.cooler_power, camera.dewheater]:
                logging.debug('  %s %s', component, component.component_id)
                try:
                    await component.publish(camera)
                except Exception as ex:
                    logging.debug('exception %s', ex)
                logging.debug('complete')


            for command in CAMERA_COMMANDS_4700:
                (method, args) = command_args(command)
                await self.jsonrpc_call_async(4700, method, *args)
        elif event == "ScopeTrack":
            await self.update_q.put({'method': 'scope_get_track_state', 'code': 0, 'result': payload["state"] == "on"})


    async def read_events(self, cmd_q, port: int):
        q = self.update_q
        event_map = {}
        print("Connecting to port " + str(port))
        reader, writer = await asyncio.open_connection('asiair', port)

        async def exec_and_keepalive(interval_seconds: int = 8):
            id = 1
            while True:
                try:
                    command = await asyncio.wait_for(cmd_q.get(), interval_seconds)
                    if isinstance(command, tuple) and len(command) == 3:
                        (method, args, event) = command
                        command = (method, args)
                        event_map[id] = event
                    writer.write((json.dumps(jsonrpc.make_command(id, command)) + "\r\n").encode())
                    id += 1
                except asyncio.TimeoutError:
                    await self.jsonrpc_call_async(port, "test_connection")
                except Exception as ex:
                    logging.error("Failed in command handling: %s", ex)

        keepalive = asyncio.create_task(exec_and_keepalive())
        while True:
            message = await reader.readline()
            if not message:
                print("EOF on port " + str(port))
                break
            #print("Putting on Q: " + message.decode())
            message = message.replace(b"<\x90\xadE\xb6>", b"???")
            message = message.replace(b"<\xe8>", b"???")
            message = message.decode('iso-8859-1')
            try:
                message = json.loads(message)
                if "method" in message and message["id"] in event_map:
                    logging.debug("Reponse to message %d", message["id"])
                    event = event_map[message["id"]]
                    try:
                        event.result = message["result"]
                    except KeyError as ke:
                        event.result = None
                        event.error = message.get("error", None)
                    event.set()

                # Handle any immediate routing/updates.
                #logging.debug("Received %s", message)
                if "Event" in message:
                    try:
                        #await self._handle_event(message["Event"], message)
                        await self.event_q.put((message['Event'], message))
                    except Exception as ex:
                        logging.debug(ex)
                        sys.exit(1)
                # Send it to the legacy queue.
                await q.put(message)
            except Exception as ex:
                logging.error(ex)
        await keepalive

    async def read_images(self, port=4800):
        q = self.update_q
        image_available = self.image_available
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
                                rawImage = np.ndarray(shape=(height, width), dtype="<u2", buffer=rawData.read())
                                imageData = await ImageManipulation.normalize_image(rawImage)
                                imageData = await ImageManipulation.compute_astropy_stretch(imageData)
                                imageData = await ImageManipulation.resize_image(imageData)
                                (result, imageData) = cv2.imencode(".png", imageData)
                                byteArray = bytearray(imageData)
                                print("MQTT publish result: " + str(result) + "; Len: " + str(len(byteArray)))
                                await q.put(byteArray)
                    else:
                        print(str(port) + " Width <= 0")
                        print(str(port) + " => " + str(header))
            except Exception as ex:
                logging.error(ex)

class ZwoAsiairDevice(Device):
    """ The ASIAIR itself. """
    def __init__(self, parent: ZwoAsiair, name):
        super().__init__(parent, name)

    def get_mqtt_device_config(self):
        pi_info = self.parent.pi_info
        return {
            'name': 'ZWO ASIAIR',
            'manufacturer': 'Suzhou ZWO Co., Ltd',
            'model': pi_info.model,
            'serial_number': pi_info.guid,
            'identifiers': [pi_info.guid, pi_info.cpuId],
            'suggested_area': 'Observatory',
            'sw_version': pi_info.uname,
        }
    
    @sensor(
        name="CPU ID",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon="mdi:raspberry-pi",
        unique_id='1235qwv45h4'
    ) 
    async def cpuid(self):
        return self.parent.pi_info.cpuId
    
    @sensor(
        name="CPU Temperature",
        unit_of_measurement=UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
        icon="mdi:thermometer",
        unique_id='1235qwv45h6'
    ) 
    async def cpu_temp(self):
        self.parent.pi_info = FromJson(await self.parent.jsonrpc_call(4700, 'pi_get_info'))
        return self.parent.pi_info.temp

class Focuser(Device):
    """ The ASIAIR itself. """
    def __init__(self, parent: ZwoAsiair, name):
        super().__init__(parent, name)

    def get_mqtt_device_config(self):
        pi_info = self.parent.pi_info
        return {
            'name': 'ZWO ASIAIR - Focuser',
            'model': 'Focuser',
            'manufacturer': 'Suzhou ZWO Co., Ltd',
            'identifiers': [pi_info.guid + '_focuser'],
            'suggested_area': 'Observatory',
        }
    
    @sensor(
        name="Position",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_FOCUSER_ICON,
        unique_id='1236qw245h6'
    ) 
    async def position(self):
        return await self.parent.jsonrpc_call(4700, 'get_focuser_position')

class FilterWheel(Device):
    """ The ASIAIR filter wheel. """
    def __init__(self, parent: ZwoAsiair, name):
        self.wheel_names = []
        super().__init__(parent, name)

    def get_mqtt_device_config(self):
        pi_info = self.parent.pi_info
        return {
            'name': 'ZWO ASIAIR - Filter Wheel',
            'model': 'Filter Wheel',
            'manufacturer': 'Suzhou ZWO Co., Ltd',
            'identifiers': [pi_info.guid + '_efw'],
            'suggested_area': 'Observatory',
        }
    
    @sensor(
        name="Current",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_FILTERWHEEL_ICON,
        unique_id='1236qw345h6'
    ) 
    async def current(self):
        (self.wheel_names, position) = await asyncio.gather(
            self.parent.jsonrpc_call(4700, 'get_wheel_slot_name'),
            self.parent.jsonrpc_call(4700, 'get_wheel_position')
        )
        if len(self.wheel_names) > 0:
            return self.wheel_names[position]
        else:
            return None

class Camera(Device):
    """ The ASIAIR camera. """
    def __init__(self, parent: ZwoAsiair, name):
        super().__init__(parent, name)

    def get_mqtt_device_config(self):
        pi_info = self.parent.pi_info
        return {
            'name': 'ZWO ASIAIR - Camera',
            'model': 'Camera',
            'manufacturer': 'Suzhou ZWO Co., Ltd',
            'identifiers': [pi_info.guid + '_camera'],
            'suggested_area': 'Observatory',
        }
    
    @sensor(
        name="Name",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        unique_id='awe4t4ats-1'
    ) 
    async def name(self):
        return (await self.parent.jsonrpc_call(4700, 'get_camera_state'))['name']

    @sensor(
        name="State",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        unique_id='awe4t4ats-2'
    ) 
    async def state(self):
        return (await self.parent.jsonrpc_call(4700, 'get_camera_state'))['state']
    
    @sensor(
        name="Cooler Power",
        unit_of_measurement=UNIT_OF_MEASUREMENT_PERCENTAGE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
        unique_id='awe4t4ats-3'
    ) 
    async def cooler_power(self):
        try:
            control_value_response = await asyncio.wait_for(self.parent.jsonrpc_call(4700, 'get_control_value', 'CoolPowerPerc'), 5)
            logging.debug(control_value_response)
        except:
            sys.exit(0)
        return (control_value_response)['value']
    
    @sensor(
        name="Gain",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
        unique_id='awe4t4ats-4'
    ) 
    async def gain(self):
        return (await self.parent.jsonrpc_call(4700, 'get_control_value', 'Gain'))['value']
    
    @sensor(
        name="Exposure",
        unit_of_measurement=UNIT_OF_MEASUREMENT_SECONDS,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
        unique_id='awe4t4ats-5'
    ) 
    async def exposure_seconds(self):
        return (await self.parent.jsonrpc_call(4700, 'get_control_value', 'Exposure'))['value'] / (1000*1000)

    @switch(
        name='Dew Heater',
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon='mdi:heating-coil',
        device_class=DEVICE_CLASS_SWITCH,
        state_class=STATE_CLASS_NONE,
        unique_id='awe4t4ats-6',
        value_template='{% if value_json == 0 %}OFF{% else %}ON{% endif %}',
        command_template='{% if value == "ON" %}1{% else %}0{% endif %}'
    ) 
    async def dewheater(self):
        return (await self.parent.jsonrpc_call(4700, 'get_control_value', 'AntiDewHeater'))['value']

    @dewheater.command
    async def set_dewheater(self, value):
        error_code = await self.parent.jsonrpc_call(4700, 'set_control_value', 'AntiDewHeater', value)
        if error_code == 0:
            return value # return the latest value for publication.
        else:
            raise RuntimeError("Non-zero exit code for " + function.__name__)

    @climate(
        name='Cooling',
        temperature_unit='C',
        icon='mdi:snowflake',
        max_temp=40,
        min_temp=40,
        modes=['off', 'cool'],
        unique_id='awe4t4ats-7')
    async def cooling(self):
        pass

    @cooling.temperature_command
    async def set_cooling_temperature(self, temp):
        return temp

    @cooling.mode_state
    async def cooling_mode(self):
        return 'off'

    @cooling.mode_command
    async def set_cooling_mode(self, mode):
        return 'off'

nothing = [
#        [
#            TYPE_SENSOR,
#            "CCD temperature",
#            UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
#            DEVICE_TYPE_CAMERA_ICON,
#            DEVICE_CLASS_TEMPERATURE,
#            STATE_CLASS_MEASUREMENT,
#            "asiair/Temperature",
#            "{{ value_json.value }}"
#        ],
#        [
#            TYPE_CLIMATE,
#           "Cooling",
#            UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
#            DEVICE_TYPE_CAMERA_ICON,
#            DEVICE_CLASS_TEMPERATURE,
#            STATE_CLASS_MEASUREMENT,
#            "asiair/Temperature",
#            "{{ value_json.value }}"
#        ],
#        [
#            TYPE_BINARY_SENSOR,
#            "Cooler on",
#            UNIT_OF_MEASUREMENT_NONE,
#            DEVICE_TYPE_CAMERA_ICON,
#            DEVICE_CLASS_NONE,
#            STATE_CLASS_NONE,
#            "asiair/cooleron",
#            "{% if value_json.value == 0 %}OFF{% else %}ON{% endif %}"
#        ],

]