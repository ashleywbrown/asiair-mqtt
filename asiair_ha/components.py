import logging
from const import TYPE_SENSOR


def sensor(**kwargs):
    def sensor(func):
        def get_wrapper(self, *args, **kwargs):
            return func(self, *args, **kwargs)
        
        # Event handler - set by main code.
        get_wrapper.on_publish = None
        
        async def publish(self, *args, **kwargs):
            logging.debug("call on_publish")
            result = await func(self, *args, **kwargs)
            get_wrapper.on_publish(get_wrapper, result)

        def set_on_publish(func):
            logging.debug("set_on_publish")
            get_wrapper.on_publish = func

        get_wrapper.publish = publish
        get_wrapper.set_on_publish = set_on_publish

        get_wrapper.component_id = func.__name__
        get_wrapper.component_config = kwargs
        get_wrapper.component_config['platform'] = TYPE_SENSOR
        return get_wrapper
    return sensor
