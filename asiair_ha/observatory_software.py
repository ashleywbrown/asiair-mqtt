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
    
    async def execute_command(cmd: str, payload):
        raise NotImplementedError
    
    async def _update(property: str, payload):
        """ Sends an update on an MQTT topic. """
        raise NotImplementedError

    @staticmethod
    def create(name: str, **kwargs):
        raise NotImplementedError
