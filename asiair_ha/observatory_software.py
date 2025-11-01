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
from const import DEVICE_TYPE_CAMERA_ICON, STATE_CLASS_MEASUREMENT, UNIT_OF_MEASUREMENT_NONE, UNIT_OF_MEASUREMENT_PERCENTAGE, UNIT_OF_MEASUREMENT_SECONDS
from components import camera, climate, sensor, switch


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

class Camera(Device):

    @camera(
        name="Latest Image",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
    ) 
    async def image(self):
        raise NotImplementedError

    @sensor(
        name="Name",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
    ) 
    async def device_name(self):
        return await self._device_name()
    
    async def _device_name(self):
        return NotImplementedError
    
    @sensor(
        name="Cooler Power",
        unit_of_measurement=UNIT_OF_MEASUREMENT_PERCENTAGE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def cooler_power(self):
        return await self._cooler_power()
    
    async def _cooler_power(self):
        raise NotImplementedError

    @sensor(
        name="Gain",
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def gain(self):
        return await self._gain()
    
    async def _gain(self):
        raise NotImplementedError

    
    @sensor(
        name="Exposure",
        unit_of_measurement=UNIT_OF_MEASUREMENT_SECONDS,
        icon=DEVICE_TYPE_CAMERA_ICON,
        state_class=STATE_CLASS_MEASUREMENT,
    ) 
    async def exposure_seconds(self):
        raise NotImplementedError

    @switch(
        name='Dew Heater',
        icon='mdi:heating-coil',
    ) 
    async def dewheater(self):
        return await self._dewheater()
    
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
        raise NotImplementedError

    @cooling.temperature_state
    async def get_cooling_temperature(self):
        raise NotImplementedError

    @cooling.temperature_command
    async def set_cooling_temperature(self, temp):
        raise NotImplementedError

    @cooling.mode_state
    async def cooling_mode(self):
        raise NotImplementedError

    @cooling.mode_command
    async def set_cooling_mode(self, mode: str):
        raise NotImplementedError

    @cooling.power_command
    async def cooling_power(self, onoff: str):
        raise NotImplementedError

    @cooling.action
    async def cooling_action(self):
        raise NotImplementedError
