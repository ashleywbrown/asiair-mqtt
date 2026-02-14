import asyncio
from collections import namedtuple
import struct
import sys
import tempfile
import json
import zipfile
from cachetools import TTLCache
from cachetools_async import cached
import logging
from hass_mqtt import binary_sensor, mqtt_device, sensor
from astrolive.image import ImageManipulation
from const import (
    DEVICE_TYPE_CAMERA_ICON,
    DEVICE_TYPE_FOCUSER_ICON,
    DEVICE_TYPE_TELESCOPE_ICON,
    UNIT_OF_MEASUREMENT_NONE,
    UNIT_OF_MEASUREMENT_TEMP_CELSIUS,
)
import jsonrpc


import cv2
import numpy as np
from observatory_software import Camera, Device, FilterWheel, Guider, ObservatorySoftware, Telescope

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
            'guider': AsiAirGuider(self, 'guider'),
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
            raise RuntimeError(f"Non-zero exit code for set_control_value({value_name})")

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

    @cached(cache=TTLCache(maxsize=30, ttl=10))
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
        if hasattr(event, 'result') and event.result is not None:
            return event.result
        else:
            error = getattr(event, 'error', 'Unknown error')
            logging.error('Error during synchronous call: %s', error)
            raise RuntimeError(f"JSONRPC call failed: {error}")

    async def discover(self):
        self.pi_info = FromJson(await self.jsonrpc_call(4700, 'pi_get_info'))
        logging.debug(self.pi_info)
        return self.devices
  
    async def poll(self):
        logging.debug(">>>>>>>>>>>>>>>>>>> Getting filter wheel")
        try:
            (self.wheel_names, position) = await asyncio.gather(
                self.jsonrpc_call(4700, 'get_wheel_slot_name'),
                self.jsonrpc_call(4700, 'get_wheel_position')
            )
            if len(self.wheel_names) > 0:
                await self.update_q.put({'method': 'WheelName', 'code': 0, 'result': self.wheel_names[position]}),
        except Exception as e:
            logging.error(f"Failed to fetch initial filter wheel info: {e}")

        # Process events from the event queue.
        async def event_loop():
            while True:
                try:
                    (event, payload) = await self.event_q.get()
                    await self._handle_event(event, payload)
                except Exception as ex:
                    logging.error(f"Event loop error: {ex}")

        async def poll_loop():
            while True:
                try:
                    for device in self.devices.values():
                        await device.fetch_data()
                    await asyncio.sleep(45)
                except Exception as ex:
                    logging.error(f"Poll loop error: {ex}")
                    await asyncio.sleep(45)

        logging.debug(">>>>>>>>>>>>>>>>>>> Polling")
        await asyncio.gather(poll_loop(), event_loop(), self.port4400, self.port4700, self.images)

    async def _handle_event(self, event, payload: dict|bytearray):
        logging.debug('Event %s %s', event, payload)
        camera = self.devices['camera']
        efw = self.devices['efw']
        asiair = self.devices['asiair']
        telescope = self.devices['telescope']
        guider = self.devices['guider']
        if event == "Exposure":
            if payload["state"] == "complete":
                self.image_available.set()
            await camera.update_property('state', payload["state"], source='push')
        elif event == "Temperature":
            await camera.update_property('cooling', payload['value'], source='push')
        elif event == "CoolerPower":
            await camera.update_property('cooler_power', payload['value'], source='push')
        elif event == 'ImageDownload':
            await camera.update_property('image', payload, source='push')
        elif event == "PiStatus":
            asiair.pi_status = FromJson(payload)
            await asiair.cpu_temp.publish(asiair)
        elif event == "ScopeTrack":
            await telescope.update_property('tracking', payload["state"] == "on", source='push')

        if event == "WheelMove" and payload["state"] == "complete":
            position = payload.get('position')
            # The filter wheel names are cached on the efw device itself from polling.
            if position is not None and efw.wheel_names and len(efw.wheel_names) > position:
                await efw.update_property('current', efw.wheel_names[position], source='push')
            else:
                # Fallback to a full poll if we don't have the info needed.
                await efw.fetch_data()
        elif event == "CameraControlChange":
            await camera.fetch_data()
        elif event == "ScopeTrack":
            await self.update_q.put({'method': 'scope_get_track_state', 'code': 0, 'result': payload["state"] == "on"})
        elif event == "GuideStep":
            await guider.update_property('star_mass', payload.get('StarMass'), source='push')
            await guider.update_property('snr', payload.get('SNR'), source='push')
            await guider.update_property('ra_distance', payload.get('RADistanceRaw'), source='push')
            await guider.update_property('dec_distance', payload.get('DECDistanceRaw'), source='push')
            await guider.update_property('total_distance', payload.get('AvgDist'), source='push')


    async def read_events(self, cmd_q, port: int):
        q = self.update_q
        event_map = {}
        retry_delay = 5
        
        while True:
            try:
                print("Connecting to port " + str(port))
                reader, writer = await asyncio.open_connection(self._address, port)
                logging.info(f"Connected to {self._address}:{port}")
                retry_delay = 5

                async def exec_and_keepalive(interval_seconds: int = 8):
                    id = 1
                    while True:
                        try:
                            command = await asyncio.wait_for(cmd_q.get(), interval_seconds)
                            if isinstance(command, tuple) and len(command) == 3:
                                (method, args, event) = command
                                command = (method, args)
                                event_map[id] = event
                            
                            try:
                                writer.write((json.dumps(jsonrpc.make_command(id, command)) + "\r\n").encode())
                                await writer.drain()
                            except Exception as e:
                                logging.error(f"Write failed on port {port}: {e}")
                                try:
                                    writer.close()
                                except:
                                    pass
                                raise e

                            id += 1
                        except asyncio.TimeoutError:
                            await self.jsonrpc_call_async(port, "test_connection")
                        except Exception as ex:
                            logging.error("Failed in command handling: %s", ex)
                            if isinstance(ex, (ConnectionError, OSError)):
                                break

                keepalive = asyncio.create_task(exec_and_keepalive())

                while True:
                    try:
                        message = await reader.readline()
                    except Exception as e:
                        logging.error(f"Read error on port {port}: {e}")
                        break

                    if not message:
                        print("EOF on port " + str(port))
                        break
                    
                    message = message.replace(b"<\x90\xadE\xb6>", b"???")
                    message = message.replace(b"<\xe8>", b"???")
                    message = message.decode('iso-8859-1')
                    try:
                        message = json.loads(message)
                        if "method" in message and message["id"] in event_map:
                            event = event_map[message["id"]]
                            try:
                                event.result = message["result"]
                            except KeyError as ke:
                                event.result = None
                                event.error = message.get("error", None)
                            event.set()
                            del event_map[message["id"]]

                        if "Event" in message:
                            try:
                                await self.event_q.put((message['Event'], message))
                            except Exception as ex:
                                logging.error(f"Error putting event on queue: {ex}")
                        
                        await q.put(message)
                    except Exception as ex:
                        logging.error(f"Error processing message: {ex}")
                
                keepalive.cancel()
                try:
                    await keepalive
                except asyncio.CancelledError:
                    pass
                
                # Clear pending events to unblock waiters
                for event in event_map.values():
                    event.error = "Connection lost"
                    event.result = None
                    event.set()
                event_map.clear()

                try:
                    writer.close()
                    await writer.wait_closed()
                except:
                    pass

            except Exception as ex:
                logging.error(f"Connection error on port {port}: {ex}")
            
            logging.info(f"Reconnecting to ASIAIR port {port} in {retry_delay:.1f} seconds...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.2, 120)

    async def read_images(self, port=4800):
        image_available = self.image_available
        retry_delay = 5
        
        while True:
            try:
                print(f"Connecting to image port {port}")
                reader, writer = await asyncio.open_connection(self._address, port)
                logging.info(f"Connected to ASIAIR image port {port}")
                retry_delay = 5
                
                id = 1
                while True:
                    await image_available.wait()
                    image_available.clear()
                    
                    try:
                        command = "get_current_img"
                        writer.write((json.dumps({"id": id, "method": command}) + "\r\n").encode())
                        await writer.drain()
                    except Exception as e:
                        logging.error(f"Image write error: {e}")
                        break

                    id = id + 1
                    print(str(port) + " Reading 80")
                    
                    try:
                        header = await reader.readexactly(80)
                    except Exception as e:
                        logging.error(f"Image read header error: {e}")
                        break

                    if len(header) < 80:
                        print(str(port) + " Failed to read header")
                        break
                    
                    (size, width, height) = struct.unpack("!xxxxxxIxxxxxxHHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", header)
                    remaining = size
                    print(str(port) + " Header " + str((size, width, height)))
                    if width > 0:
                        logging.debug(str(port) + " Zipped Image Size: " + str(size) + " " + str(width) + "x" + str(height))
                        try:
                            with tempfile.TemporaryFile("w+b") as f:
                                while remaining > 0:
                                    chunkSize = min(remaining, 4*1024*1024)
                                    chunk = await reader.read(chunkSize)
                                    if not chunk:
                                        raise Exception("Unexpected EOF reading image body")
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

                                    await self.event_q.put(('ImageDownload', byteArray))
                        except Exception as e:
                            logging.error(f"Error processing image: {e}")
                            break
                    else:
                        print(str(port) + " Width <= 0")
                        print(str(port) + " => " + str(header))
                
                try:
                    writer.close()
                    await writer.wait_closed()
                except:
                    pass

            except Exception as ex:
                logging.error(f"Image connection error: {ex}")
            
            logging.info(f"Reconnecting to ASIAIR image port {port} in {retry_delay:.1f} seconds...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.2, 120)

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
class Telescope(ZwoAsiairDevice, Telescope):

    def get_mqtt_device_config(self):
        pi_info = self.parent.pi_info
        return {
            'name': 'ZWO ASIAIR - Telescope',
            'model': 'Telescope',
            'manufacturer': 'Suzhou ZWO Co., Ltd',
            'identifiers': [pi_info.guid + '_telescope'],
            'suggested_area': 'Observatory',
        }
    
    async def _altitude(self):
        return (await self.parent.scope_get_horiz_coord())[0]
    
    async def _azimuth(self):
        return (await self.parent.scope_get_horiz_coord())[1]
    
    async def _right_ascension(self):
        return (await self.parent.scope_get_ra_dec())[0]
    
    async def _declination(self):
        return (await self.parent.scope_get_ra_dec())[1]
    
    @sensor(
        name="Pier Side",
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        device_class='enum',
        enum=['pier_east', 'pier_west']
    ) 
    async def pier_side(self):
        return await self.parent.scope_get_pierside()

    async def _track_mode(self):
        track_mode = await self.parent.scope_get_track_mode()
        return track_mode.list[track_mode.index]

    async def _tracking(self):
        return await self.parent.scope_get_track_state()
    
    async def _set_tracking(self, on: bool):
        return await self.parent.scope_set_track_state(on)
    
    async def _site_latlon(self):
        return await self.parent.scope_get_location()
    
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
class FilterWheel(ZwoAsiairDevice, FilterWheel):
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
    
    async def _current(self):
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
    
    async def _gain(self):
        return await self.parent.get_control_value('Gain')
    
    async def _exposure_seconds(self):
        return await self.parent.get_control_value('Exposure') / (1000*1000)

    async def _dewheater(self):
        return bool(await self.parent.get_control_value('AntiDewHeater'))

    async def _set_dewheater(self, value):
        error_code = await self.parent.jsonrpc_call(4700, 'set_control_value', 'AntiDewHeater', int(value))
        if error_code == 0:
            await self.update_property('dewheater', value, source='push')
        else:
            raise RuntimeError("Non-zero exit code for _set_dewheater")

    async def _cooling_current_temperature(self):
        return self.get_property('cooling')

    async def _cooling_target_temperature(self):
        return await self.parent.get_control_value('TargetTemp')

    async def _set_cooling_target_temperature(self, temp):
        await self.parent.set_control_value('TargetTemp', temp)
        await self.update_property('get_cooling_temperature', temp, source='push')

    async def _cooling_mode(self):
        return 'cool' if bool(await self.parent.get_control_value('CoolerOn')) else 'off'

    async def _set_cooling_mode(self, mode: str):
        logging.debug('Setting cooling mode to %s', mode)
        is_on = 1 if mode != 'off' else 0
        await self.parent.set_control_value('CoolerOn', is_on)
        await self.update_property('cooling_mode', mode, source='push')

    async def _set_cooling_power(self, onoff: str):
        is_on = int(onoff != 'OFF')
        await self.parent.set_control_value('CoolerOn', is_on)
        await self.update_property('cooling_mode', 'cool' if is_on else 'off', source='push')

    async def _cooling_action(self):
        return await self.parent.get_control_value('CoolPowerPerc')

@mqtt_device()
class AsiAirGuider(ZwoAsiairDevice, Guider):
    """ The ASIAIR Guider. """
    def get_mqtt_device_config(self):
        pi_info = self.parent.pi_info
        return {
            'name': 'ZWO ASIAIR - Guider',
            'model': 'Guider',
            'manufacturer': 'Suzhou ZWO Co., Ltd',
            'identifiers': [pi_info.guid + '_guider'],
            'suggested_area': 'Observatory',
        }