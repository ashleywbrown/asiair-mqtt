import asyncio

from functools import partial
import json
import sys
import logging
import paho.mqtt.client as mqtt

from asiair import ZwoAsiair
from const import DEVICE_CLASS_NONE, STATE_CLASS_NONE, TYPE_SENSOR, TYPE_SWITCH, UNIT_OF_MEASUREMENT_NONE
from mqttpublisher import mqtt_publisher, sensor_publisher


logging.basicConfig(#filename="./ASIAIR_"+str(sys.argv[2])+".log",
                    #filemode="a",
                    format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S",
                    level=logging.DEBUG,
                    force=True)

# get connection details from params
asiair_host  = str(sys.argv[1])
mqtt_host     = str(sys.argv[2])
mqtt_port     = int(sys.argv[3])
mqtt_username     = str(sys.argv[4])
mqtt_password     = str(sys.argv[5])

async def command_router(cmd_q: asyncio.Queue):
    while True:
        try:
            (device, component, topic, fn, payload) = await cmd_q.get()
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = payload.decode() # just use the string
            new_value = await fn(device, payload)
            if new_value is not None:
                component.on_publish(component, topic, new_value)
        except Exception as ex:
            logging.error(ex)

async def main():
    cmd_q = asyncio.Queue()
    connections = {
        'asiair': ZwoAsiair.create('ASIAIR', address=asiair_host)
    }
    for name, cnx in connections.items():
        # We run this sequentially as parallel connection creation
        # creates messy logs which are hard to debug.
        logging.info('Opening connections for "%s"', name)
        await cnx.connect()

    # Setup MQTT.
    def on_message(client, connections, message: mqtt.MQTTMessage):
        (connection_name, suffix) = message.topic.split('/', 1)

        cnx = connections[connection_name]
        cmd_q_4700 = cnx.cmd_q_4700
        if (cmd_q_4700):
            logging.debug(">>>>>>>>>>> %s: %s", message.topic, message.payload)
            if suffix == "set_control_value/cmd":
                cmd_q_4700.put_nowait(("set_control_value", json.loads(message.payload)))

    logging.info("Connecting MQTT: %s : %d", mqtt_host, mqtt_port)
    clientMQTT = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, userdata=connections)
    if mqtt_username and mqtt_password:
        clientMQTT.username_pw_set(username=mqtt_username, password=mqtt_password)
    clientMQTT.connect(mqtt_host, mqtt_port, 60)
    clientMQTT.on_message = on_message
    clientMQTT.loop_start()
    log = logging.getLogger(__name__)
    log.info("Starting MQTT publisher")
    publisher = asyncio.create_task(mqtt_publisher(
        clientMQTT,
        connections['asiair'].update_q,
        'asiair'))
    logging.info("Discovering devices...")

    all_devices = []
    for cnx_name, cnx in connections.items():
        device_list = await cnx.discover()
        for device in device_list.values():
            all_devices.append((cnx_name, device))

    for (cnx_name, device) in all_devices:
        dv = device.get_mqtt_device_config()
        discovery_topic = 'homeassistant/device/asiair/asiair/config' # remove hard coding
        components = {}
        for component in device.components():
            config = component.component_config
            component_root_topic = '{cnx_name}/{device_name}/{component_id}'.format(cnx_name=cnx_name, device_name=device.name, component_id=component.component_id)

            for topic in component.subscription_topic_map.keys():
                if topic == '':
                    config['topic'] = component_root_topic
                else:
                    config[topic + '_topic'] = component_root_topic + '/' + topic

            def callback(client, userdata, message, device, component, topic, fn, cmd_q):
                logging.debug('Callback for %s %s %s %s', device.name, topic, fn, message.payload)
                cmd_q.put_nowait((device, component, topic, fn, message.payload))

            for topic, fn in component.command_topic_map.items():
                command_topic = component_root_topic + '/' + topic
                config[topic + '_topic'] = command_topic

                clientMQTT.subscribe(command_topic)
                topic_callback = partial(callback, device=device, component=component, topic=command_topic, fn=fn, cmd_q=cmd_q)
                topic_callback.__name__ = 'partial'
                clientMQTT.message_callback_add(
                    command_topic,
                    topic_callback
                    )
            
            components[component.component_id] = config
            component.set_on_publish(lambda component, topic, payload, root_topic=component_root_topic: clientMQTT.publish(root_topic + ('' if topic == '' else '/' + topic ), payload, qos=1))
        logging.debug(' Registering components %s', components)
        
        discovery_payload = {
            'dev': dv,
            'o': {
                'name': 'AstroMQTT',
                'sw_version': '0.1',
                'support_url': 'https://github.com/ashleywbrown/asiair-mqtt',
            },
            'cmps': components,
            'state_topic': 'asiair/pi_get_info', # Can add a better topic here.
            
        }
        clientMQTT.publish(discovery_topic, json.dumps(discovery_payload), qos=0, retain=True)
    
    polling = list(map(lambda cnx: cnx.poll(), connections.values()))
    logging.info("Starting... %d", len(polling))
    await connections['asiair'].poll()
    await asyncio.gather(command_router(cmd_q), publisher, *polling)

asyncio.run(main())