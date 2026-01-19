import json
import logging
import aiohttp
import asyncio

from const import DEVICE_TYPE_CAMERA_ICON
from hass_mqtt import climate, mqtt_device, sensor
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

    async def discover(self):
        return self.devices

    async def poll(self):
        while True:
            for device in self.devices.values():
                for component in device.components():
                    await component.publish(device)
            await asyncio.sleep(20)
    
    @cached(cache=TTLCache(maxsize=30, ttl=10))
    async def _poll(self, path, **kwargs):
        return await self._get(path, **kwargs)

    async def _get(self, path, **kwargs):
        async with self.session.get(path, params=kwargs) as response:
            print(response)
            print("Status:", response.status)
            print("Content-type:", response.headers['content-type'])
            json = await response.json()
            print(json)
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
        return await self.fetch_value('Temperature')

    @cooling.temperature_state
    async def get_cooling_temperature(self):
        return await self.fetch_value('TargetTemp')

    @cooling.temperature_command
    async def set_cooling_temperature(self, temp):
        raise NotImplementedError

    @cooling.mode_state
    async def cooling_mode(self):
        return 'cool' if await self.fetch_value('CoolerOn') else 'off'

    @cooling.mode_command
    async def set_cooling_mode(self, mode: str):
        await self.parent.set_cooling(mode != 'off')
        return mode

    @cooling.power_command
    async def cooling_power(self, onoff: str):
        raise NotImplementedError

    @cooling.action
    async def cooling_action(self):
        return 'cooling' if (await self.fetch_value('CoolerPower')) > 0 else 'off'

    async def _gain(self):
        return (await self.parent.get_camera_info())['Gain']
    

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
        return (await self.parent.get_mount_info())['Altitude']
    
    async def _azimuth(self):
        return (await self.parent.get_mount_info())['Azimuth']
    
    async def _right_ascension(self):
        return (await self.parent.get_mount_info())['RightAscension']
    
    async def _declination(self):
        return (await self.parent.get_mount_info())['Declination']
    
    async def _tracking(self):
        return (await self.parent.get_mount_info())['TrackingEnabled']
    
    async def _set_tracking(self, on: bool):
        return await self.parent.set_tracking(on)
  
    async def _track_mode(self):
        return (await self.parent.get_mount_info()).get('TrackingMode', '-')
    
    async def _site_latlon(self):
        info = (await self.parent.get_mount_info())
        return (info['SiteLatitude'], info['SiteLongitude'])
    
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
