import asyncio
from collections import namedtuple
import struct
import sys
import tempfile
import json, time
import zipfile
import paho.mqtt.client as mqtt
import logging
from hass_mqtt import binary_sensor, camera, climate, device_tracker, mqtt_device, sensor, switch
from astrolive.image import ImageManipulation
from const import (
    DEVICE_CLASS_SWITCH,
    DEVICE_TYPE_CAMERA_ICON,
    DEVICE_TYPE_FILTERWHEEL_ICON,
    DEVICE_TYPE_FOCUSER_ICON,
    DEVICE_TYPE_TELESCOPE_ICON,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_NONE,
    UNIT_OF_MEASUREMENT_DEGREE,
    UNIT_OF_MEASUREMENT_NONE,
    UNIT_OF_MEASUREMENT_PERCENTAGE,
    UNIT_OF_MEASUREMENT_SECONDS,
    UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
    UNIT_OF_MEASUREMENT_VOLTAGE,
)
import jsonrpc


import cv2
import numpy as np
from observatory_software import Camera, Device, ObservatorySoftware

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
#FILTER_WHEEL_COMMANDS_4700 = ["get_wheel_slot_name", "get_wheel_state", "get_wheel_setting", "get_wheel_position"]
#CAMERA_COMMANDS_4700 = [
#    "get_camera_info", # camera capabilities - pixel size, dimensions, cooling etc
#    "get_camera_exp_and_bin",
#    "get_subframe",
#   ]
SEQUENCE_COMMANDS_4700 = ["get_sequence", "get_sequence_number"]
TELESCOPE_COMMANDS_4400 = [
    "scope_get_location", "scope_is_moving", # 4400
    ]
TELESCOPE_COMMANDS_4700 = [
    "get_focal_length",
]
#FOCUSER_COMMANDS_4700 = [
#    "get_focuser_state",
#    "get_focuser_caps",
#    "get_focuser_value",
#    ]

PI_STATUS_COMMANDS_4700 = [
    #"pi_is_verified",
    "get_app_state", # Returns everything needed to configure the UI, including active page
    #"pi_get_time",
    "pi_get_info",
#    "pi_get_ap",
    ]
DEVICE_LIST_COMMANDS_4700 = ["get_connected_cameras"]

COMMANDS_PORT_4700 = (
    #FILTER_WHEEL_COMMANDS_4700 +
    SEQUENCE_COMMANDS_4700 +
    TELESCOPE_COMMANDS_4700 +
    #FOCUSER_COMMANDS_4700 +
    PI_STATUS_COMMANDS_4700  
    #CAMERA_COMMANDS_4700
    )

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
            'asiair': ZwoAsiairPi(self, 'asiair'),
            'focuser': Focuser(self, 'focuser'),
            'efw': FilterWheel(self, 'efw'),
            'camera': AsiAirCamera(self, 'camera'),
            'telescope': Telescope(self, 'telescope'),
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

    async def get_control_value(self, value_name: str):
        return (await self.jsonrpc_call(4700, 'get_control_value', value_name))['value']

    async def set_control_value(self, value_name: str, value):
        error_code = await self.jsonrpc_call(4700, 'set_control_value', value_name, value)
        if error_code != 0:
            raise RuntimeError("Non-zero exit code for " + function.__name__)
        return value

    async def get_power_supply(self):
        result =  (await self.jsonrpc_call(4700, 'get_power_supply'))
        
        power_supply = namedtuple('PowerSupply', ['outputs', 'input'])(
            outputs=result[:-1],
            input=result[-1],
        )
        return power_supply
    
    async def pi_station_state(self):
        return FromJson(await self.jsonrpc_call(4700, 'pi_station_state'))
    
    async def get_app_state(self):
        return FromJson(await self.jsonrpc_call(4700, 'get_app_state'))

    async def get_sequence_setting(self):
        return FromJson(await self.jsonrpc_call(4700, 'get_sequence_setting'))
    
    async def scope_get_horiz_coord(self):
        return await self.jsonrpc_call(4400, 'scope_get_horiz_coord')

    async def scope_get_ra_dec(self):
        return await self.jsonrpc_call(4400, 'scope_get_ra_dec')

    async def scope_get_pierside(self):
        return await self.jsonrpc_call(4400, 'scope_get_pierside')

    async def scope_get_track_mode(self):
        return FromJson(await self.jsonrpc_call(4400, 'scope_get_track_mode'))

    async def scope_get_track_state(self):
        return await self.jsonrpc_call(4400, 'scope_get_track_state')

    async def scope_set_track_state(self, on: bool):
        return await self.jsonrpc_call(4400, 'scope_set_track_state', on)

    async def scope_get_location(self):
        return await self.jsonrpc_call(4400, 'scope_get_location')

    async def scope_is_moving(self):
        return await self.jsonrpc_call(4400, 'scope_is_moving')


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
                        await asyncio.sleep(45)
                    except Exception as ex:
                        logging.error(ex)
                        sys.exit(0)
            logging.debug(">>>>>>>>>>>>>>>>>>> Polling")
            asyncio.gather(poll_loop(), event_loop(), self.port4400, self.port4700, self.images)
        except Exception as ex:
            logging.error("Poll error %s", ex)
            sys.exit(0)

    async def _handle_event(self, event, payload: dict|bytearray):
        logging.debug('Event %s %s', event, payload)
        camera = self.devices['camera']
        efw = self.devices['efw']
        asiair = self.devices['asiair']
        telescope = self.devices['telescope']
        if event == "Exposure":
            if payload["state"] == "complete":
                self.image_available.set()
            await camera.state.publish(camera)
        elif event == "Temperature":
            camera.sensor_temperature = payload['value']
            await camera.cooling.publish(camera)
        elif event == "CoolerPower":
            await camera.cooler_power.publish(camera)
        elif event == 'ImageDownload':
            camera.latest_image = payload
            await camera.image.publish(camera)
            # We don't need to keep sending this on poll.
            camera.latest_image = None
        elif event == "PiStatus":
            asiair.pi_status = FromJson(payload)
            await asiair.cpu_temp.publish(asiair)
        elif event == "ScopeTrack":
            await telescope.tracking.publish(telescope)

        if event == "WheelMove" and payload["state"] == "complete":
            await efw.current.publish(efw)
        elif event == "CameraControlChange":
            for component in [camera.gain, camera.exposure_seconds, camera.cooler_power, camera.dewheater, camera.cooling]:
                try:
                    await component.publish(camera)
                except Exception as ex:
                    logging.error('exception %s', ex)
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
#                    logging.debug("Reponse to message %d", message["id"])
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

                                # New path
                                await self.event_q.put(('ImageDownload', byteArray))
                    else:
                        print(str(port) + " Width <= 0")
                        print(str(port) + " => " + str(header))
            except Exception as ex:
                logging.error(ex)

class ZwoAsiairDevice(Device):
    def __init__(self, parent: ZwoAsiair, name):
        super().__init__(parent, name)

    def uuid(self):
        return self.parent.pi_info.guid + '.' + self.name

@mqtt_device()
class ZwoAsiairPi(ZwoAsiairDevice):
    """ The ASIAIR itself. """
    def __init__(self, parent: ZwoAsiair, name):
        self.pi_status = None
        self.app_state = None
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
    
    def uuid(self):
        return self.parent.pi_info.guid + '.' + self.name

    @sensor(
        name='Target',
        icon='mdi:creation',
    ) 
    async def target(self):
        return (await self.parent.get_sequence_setting()).group_name
    
    @sensor(
        name='App Page',
        icon='mdi:file-document-outline',
    ) 
    async def page(self):
        return (await self.parent.get_app_state()).page

    @sensor(
        name='Wifi Station Signal Strength',
        unit_of_measurement='dB',
        icon='mdi:wifi',
        device_class='signal_strength',
        state_class='measurement',
        entity_category='diagnostic',
    ) 
    async def wifi_station_signal_level(self):
        return (await self.parent.pi_station_state()).sig_lev

    @sensor(
        name='Wifi Station Frequency',
        unit_of_measurement='MHz',
        icon='mdi:wifi',
        device_class='frequency',
        entity_category='diagnostic',
    ) 
    async def wifi_station_freq(self):
        return (await self.parent.pi_station_state()).freq
    
    @sensor(
        name='Wifi Station SSID',
        icon='mdi:wifi',
        entity_category='diagnostic',
    ) 
    async def wifi_station_ssid(self):
        return (await self.parent.pi_station_state()).ssid

    @sensor(
        name='Wifi Station IP',
        icon='mdi:wifi',
        entity_category='diagnostic',
    ) 
    async def wifi_station_ip(self):
        return (await self.parent.pi_station_state()).ip
    
    @sensor(
        name='Wifi Station Gateway',
        icon='mdi:wifi',
        entity_category='diagnostic',
    ) 
    async def wifi_station_gateway(self):
        return (await self.parent.pi_station_state()).gateway
    
    @sensor(
        name='Wifi Station Netmask',
        icon='mdi:wifi',
        entity_category='diagnostic',
    ) 
    async def wifi_station_netmask(self):
        return (await self.parent.pi_station_state()).netmask

    @sensor(
        name='CPU ID',
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon='mdi:raspberry-pi',
        entity_category='diagnostic',
    ) 
    async def cpuid(self):
        return self.parent.pi_info.cpuId
    
    @sensor(
        name='CPU Temperature',
        unit_of_measurement=UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
        icon='mdi:thermometer',
        entity_category='diagnostic',
    ) 
    async def cpu_temp(self):
        if self.pi_status is not None:
            return self.pi_status.temp
        elif self.parent.pi_info is not None:
            return self.parent.pi_info.temp
        else:
            return None

    @sensor(
        name='Port 1 Voltage',
        unit_of_measurement='V',
        icon='mdi:flash',
        device_class='voltage',
        state_class='measurement',
        suggested_display_precision=2,
        entity_category='diagnostic',
    )
    async def port_1_voltage(self):
        return (await self.parent.get_power_supply()).input[0]
    
    @sensor(
        name='Port 2 Voltage',
        unit_of_measurement='V',
        icon='mdi:flash',
        device_class='voltage',
        state_class='measurement',
        suggested_display_precision=2,
        entity_category='diagnostic',
    )
    async def port_2_voltage(self):
        return (await self.parent.get_power_supply()).input[0]
    
    @sensor(
        name='Port 3 Voltage',
        unit_of_measurement='V',
        icon='mdi:flash',
        device_class='voltage',
        state_class='measurement',
        suggested_display_precision=2,
        entity_category='diagnostic',
    )
    async def port_3_voltage(self):
        return (await self.parent.get_power_supply()).input[0]
    
    @sensor(
        name='Port 4 Voltage',
        unit_of_measurement='V',
        icon='mdi:flash',
        device_class='voltage',
        state_class='measurement',
        suggested_display_precision=2,
        entity_category='diagnostic',
    )
    async def port_4_voltage(self):
        return (await self.parent.get_power_supply()).input[0]
    
    @sensor(
        name='Input Voltage',
        unit_of_measurement='V',
        icon='mdi:flash',
        device_class='voltage',
        state_class='measurement',
        suggested_display_precision=2,
        entity_category='diagnostic',
    )
    async def input_voltage(self):
        return (await self.parent.get_power_supply()).input[0]

    @sensor(
        name='Input Voltage',
        unit_of_measurement='V',
        icon='mdi:flash',
        device_class='voltage',
        state_class='measurement',
        suggested_display_precision=2,
        entity_category='diagnostic',
    )
    async def input_voltage(self):
        return (await self.parent.get_power_supply()).input[0]

    @sensor(
        name='Input Current',
        unit_of_measurement='A',
        icon='mdi:flash',
        device_class='current',
        state_class='measurement',
        suggested_display_precision=2,
        entity_category='diagnostic',
    )
    async def input_current(self):
        return (await self.parent.get_power_supply()).input[1]

    @sensor(
        name='Input Power',
        unit_of_measurement='W',
        icon='mdi:flash',
        device_class='power',
        state_class='measurement',
        suggested_display_precision=2,
        entity_category='diagnostic',
    )
    async def input_power(self):
        input_supply = (await self.parent.get_power_supply()).input
        return input_supply[0] * input_supply[1]

@mqtt_device()
class Telescope(ZwoAsiairDevice):

    def get_mqtt_device_config(self):
        pi_info = self.parent.pi_info
        return {
            'name': 'ZWO ASIAIR - Telescope',
            'model': 'Telescope',
            'manufacturer': 'Suzhou ZWO Co., Ltd',
            'identifiers': [pi_info.guid + '_telescope'],
            'suggested_area': 'Observatory',
        }
    
    @sensor(
        name="Altitude",
        unit_of_measurement=UNIT_OF_MEASUREMENT_DEGREE,
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def altitude(self):
        return (await self.parent.scope_get_horiz_coord())[0]
    
    @sensor(
        name="Azimuth",
        unit_of_measurement=UNIT_OF_MEASUREMENT_DEGREE,
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def azimuth(self):
        return (await self.parent.scope_get_horiz_coord())[1]
    
    @sensor(
        name="Right Ascension",
        unit_of_measurement=UNIT_OF_MEASUREMENT_DEGREE,
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def right_ascension(self):
        return (await self.parent.scope_get_ra_dec())[0]
    
    @sensor(
        name="Declination",
        unit_of_measurement=UNIT_OF_MEASUREMENT_DEGREE,
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def declination(self):
        return (await self.parent.scope_get_ra_dec())[1]
    
    @sensor(
        name="Pier Side",
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        device_class='enum',
        enum=['pier_east', 'pier_west']
    ) 
    async def pier_side(self):
        return await self.parent.scope_get_pierside()

    @sensor(
        name="Track Mode",
        icon=DEVICE_TYPE_TELESCOPE_ICON,
    ) 
    async def track_mode(self):
        track_mode = await self.parent.scope_get_track_mode()
        return track_mode.list[track_mode.index]

    @switch(
        name="Tracking",
        icon=DEVICE_TYPE_TELESCOPE_ICON,
    ) 
    async def tracking(self):
        return await self.parent.scope_get_track_state()
    
    @tracking.command
    async def set_tracking(self, on: bool):
        return await self.parent.scope_set_track_state(on)
    
    @tracking.json_attributes
    async def tracking_attributes(self):
        return {
            'Mode': await self.track_mode()
        }

    @device_tracker(
        name='Site Location',
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        subscription_topics=['json_attributes'],
    )
    async def site_location(self):
        location = await self.parent.scope_get_location()
        return {
            'latitude': location[0],
            'longitude': location[1],
        }
    
    @binary_sensor(
        name='Slewing',
        icon='mdi:rotate-orbit',
    )
    async def is_slewing(self):
        return (await self.parent.scope_is_moving()) != 'none'

@mqtt_device()
class Focuser(ZwoAsiairDevice):
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
    ) 
    async def position(self):
        return await self.parent.jsonrpc_call(4700, 'get_focuser_position')

@mqtt_device()
class FilterWheel(ZwoAsiairDevice):
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

@mqtt_device()
class AsiAirCamera(ZwoAsiairDevice, Camera):
    """ The ASIAIR camera. """
    def __init__(self, parent: ZwoAsiair, name):
        self.sensor_temperature = None
        self.latest_image = None
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

    @camera(
        name="Latest Image",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
    ) 
    async def image(self):
        return self.latest_image

    async def _device_name(self):
        return (await self.parent.jsonrpc_call(4700, 'get_camera_state'))['name']

    @sensor(
        name="State",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
    ) 
    async def state(self):
        return (await self.parent.jsonrpc_call(4700, 'get_camera_state'))['state']
    
    async def _cooler_power(self):
        logging.debug('Got Cooler Power')
        return await self.parent.get_control_value('CoolPowerPerc')
    
    @sensor(
        name="Gain",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def gain(self):
        return await self.parent.get_control_value('Gain')
    
    @sensor(
        name="Exposure",
        unit_of_measurement=UNIT_OF_MEASUREMENT_SECONDS,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def exposure_seconds(self):
        return await self.parent.get_control_value('Exposure') / (1000*1000)

    @switch(
        name='Dew Heater',
        icon='mdi:heating-coil',
    ) 
    async def dewheater(self):
        return bool(await self.parent.get_control_value('AntiDewHeater'))

    @dewheater.command
    async def set_dewheater(self, value):
        error_code = await self.parent.jsonrpc_call(4700, 'set_control_value', 'AntiDewHeater', int(value))
        if error_code == 0:
            return value # return the latest value for publication.
        else:
            raise RuntimeError("Non-zero exit code for " + function.__name__)

    @climate(
        name='Cooling',
        temperature_unit='C',
        icon='mdi:snowflake',
        max_temp=40,
        min_temp=-40,
        modes=['off', 'cool'],
        action_template='{% if value_json == 0 %}off{% else %}cooling{% endif %}',
        )
    async def cooling(self):
        return self.sensor_temperature

    @cooling.temperature_state
    async def get_cooling_temperature(self):
        return await self.parent.get_control_value('TargetTemp')

    @cooling.temperature_command
    async def set_cooling_temperature(self, temp):
        return await self.parent.set_control_value('TargetTemp', temp)

    @cooling.mode_state
    async def cooling_mode(self):
        return 'cool' if bool(await self.parent.get_control_value('CoolerOn')) else 'off'

    @cooling.mode_command
    async def set_cooling_mode(self, mode: str):
        logging.error('Cooling mode %s', mode)
        await self.parent.set_control_value('CoolerOn', 1 if mode != 'off' else 0)
        return mode

    @cooling.power_command
    async def cooling_power(self, onoff: str):
        await self.parent.set_control_value('CoolerOn', int(onoff != 'OFF'))

    @cooling.action
    async def cooling_action(self):
        return await self.parent.get_control_value('CoolPowerPerc')