import asyncio
from collections import namedtuple
import json
import logging
import math
import sys
import traceback

import aiohttp
import numpy as np
from numpy import arcsin, arctan2
from components import number, text
from observatory_software import Device, ObservatorySoftware

AltAz = namedtuple('AltAz', ['alt', 'az'])

class Stellarium(ObservatorySoftware):
    def __init__(self, name, host='localhost', port='8090'):
        self.host = host
        self.port = port
        self.session = None
        self.devices = {
            'planetarium': Planetarium(self, 'planetarium')
        }
        super().__init__(name)

    @staticmethod
    def create(name: str, **kwargs):
        return Stellarium(name, **kwargs)


    async def connect(self):
        self.session = aiohttp.ClientSession('http://{0}:{1}/api/'.format(self.host, self.port))

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
            return await response.json()

    async def _post(self, path, **kwargs):
        async with self.session.post(path, params=kwargs) as response:
            print(response)
            print("Status:", response.status)
            print("Content-type:", response.headers['content-type'])

    async def get_view(self):
        return await self._get('main/view')
    
    async def get_alt_az(self):
        all = await self.get_view()
        try:
            vector = np.array(json.loads(all['altAz']))
            mag = np.linalg.norm(vector)
            (x, y, z) = vector / mag
            alt = np.rad2deg(arcsin(z))
            azp = np.rad2deg(arctan2(y, x))
            az = 180 - azp
            alt = np.round(alt, 5)
            az = np.round(az, 5)
            return (alt, az)
        except Exception as ex:
            logging.error(traceback.format_exc())
            raise

    async def set_alt_az(self, alt=None, az=None) -> None:
        altaz = {}
        if alt is not None:
            altaz['alt'] = np.deg2rad(alt)
        if az is not None:
            altaz['az'] = np.deg2rad(180-float(az))
        await self._post('main/view', **altaz)
    
class Planetarium(Device):
    def __init__(self, parent: Stellarium, name):
        super().__init__(parent, name)

    def uuid(self):
        return '_'.join([self.parent.host, self.parent.port, self.parent.name, self.name])
    
    def get_mqtt_device_config(self):
        return {
            'name': 'Stellarium ({0}:{1}) - Planetarium'.format(self.parent.host, self.parent.port),
            'model': 'Planetarium',
            'manufacturer': 'Stellarium',
            'identifiers': [self.uuid()],
            'suggested_area': 'Observatory',
        }
    
    @text(
            name='Altitude',
    )
    async def altitude(self):
        return (await self.parent.get_alt_az())[0]
    
    @altitude.command
    async def set_altitude(self, alt: float):
        return (await self.parent.set_alt_az(alt=alt))

    @text(
            name='Azimuth',
    )
    async def azimuth(self):
        return (await self.parent.get_alt_az())[1]

    @azimuth.command
    async def set_azimuth(self, az: float):
        return (await self.parent.set_alt_az(az=az))
