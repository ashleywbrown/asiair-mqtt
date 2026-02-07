import json
import logging
import aiohttp
import asyncio

from const import DEVICE_TYPE_CAMERA_ICON
from hass_mqtt import mqtt_device
from observatory_software import Camera, Device, FilterWheel, ObservatorySoftware, Telescope
from cachetools import TTLCache
from cachetools_async import cached

class Nina(ObservatorySoftware):
    def __init__(self, name, host='localhost', port='1888'):
        self.host = host
        self.port = port
        self.session = None
        self.devices = {
            'camera': NinaCamera(self, 'camera'),
            'telescope': NinaTelescope(self, 'telescope'),
            'filterwheel': NinaFilterWheel(self, 'filterwheel'),
        }
        super().__init__(name)

    @staticmethod
    def create(name: str, **kwargs):
        return Nina(name, **kwargs)


    async def connect(self):
        self.session = aiohttp.ClientSession('http://{0}:{1}/v2/api/'.format(self.host, self.port))
        asyncio.create_task(self.listen_websocket())

    async def listen_websocket(self):
        url = 'ws://{0}:{1}/v2'.format(self.host, self.port)
        while True:
            try:
                logging.info("Connecting to NINA WebSocket: %s", url)
                async with self.session.ws_connect(url) as ws:
                    logging.info("Connected to NINA WebSocket")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            logging.debug("NINA WS Message: %s", msg.data)
                            try:
                                data = json.loads(msg.data)
                                await self.handle_message(data)
                            except Exception as e:
                                logging.error("Error handling NINA message: %s", e)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logging.error("NINA WebSocket connection closed with error %s", ws.exception())
                            break
            except Exception as e:
                logging.error("NINA WebSocket error: %s", e)
            
            await asyncio.sleep(5)

    async def handle_message(self, data):
        logging.debug("NINA Handle Message: %s", data)
        response = data.get('Response')
        
        if not isinstance(response, dict):
            return

        evt_type = response.get('Event')
        
        if not evt_type:
            return

        if evt_type == 'FILTERWHEEL-CHANGED':
            fw = self.devices['filterwheel']
            new_filter = response.get('New')
            if new_filter and 'Name' in new_filter:
                await fw.update_property('current', new_filter['Name'], source='push')

        elif evt_type == 'IMAGE-SAVE':
            camera = self.devices['camera']
            stats = response.get('ImageStatistics')
            if stats:
                if 'Gain' in stats:
                    await camera.update_property('gain', stats['Gain'], source='push')
                if 'Temperature' in stats:
                    await camera.update_property('cooling', stats['Temperature'], source='push')

    async def discover(self):
        return self.devices

    async def poll(self):
        while True:
            for device in self.devices.values():
                await device.fetch_data()
            await asyncio.sleep(20)
    
    @cached(cache=TTLCache(maxsize=30, ttl=10))
    async def _poll(self, path, **kwargs):
        return await self._get(path, **kwargs)

    async def _get(self, path, **kwargs):
        async with self.session.get(path, params=kwargs) as response:
            #print(response)
            #print("Status:", response.status)
            #print("Content-type:", response.headers['content-type'])
            json = await response.json()
            #print(json)
            return json['Response']

    async def get_camera_info(self):
        return await self._poll('equipment/camera/info')
    
    async def get_mount_info(self):
        return await self._poll('equipment/mount/info')
    
    async def get_fw_info(self):
        return await self._poll('equipment/filterwheel/info')

    async def set_dewheater(self, on: bool):
        await self._get('equipment/camera/dew-heater', power=json.dumps(on))
        return on
    
    async def set_cooling(self, on: bool):
        if on:
            temperature = (await self.get_camera_info())['TargetTemp']
            await self._get('equipment/camera/cool', temperature=temperature, minutes=-1)
        else:
            await self._get('equipment/camera/warm', minutes=-1)
        return on
    
    async def set_tracking(self, on: bool):
        if on:
            # Figure out which mode to set. temperature = (await self.get_camera_info())['TargetTemp']
            await self._get('equipment/mount/tracking', mode=0) # 0 = Sidereal
        else:
            await self._get('equipment/mount/tracking', mode=4) # 4 = Stopped
        return on

class NinaDevice(Device):
    def __init__(self, parent: Nina, name):
        super().__init__(parent, name)

    def uuid(self):
        return '_'.join([self.parent.host, self.parent.port, self.parent.name, self.name])
    
@mqtt_device()
class NinaCamera(NinaDevice, Camera):
    
    def get_mqtt_device_config(self):
        return {
            'name': 'NINA ({0}:{1}) - Camera'.format(self.parent.host, self.parent.port),
            'model': 'Camera',
            'manufacturer': 'NINA',
            'identifiers': [self.uuid()],
            'suggested_area': 'Observatory',
        }
    
    async def fetch_value(self, value: str):
        return (await self.parent.get_camera_info())[value]
    
    async def _device_name(self):
        return await self.fetch_value('Name')

    async def _cooler_power(self):
        return await self.fetch_value('CoolerPower')
    
    async def _dewheater(self):
        return await self.fetch_value('DewHeaterOn')

    async def _set_dewheater(self, on):
        return await self.parent.set_dewheater(on)
    
    async def _gain(self):
        return await self.fetch_value('Gain')

    async def _cooling_current_temperature(self):
        return await self.fetch_value('Temperature')

    async def _cooling_target_temperature(self):
        return await self.fetch_value('TargetTemp')

    async def _set_cooling_target_temperature(self, temp):
        raise NotImplementedError

    async def _cooling_mode(self):
        return 'cool' if await self.fetch_value('CoolerOn') else 'off'

    async def _set_cooling_mode(self, mode: str):
        await self.parent.set_cooling(mode != 'off')
        return mode

    async def _set_cooling_power(self, onoff: str):
        raise NotImplementedError

    async def _cooling_action(self):
        return 'cooling' if (await self.fetch_value('CoolerPower')) > 0 else 'off'
    

@mqtt_device()
class NinaTelescope(NinaDevice, Telescope):
    
    def get_mqtt_device_config(self):
        return {
            'name': 'NINA ({0}:{1}) - Telescope'.format(self.parent.host, self.parent.port),
            'model': 'Telescope',
            'manufacturer': 'NINA',
            'identifiers': [self.uuid()],
            'suggested_area': 'Observatory',
        }

    async def _altitude(self):
        info = await self.parent.get_mount_info()
        if isinstance(info, dict):
            return info.get('Altitude')
        return None
    
    async def _azimuth(self):
        info = await self.parent.get_mount_info()
        if isinstance(info, dict):
            return info.get('Azimuth')
        return None
    
    async def _right_ascension(self):
        info = await self.parent.get_mount_info()
        if isinstance(info, dict):
            return info.get('RightAscension')
        return None
    
    async def _declination(self):
        info = await self.parent.get_mount_info()
        if isinstance(info, dict):
            return info.get('Declination')
        return None
    
    async def _tracking(self):
        info = await self.parent.get_mount_info()
        if isinstance(info, dict):
            return info.get('TrackingEnabled')
        return False
    
    async def _set_tracking(self, on: bool):
        return await self.parent.set_tracking(on)
  
    async def _track_mode(self):
        info = await self.parent.get_mount_info()
        if isinstance(info, dict):
            return info.get('TrackingMode', '-')
        return '-'
    
    async def _site_latlon(self):
        info = await self.parent.get_mount_info()
        if isinstance(info, dict):
            return (info.get('SiteLatitude', 0), info.get('SiteLongitude', 0))
        return (0, 0)
    
@mqtt_device()
class NinaFilterWheel(NinaDevice, FilterWheel):
    
    def get_mqtt_device_config(self):
        return {
            'name': 'NINA ({0}:{1}) - Filter Wheel'.format(self.parent.host, self.parent.port),
            'model': 'Filter Wheel',
            'manufacturer': 'NINA',
            'identifiers': [self.uuid()],
            'suggested_area': 'Observatory',
        }
    
    async def _current(self):
        return (await self.parent.get_fw_info())['SelectedFilter']['Name']
