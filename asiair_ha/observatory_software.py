""" Connections to common Astrophotography equipment with an MQTT bridge. """

# This differs to astrolive in that we use push messaging where possible instead
# of polling, and have a cut-down selection of fields.
# 
# We also publish different info depending on the software support.
#
# General algo:
# - initialize persistent connections
# - interrogate software for status
# - register devices via HA device discovery
# - listen to push events with a regular poll
#
# One challenge of abstractions here is that we often end up
# sending multiple updates.

import logging
import time
from const import DEVICE_TYPE_CAMERA_ICON, DEVICE_TYPE_FILTERWHEEL_ICON, DEVICE_TYPE_TELESCOPE_ICON, STATE_CLASS_MEASUREMENT, UNIT_OF_MEASUREMENT_DEGREE, UNIT_OF_MEASUREMENT_NONE, UNIT_OF_MEASUREMENT_PERCENTAGE, UNIT_OF_MEASUREMENT_SECONDS
from hass_mqtt import camera, climate, device_tracker, sensor, switch


class ObservatorySoftware:
    """ Root class for all the devices exposed by a piece of observatory software.
    """
    update = None

    def __init__(self, name):
        self.name = name
        super().__init__()

    async def connect(self):
        """ Set up persistent connections. """
        raise NotImplementedError

    async def discover(self):
        """
        Create device objects needed for MQTT discovery

        When this method is complete, MQTT discovery should
        be able to register devices.

        Device types that are supported by the software but
        not connected should still be registered as unavailable.
        """
        raise NotImplementedError
    
    async def poll(self):
        raise NotImplementedError
    

    @staticmethod
    def create(name: str, **kwargs):
        raise NotImplementedError

class Device:
    """ Root device class which handles MQTT sensor mapping + HA discovery. """
    def __init__(self, parent: ObservatorySoftware, name: str):
        self.parent = parent
        self.name = name
        self._cache = {}
        self._last_push = {}
        super().__init__()

    def components(self):
        components = []
        for attr_name in dir(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'component_config'):
                components.append(method)
        return components

    def uuid(self):
        raise NotImplementedError

    def get_mqtt_device_config(self):
        raise NotImplementedError

    def get_property(self, name):
        return self._cache.get(name)

    async def update_property(self, name, value, source='poll'):
        now = time.time()
        if source == 'push':
            self._last_push[name] = now
        elif source == 'poll':
            last = self._last_push.get(name, 0)
            if now - last < 1.0:
                return # Suppress poll update if push was recent

        self._cache[name] = value
        
        if hasattr(self, name):
            component = getattr(self, name)
            if hasattr(component, 'publish'):
                await component.publish(self)

    async def fetch_data(self):
        """ Fetches data for all pollable properties and updates the cache. """
        pass

    async def _try_fetch(self, name, func):
        try:
            await self.update_property(name, await func())
        except NotImplementedError:
            pass
        except Exception as e:
            logging.error(f"Error fetching {name} for {self.name}: {e}")

class Camera(Device):

    @camera(
        name="Latest Image",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
    ) 
    async def image(self):
        return self.get_property('image')
    
    async def _image(self):
        raise NotImplementedError

    @sensor(
        name="Name",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
    ) 
    async def device_name(self):
        return self.get_property('device_name')
    
    async def _device_name(self):
        return NotImplementedError
    
    @sensor(
        name="Cooler Power",
        unit_of_measurement=UNIT_OF_MEASUREMENT_PERCENTAGE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def cooler_power(self):
        return self.get_property('cooler_power')
    
    async def _cooler_power(self):
        raise NotImplementedError

    @sensor(
        name="Gain",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def gain(self):
        return self.get_property('gain')
    
    async def _gain(self):
        raise NotImplementedError

    
    @sensor(
        name="Exposure",
        unit_of_measurement=UNIT_OF_MEASUREMENT_SECONDS,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def exposure_seconds(self):
        return self.get_property('exposure_seconds')
    
    async def _exposure_seconds(self):
        raise NotImplementedError

    @switch(
        name='Dew Heater',
        icon='mdi:heating-coil',
    ) 
    async def dewheater(self):
        return self.get_property('dewheater')
    
    async def _dewheater(self):
        raise NotImplementedError

    @dewheater.command
    async def set_dewheater(self, value):
        return await self._set_dewheater(value)
    
    async def _set_dewheater(self, value):
        raise NotImplementedError

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
        return self.get_property('cooling')
    
    async def _cooling_current_temperature(self):
        raise NotImplementedError

    @cooling.temperature_state
    async def get_cooling_temperature(self):
        return self.get_property('get_cooling_temperature')
    
    async def _cooling_target_temperature(self):
        raise NotImplementedError

    @cooling.temperature_command
    async def set_cooling_temperature(self, temp):
        return await self._set_cooling_target_temperature(temp)
    
    async def _set_cooling_target_temperature(self, temp):
        raise NotImplementedError

    @cooling.mode_state
    async def cooling_mode(self):
        return self.get_property('cooling_mode')
    
    async def _cooling_mode(self):
        raise NotImplementedError

    @cooling.mode_command
    async def set_cooling_mode(self, mode: str):
        return await self._set_cooling_mode(mode)
    
    async def _set_cooling_mode(self, mode: str):
        raise NotImplementedError

    @cooling.power_command
    async def cooling_power(self, onoff: str):
        return await self._set_cooling_power(onoff)
    
    async def _set_cooling_power(self, onoff: str):
        raise NotImplementedError

    @cooling.action
    async def cooling_action(self):
        return self.get_property('cooling_action')
    
    async def _cooling_action(self):
        raise NotImplementedError

    async def fetch_data(self):
        await self._try_fetch('device_name', self._device_name)
        await self._try_fetch('cooler_power', self._cooler_power)
        await self._try_fetch('gain', self._gain)
        await self._try_fetch('exposure_seconds', self._exposure_seconds)
        await self._try_fetch('dewheater', self._dewheater)
        await self._try_fetch('cooling', self._cooling_current_temperature)
        await self._try_fetch('get_cooling_temperature', self._cooling_target_temperature)
        await self._try_fetch('cooling_mode', self._cooling_mode)
        await self._try_fetch('cooling_action', self._cooling_action)
        # Image is typically pushed, not polled

class Telescope(Device):
    @sensor(
        name="Altitude",
        unit_of_measurement=UNIT_OF_MEASUREMENT_DEGREE,
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
        suggested_display_precision=3,
    ) 
    async def altitude(self):
        return self.get_property('altitude')
    
    async def _altitude(self):
        raise NotImplementedError
    
    @sensor(
        name="Azimuth",
        unit_of_measurement=UNIT_OF_MEASUREMENT_DEGREE,
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
        suggested_display_precision=3,
    ) 
    async def azimuth(self):
        return self.get_property('azimuth')
    
    async def _azimuth(self):
        raise NotImplementedError

    @sensor(
        name="Right Ascension",
        unit_of_measurement=UNIT_OF_MEASUREMENT_DEGREE,
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
        suggested_display_precision=3,
    ) 
    async def right_ascension(self):
        return self.get_property('right_ascension')
    
    async def _right_ascension(self):
        raise NotImplementedError
    
    @sensor(
        name="Declination",
        unit_of_measurement=UNIT_OF_MEASUREMENT_DEGREE,
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
        suggested_display_precision=3,
    ) 
    async def declination(self):
        return self.get_property('declination')
    
    async def _declination(self):
        raise NotImplementedError
    
    @sensor(
        name="Track Mode",
        icon=DEVICE_TYPE_TELESCOPE_ICON,
    ) 
    async def track_mode(self):
        return self.get_property('track_mode')
    
    async def _track_mode(self):
        raise NotImplementedError
    
    @switch(
        name="Tracking",
        icon=DEVICE_TYPE_TELESCOPE_ICON,
    ) 
    async def tracking(self):
        return self.get_property('tracking')
    
    @tracking.command
    async def set_tracking(self, on: bool):
        return await self._set_tracking(on)
    
    @tracking.json_attributes
    async def tracking_attributes(self):
        return self.get_property('tracking_attributes')

    async def _tracking(self):
        raise NotImplementedError
    
    async def _set_tracking(self):
        raise NotImplementedError
    
    async def _tracking_attributes(self):
        return {
            'Mode': await self._track_mode()
        }
    
    @device_tracker(
        name='Site Location',
        icon=DEVICE_TYPE_TELESCOPE_ICON,
        subscription_topics=['json_attributes'],
    )
    async def site_location(self):
        return self.get_property('site_location')
    
    async def _site_latlon(self):
        raise NotImplementedError

    async def fetch_data(self):
        await self._try_fetch('altitude', self._altitude)
        await self._try_fetch('azimuth', self._azimuth)
        await self._try_fetch('right_ascension', self._right_ascension)
        await self._try_fetch('declination', self._declination)
        await self._try_fetch('track_mode', self._track_mode)
        await self._try_fetch('tracking', self._tracking)
        await self._try_fetch('tracking_attributes', self._tracking_attributes)
        
        try:
            location = await self._site_latlon()
            await self.update_property('site_location', {
                'latitude': location[0],
                'longitude': location[1],
            })
        except:
            pass

class FilterWheel(Device):
    @sensor(
        name="Current",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_FILTERWHEEL_ICON,
        unique_id='1236qw345h6'
    ) 
    async def current(self):
        return self.get_property('current')
    
    async def _current(self):
        raise NotImplementedError

    async def fetch_data(self):
        await self._try_fetch('current', self._current)
