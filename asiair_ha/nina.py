import json
import logging
import aiohttp
import asyncio

from const import DEVICE_TYPE_CAMERA_ICON
from hass_mqtt import climate, mqtt_device, sensor
from observatory_software import Camera, Device, ObservatorySoftware


class Nina(ObservatorySoftware):
    def __init__(self, name, host='localhost', port='1888'):
        self.host = host
        self.port = port
        self.session = None
        self.devices = {
            'camera': NinaCamera(self, 'camera')
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
    
    async def _get(self, path, **kwargs):
        async with self.session.get(path, params=kwargs) as response:
            print(response)
            print("Status:", response.status)
            print("Content-type:", response.headers['content-type'])
            json = await response.json()
            return json['Response']

    async def get_camera_info(self):
        return await self._get('equipment/camera/info')

    async def set_dewheater(self, on: bool):
        await self._get('equipment/camera/dew-heater', power=json.dumps(on))
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
    
    async def _device_name(self):
        return (await self.parent.get_camera_info())['Name']

    async def _cooler_power(self):
        return (await self.parent.get_camera_info())['CoolerPower']
    
    async def _dewheater(self):
        return (await self.parent.get_camera_info())['DewHeaterOn']

    async def _set_dewheater(self, on):
        return await self.parent.set_dewheater(on)


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
        return (await self.parent.get_camera_info())['Temperature']

    @cooling.temperature_state
    async def get_cooling_temperature(self):
        return (await self.parent.get_camera_info())['TargetTemp']

    @cooling.temperature_command
    async def set_cooling_temperature(self, temp):
        raise NotImplementedError

    @cooling.mode_state
    async def cooling_mode(self):
        return 'cool' if (await self.parent.get_camera_info())['CoolerOn'] else 'off'

    @cooling.mode_command
    async def set_cooling_mode(self, mode: str):
        raise NotImplementedError

    @cooling.power_command
    async def cooling_power(self, onoff: str):
        raise NotImplementedError

    @cooling.action
    async def cooling_action(self):
        return 'cooling' if (await self.parent.get_camera_info())['CoolerOn'] else 'off'

    async def _gain(self):
        return (await self.parent.get_camera_info())['Gain']