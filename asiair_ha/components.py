import asyncio
from functools import partial
import logging
from const import TYPE_CLIMATE, TYPE_SENSOR, TYPE_SWITCH


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
            logging.debug("call on_publish")
            iterable_topics = [(topic, fn) for topic, fn in state.subscription_topic_map.items()]
            topics = [topic for topic, fn in iterable_topics ]
            results = await asyncio.gather(*[fn(self, *args, **kwargs) for (topic, fn) in iterable_topics])
            for topic, result in zip(topics, results):
                state.on_publish(state, topic, result)

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
            subscription_topics=['temperature_state', 'mode_state'],
            command_topics=['temperature_command', 'mode_command', 'power_command'],
            **kwargs)(func)
        
        return state
    return climate
