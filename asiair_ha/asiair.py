import asyncio
import struct
import tempfile
import json, time
import zipfile
import paho.mqtt.client as mqtt
import logging
from astrolive.image import ImageManipulation
from const import (
    CAMERA_SAMPLE_RESOLUTION,
)
import jsonrpc


import cv2
import numpy as np
from observatory_software import ObservatorySoftware

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
    ("get_control_value", ["Exposure"]),
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

class ZwoAsiair(ObservatorySoftware):

    def __init__(self, name, address):
        self._address = address
        self.rpc_command_id = 1
        super().__init__(name)

    @staticmethod
    def create(name: str, address: str, **kwargs):
        return ZwoAsiair(name, address=address)
     
    async def connect(self):
        self.update_q = asyncio.Queue()
        self.cmd_q_4400 = asyncio.Queue()
        self.cmd_q_4700 = asyncio.Queue()
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
        return event.result

    async def discover(self):
        result = await self.jsonrpc_call(4700, 'pi_get_info')
        logging.debug(result)
  
    async def poll(self):
        async def poll_loop():
            while True:
                for port in [4400, 4700]:
                    for command in COMMANDS[str(port)]:
                        if isinstance(command, tuple):
                            (method, args) = command
                        else:
                            (method, args) = (command, [])
                        await self.jsonrpc_call_async(port, method, *args)
                await asyncio.sleep(15)
        task = await asyncio.create_task(poll_loop())
        await self.port4400
        await self.port4700
        await self.images
        await task

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
                    event.result = message["result"]
                    event.set()
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
