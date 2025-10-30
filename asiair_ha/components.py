import asyncio
from functools import partial
import json
import logging
import sys
from const import TYPE_CAMERA, TYPE_CLIMATE, TYPE_SENSOR, TYPE_SWITCH


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
                logging.debug("fetching sensor states for %s... %s", state.component_id, topics)
                results = await asyncio.gather(*[fn(self, *args, **kwargs) for (topic, fn) in iterable_topics])
                logging.debug("... found %d", len(results))
                for topic, result in zip(topics, results):
                    logging.error("publish %s - %s - %s", state.component_id, topic, result)
                    if result is None:
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

def switch(**kwargs):
    def switch(func):
        state = component(
            platform=TYPE_SWITCH,
            command_topics=['command'],
            **kwargs)(func)
        return state

    return switch

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