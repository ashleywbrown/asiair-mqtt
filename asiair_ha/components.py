import asyncio
from functools import partial
import json
import logging
import sys
from const import DEVICE_CLASS_SWITCH, STATE_CLASS_NONE, TYPE_BINARY_SENSOR, TYPE_CAMERA, TYPE_CLIMATE, TYPE_DEVICE_TRACKER, TYPE_NUMBER, TYPE_SENSOR, TYPE_SWITCH, TYPE_TEXT, UNIT_OF_MEASUREMENT_NONE

class MqttDevice():
    '''Çlass decorator for a device that will be published via MQTT'''
    def __init__(self):
        pass

    def __call__(self):
        pass

    # Read through all attributes of the class.
    # Add fields and functions for setting the root topic.

    def set_device_topic(topic: str):
        '''Set the root topic for this device - used when publishing.'''

    def publish(component_fn: function):
        '''Publish the value of the associated function to its MQTT topic.'''

def component(
        platform=TYPE_SENSOR,
        subscription_topics=['state', 'json_attributes'], 
        command_topics=[],
        **kwargs):
    def component(func):
        def state(self, *args, **kwargs):
            return func(self, *args, **kwargs)
        
        # Event handler - set by main code.
        state.on_publish = None
        
        # TODO: Move this to a set of helper functions to remove asyncio in this module.
        async def publish(self, *args, **kwargs):
            try:
                iterable_topics = [(topic, fn) for topic, fn in state.subscription_topic_map.items()]
                topics = [topic for topic, fn in iterable_topics ]
                results = await asyncio.gather(
                    *[fn(self, *args, **kwargs) for (topic, fn) in iterable_topics],
                    return_exceptions=True)
                for topic, result in zip(topics, results):
                    logging.error("publish %s - %s - %s", state.component_id, topic, result)
                    if result is None or isinstance(result, NotImplementedError):
                        continue
                    if isinstance(result, Exception):
                        logging.error('Error retrieving value for %s %s', state.component_id, result)
                        continue
                    if not isinstance(result, str) and not isinstance(result, bytearray):
                        result = json.dumps(result)
                    state.on_publish(state, topic, result)
            except Exception as ex:
                logging.error(ex)
                sys.exit(-1)
        def set_on_publish(func):
            logging.debug("set_on_publish")
            state.on_publish = func

        state.publish = publish
        state.set_on_publish = set_on_publish

        state.subscription_topic_map = {}
        state.command_topic_map = {}

        def topic_setter(func, topic_map, topic):
            topic_map[topic] = func
            logging.error('%s', topic_map)
            return func
        
        if len(subscription_topics) > 0:
            state.subscription_topic_map[subscription_topics[0]] = state
        for topic_map, topics in [
            (state.subscription_topic_map, subscription_topics[1:]),
            (state.command_topic_map, command_topics)]:
            for topic in topics:
                setattr(state, topic, partial(topic_setter, topic_map=topic_map, topic=topic))

        state.component_id = func.__name__
        state.component_config = kwargs
        state.component_config['platform'] = platform
        return state
    return component

def sensor(**kwargs):
    return component(platform=TYPE_SENSOR, **kwargs)

def binary_sensor(
        value_template='{% if value_json == false %}OFF{% else %}ON{% endif %}',
        **kwargs):
    def binary_sensor(func):
        state = component(
            platform=TYPE_BINARY_SENSOR,
            value_template=value_template,
            **kwargs)(func)
        
        return state
    return binary_sensor

def switch(
        device_class=DEVICE_CLASS_SWITCH,
        unit_of_measurement=UNIT_OF_MEASUREMENT_NONE,
        state_class=STATE_CLASS_NONE,
        value_template='{% if value_json == false %}OFF{% else %}ON{% endif %}',
        command_template='{% if value == "OFF" %}false{% else %}true{% endif %}',
        **kwargs):
    def switch(func):
        state = component(
            platform=TYPE_SWITCH,
            command_topics=['command'],
            device_class=device_class,
            state_class=state_class,
            unit_of_measurement=unit_of_measurement,
            value_template=value_template,
            command_template=command_template,
            **kwargs)(func)
        return state
    return switch

def number(**kwargs):
    def number(func):
        state = component(
            platform=TYPE_NUMBER,
            command_topics=['command'],
            **kwargs
        )(func)
        return state
    return number

def text(**kwargs):
    def number(func):
        state = component(
            platform=TYPE_TEXT,
            command_topics=['command'],
            **kwargs
        )(func)
        return state
    return number

def climate(**kwargs):
    def climate(func):
        state = component(
            platform=TYPE_CLIMATE,
            subscription_topics=['current_temperature', 'temperature_state', 'mode_state', 'action', 'json_attributes'],
            command_topics=['temperature_command', 'mode_command', 'power_command'],
            **kwargs)(func)
        
        return state
    return climate

def camera(**kwargs):
    def camera(func):
        state = component(
            platform=TYPE_CAMERA,
            subscription_topics=['', 'json_attributes'],
            **kwargs)(func)
        
        return state
    return camera

def device_tracker(**kwargs):
    def device_tracker(func):
        state = component(
            platform=TYPE_DEVICE_TRACKER,
            **kwargs)(func)
        
        return state
    return device_tracker