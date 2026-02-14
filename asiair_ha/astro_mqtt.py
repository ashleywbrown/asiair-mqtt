import asyncio

import argparse
from functools import partial
import json
import sys
import os
import logging
import traceback
import yaml
import paho.mqtt.client as mqtt

from asiair import ZwoAsiair
from nina import Nina
from stellarium import Stellarium

logging.basicConfig(#filename="./ASIAIR_"+str(sys.argv[2])+".log",
                    #filemode="a",
                    format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S",
                    level=logging.DEBUG,
                    force=True)

async def command_router(cmd_q: asyncio.Queue):
    while True:
        try:
            (device, component, topic, fn, payload) = await cmd_q.get()
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = payload.decode() # just use the string
            try:
                new_value = await fn(device, payload)
                if new_value is not None:
                    device.on_publish(component, topic, new_value)
            except NotImplementedError:
                logging.error('Not implemented - command for "%s"', topic)
            cmd_q.task_done()
        except Exception as ex:
            logging.error(traceback.format_exc())

async def register_devices(cnx_name, cnx, clientMQTT, cmd_q):
    logging.info(f"Discovering devices for {cnx_name}...")
    try:
        device_list = await cnx.discover()
    except Exception as e:
        logging.error(f"Discovery failed for {cnx_name}: {e}")
        return

    for device in device_list.values():
        dv = device.get_mqtt_device_config()
        discovery_topic = 'homeassistant/device/astro_mqtt/{0}/config'.format(cnx_name) # remove hard coding
        logging.debug(type(device).__name__ + ': ' + str(dv))
        components = {}
        #for component in device.components():
        device_root_topic = '{cnx_name}/{device_name}'.format(cnx_name=cnx_name, device_name=device.name)

        for component in device.mqtt_components:
            config = component.component_config
            component_root_topic = '{device_root_topic}/{component_id}'.format(device_root_topic=device_root_topic, component_id=component.component_id)

            for topic in component.subscription_topic_map.keys():
                if topic == '':
                    config['topic'] = component_root_topic
                else:
                    config[topic + '_topic'] = component_root_topic + '/' + topic
                logging.debug('Registering: ' + type(device).__name__ + ': ' + topic)

            def callback(client, userdata, message, device, component, topic, fn, cmd_q):
                logging.debug('Callback for %s %s %s %s', device.name, topic, fn, message.payload)
                cmd_q.put_nowait((device, component, topic, fn, message.payload))

            for topic, fn in component.command_topic_map.items():
                command_topic = component_root_topic + '/' + topic
                config[topic + '_topic'] = command_topic
                logging.info('Subscribing to %s for %s', command_topic, component.component_id)

                clientMQTT.subscribe(command_topic)
                topic_callback = partial(callback, device=device, component=component, topic=command_topic, fn=fn, cmd_q=cmd_q)
                topic_callback.__name__ = 'partial'
                clientMQTT.message_callback_add(
                    command_topic,
                    topic_callback
                    )
            
            config['unique_id'] = '{0}.{1}.{2}'.format(cnx_name, device.uuid(), component.component_id)
            components[component.component_id] = config
        
        def on_publish(mqtt_component, topic, payload, device_root_topic):
            clientMQTT.publish(device_root_topic + '/' + mqtt_component.component_id + ('' if topic == '' else '/' + topic ), payload, qos=1)
        device.on_publish = partial(on_publish, device_root_topic=device_root_topic)
        
        discovery_payload = {
            'dev': dv,
            'o': {
                'name': 'AstroMQTT',
                'sw_version': '0.1',
                'support_url': 'https://github.com/ashleywbrown/asiair-mqtt',
            },
            'cmps': components,
        }
        logging.debug(' Registering device %s', discovery_payload)
        clientMQTT.publish(discovery_topic, json.dumps(discovery_payload), qos=0, retain=True)

async def main():
    parser = argparse.ArgumentParser(description='AstroMQTT Bridge')
    parser.add_argument('--config', default='default.cfg', help='Path to configuration file')
    parser.add_argument('--mqtt-host', help='MQTT Broker Host')
    parser.add_argument('--mqtt-port', type=int, help='MQTT Broker Port')
    parser.add_argument('--mqtt-username', help='MQTT Username')
    parser.add_argument('--mqtt-password', help='MQTT Password')
    
    args = parser.parse_args()

    # Load Config
    config = {}
    config_path = args.config
    if not os.path.isabs(config_path):
        # Try relative to CWD first, then relative to script
        if not os.path.exists(config_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            potential_path = os.path.join(script_dir, config_path)
            if os.path.exists(potential_path):
                config_path = potential_path

    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            try:
                config = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                logging.error(f"Error parsing config file: {exc}")
    else:
        logging.warning(f"Config file {config_path} not found. Using defaults/command line args.")

    # MQTT Config
    mqtt_cfg = config.get('mqtt', {})
    mqtt_host = args.mqtt_host or mqtt_cfg.get('host') or 'localhost'
    mqtt_port = args.mqtt_port or mqtt_cfg.get('port') or 1883
    mqtt_username = args.mqtt_username or mqtt_cfg.get('username')
    mqtt_password = args.mqtt_password or mqtt_cfg.get('password')

    cmd_q = asyncio.Queue()
    connections = {}
    
    connections_cfg = config.get('connections', {})
    
    for name, cfg in connections_cfg.items():
        ctype = cfg.pop('type', None)
        if ctype == 'asiair':
            connections[name] = ZwoAsiair.create(name, **cfg)
        elif ctype == 'nina':
            connections[name] = Nina.create(name, **cfg)
        elif ctype == 'stellarium':
            connections[name] = Stellarium.create(name, **cfg)
        else:
            logging.warning(f"Unknown connection type '{ctype}' for '{name}'")

    for name, cnx in connections.items():
        logging.info('Opening connections for "%s"', name)
        await cnx.connect()

    logging.info("Connecting MQTT: %s : %d", mqtt_host, mqtt_port)
    clientMQTT = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, userdata=connections)
    if mqtt_username and mqtt_password:
        clientMQTT.username_pw_set(username=mqtt_username, password=mqtt_password)
    clientMQTT.connect(mqtt_host, mqtt_port, 60)
    clientMQTT.loop_start()
    logging.info("Discovering devices...")
    
    tasks = [command_router(cmd_q)]
    for cnx_name, cnx in connections.items():
        tasks.append(cnx.poll())
        tasks.append(register_devices(cnx_name, cnx, clientMQTT, cmd_q))
    
    logging.info("Starting main loop...")
    await asyncio.gather(*tasks)

asyncio.run(main())