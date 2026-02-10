import json
import logging
import aiohttp
import asyncio
import re

from const import DEVICE_TYPE_CAMERA_ICON
from hass_mqtt import mqtt_device, number, sensor, switch
from observatory_software import Camera, Device, FilterWheel, Guider, ObservatorySoftware, Telescope
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
            'guider': NinaGuider(self, 'guider'),
        }
        super().__init__(name)

    @staticmethod
    def create(name: str, **kwargs):
        return Nina(name, **kwargs)


    async def connect(self):
        self.session = aiohttp.ClientSession('http://{0}:{1}/v2/api/'.format(self.host, self.port))
        asyncio.create_task(self.listen_websocket())

    async def listen_websocket(self):
        url = 'ws://{0}:{1}/v2/socket'.format(self.host, self.port)
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
        if 'switch' not in self.devices:
            try:
                switch_info = await self.get_switch_info()
                if switch_info and (switch_info.get('WritableSwitches') or switch_info.get('ReadonlySwitches')):
                    methods = {
                        'get_mqtt_device_config': lambda self: {
                            'name': 'NINA ({0}:{1}) - Switches'.format(self.parent.host, self.parent.port),
                            'model': 'Switches',
                            'manufacturer': 'NINA',
                            'identifiers': [self.uuid()],
                            'suggested_area': 'Observatory',
                        }
                    }

                    def make_getter(prop_name):
                        async def getter(self):
                            return self.get_property(prop_name)
                        return getter

                    def make_setter(s_id, prop_name):
                        async def setter(self, value):
                            await self.parent.set_switch(s_id, value)
                            await self.update_property(prop_name, value, source='push')
                        return setter

                    def get_unit_and_class(name):
                        match = re.search(r'\(([^)]+)\)$', name)
                        if match:
                            unit = match.group(1)
                            if unit == 'V':
                                return ('V', 'voltage')
                            elif unit == 'W':
                                return ('W', 'power')
                            elif unit == '%':
                                return ('%', None)
                            elif unit in ['°', 'C', '°C']:
                                return ('°C', 'temperature')
                            return (unit, None)
                        return (None, None)

                    for sw in switch_info.get('WritableSwitches', []):
                        s_id = sw['Id']
                        s_name = sw['Name']
                        prop_name = f"switch_{s_id}"
                        getter = make_getter(prop_name)
                        getter.__name__ = prop_name
                        
                        if sw.get('Minimum') == 0 and sw.get('Maximum') == 1 and sw.get('StepSize') == 1:
                            comp = switch(name=s_name)(getter)
                        else:
                            unit, dev_class = get_unit_and_class(s_name)
                            kwargs = {
                                'name': s_name,
                                'min': sw.get('Minimum'),
                                'max': sw.get('Maximum'),
                                'step': sw.get('StepSize'),
                                'mode': 'box',
                                'unit_of_measurement': unit,
                                'device_class': dev_class,
                            }
                            if dev_class in ['voltage', 'power']:
                                kwargs['suggested_display_precision'] = 2
                            comp = number(**kwargs)(getter)

                        comp.command(make_setter(s_id, prop_name))
                        methods[prop_name] = comp

                    for sw in switch_info.get('ReadonlySwitches', []):
                        s_id = sw['Id']
                        s_name = sw['Name']
                        prop_name = f"sensor_{s_id}"
                        getter = make_getter(prop_name)
                        getter.__name__ = prop_name
                        unit, dev_class = get_unit_and_class(s_name)
                        
                        kwargs = {
                            'name': s_name,
                            'unit_of_measurement': unit,
                            'device_class': dev_class,
                        }
                        if dev_class in ['voltage', 'power']:
                            kwargs['suggested_display_precision'] = 2
                        comp = sensor(**kwargs)(getter)
                        methods[prop_name] = comp

                    async def fetch_data(self):
                        info = await self.parent.get_switch_info()
                        if not info: return
                        for sw in info.get('WritableSwitches', []) + info.get('ReadonlySwitches', []):
                            prop_name = f"switch_{sw['Id']}"
                            if not hasattr(self, prop_name):
                                prop_name = f"sensor_{sw['Id']}"
                            if hasattr(self, prop_name):
                                await self.update_property(prop_name, sw['Value'])
                    
                    methods['fetch_data'] = fetch_data
                    NinaSwitch = mqtt_device()(type('NinaSwitch', (NinaDevice,), methods))
                    self.devices['switch'] = NinaSwitch(self, 'switch')
            except Exception as e:
                logging.error("Error discovering switches: %s", e)
        return self.devices

    async def poll(self):
        while True:
            for device in list(self.devices.values()):
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

    async def get_guider_info(self):
        return await self._poll('equipment/guider/info')

    async def get_switch_info(self):
        return await self._poll('equipment/switch/info')

    async def set_switch(self, id, value):
        await self._get(f'equipment/switch/{id}', value=json.dumps(value))

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
        await self.parent.set_dewheater(on)
        await self.update_property('dewheater', on, source='push')
    
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
        await self.update_property('cooling_mode', mode, source='push')

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
        await self.parent.set_tracking(on)
        await self.update_property('tracking', on, source='push')
  
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

@mqtt_device()
class NinaGuider(NinaDevice, Guider):
    
    def get_mqtt_device_config(self):
        return {
            'name': 'NINA ({0}:{1}) - Guider'.format(self.parent.host, self.parent.port),
            'model': 'Guider',
            'manufacturer': 'NINA',
            'identifiers': [self.uuid()],
            'suggested_area': 'Observatory',
        }

    async def fetch_data(self):
        info = await self.parent.get_guider_info()
        if not isinstance(info, dict):
            return

        rms = info.get('RMSError')
        if isinstance(rms, dict):
            ra = rms.get('RA')
            if isinstance(ra, dict):
                await self.update_property('ra_distance', ra.get('Arcseconds'))
            
            dec = rms.get('Dec')
            if isinstance(dec, dict):
                await self.update_property('dec_distance', dec.get('Arcseconds'))
            
            total = rms.get('Total')
            if isinstance(total, dict):
                await self.update_property('total_distance', total.get('Arcseconds'))
        
        # Star Mass and SNR are not available in this endpoint
