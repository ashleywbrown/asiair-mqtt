import logging
import json
import asyncio
import paho.mqtt.client as mqtt
import time

from asiair import CAMERA_COMMANDS_4700

from const import DEVICE_CLASS_SWITCH, DEVICE_TYPE_ASIAIR, DEVICE_TYPE_CAMERA, DEVICE_TYPE_CAMERA_FILE, DEVICE_TYPE_FILTERWHEEL, DEVICE_TYPE_FOCUSER, DEVICE_TYPE_TELESCOPE, FUNCTIONS, SENSOR_DEVICE_CLASS, SENSOR_EXTRA_FIELDS, SENSOR_ICON, SENSOR_NAME, SENSOR_STATE_CLASS, SENSOR_STATE_TOPIC, SENSOR_TYPE, SENSOR_UNIT, SENSOR_VALUE_TEMPLATE, TYPE_CLIMATE

def mqtt_publish(mqtt, root_topic, type, message):
    logging.debug(root_topic + " -> " + type + "->" + str(json.dumps(message)))
    y = mqtt.publish(root_topic + "/" + type, str(json.dumps(message)), retain=True)

async def mqtt_publisher(clientMQTT, q, mqtt_root_topic):
    # Set up MQTT Home Assistant config.
    try:
        asyncio.create_task(create_mqtt_config(clientMQTT, "asiair.asiair", DEVICE_TYPE_ASIAIR, "ASIAIR", FUNCTIONS[DEVICE_TYPE_ASIAIR]))
        asyncio.create_task(create_mqtt_config(clientMQTT, "asiair.telescope", DEVICE_TYPE_TELESCOPE, "Telescope", FUNCTIONS[DEVICE_TYPE_TELESCOPE]))
    except Exception as e:
        logging.debug(e)
        raise
    while True:
        try:
            message = await q.get()
            if isinstance(message, bytearray):
                mqttMsg = clientMQTT.publish("asiair/image/latestImage", message, qos=1, retain=True)
                print("Waiting to publish image...")
                mqttMsg.wait_for_publish()
                print("... done")
            else:
                x = message
                try:
                    message['utime'] = int(time.time())
                    if "method" in message and message["code"] == 0:
                        if message["method"] == "get_control_value":
                            message["method"] = str(message["result"]["name"]).lower()

                    if "Event" in message:
                        mqtt_publish(clientMQTT, mqtt_root_topic, message["Event"], message)
                    elif "method" in message and message["code"] == 0:
                        mqtt_publish(clientMQTT, mqtt_root_topic, message["method"], message["result"])
                    else:
                        logging.error("Unknown response: %s", str(x))
                except Exception as ex:
                    logging.debug("Failed: %s", ex)
            q.task_done()
        except Exception as ex:
            logging.error(">>>>>><<<<<<<< FAILED: %s", ex)

async def sensor_publisher(clientMQTT, sensors):
    while True:
        for (topic, device, method) in sensors:
            payload = await method()
            logging.debug('Publishing %s => %s', topic, payload)
            clientMQTT.publish(topic, payload, qos=1)
        await asyncio.sleep(20)


async def create_mqtt_config(mqtt, sys_id, device_type, device_friendly_name, device_functions):
    """Creates configuration topics within the homeassistant sensor and camera topics.

    Args:
        sys_id (string): ID of the device.
        device_type (string): Type of the device.
        device_friendly_name (string): Friendly name of the device.
        device_functions (list): List of functions provided by the device.

    Returns:
        True if thread is alive
    """

    logging.debug("Creating MQTT Config for a %s", device_type)
    logging.debug("  Friendly name %s", device_friendly_name)
    logging.debug("  Functions %s", device_functions)

    sys_id_ = sys_id.replace(".", "_")
    device_friendly_name_cap = device_friendly_name
    device_friendly_name_low = device_friendly_name.lower().replace(" ", "_")

    for function in device_functions:
        # Generic for all devices one configuration topic for each functionality
        device_function_cap = function[SENSOR_NAME]
        device_function_low = function[SENSOR_NAME].lower().replace(" ", "_")

        root_topic = (
            "homeassistant/"
            + function[SENSOR_TYPE]
            + "/asiair/"
            + device_friendly_name_low
            + "_"
            + device_function_low
            + "/"
        )
        config = {
            "name": device_function_cap,
            "state_topic": function[SENSOR_STATE_TOPIC], # set the correct host
            "state_class": function[SENSOR_STATE_CLASS],
            "device_class": function[SENSOR_DEVICE_CLASS],
            "icon": function[SENSOR_ICON],
            #"availability_topic": "astrolive/" + device_type + "/" + sys_id_ + "/lwt",
            #"payload_available": "ON",
            #"payload_not_available": "OFF",
            #"payload_on": STATE_ON,
            #"payload_off": STATE_OFF,
            "unique_id": device_type + "_" + sys_id_ + "_" + device_function_low,
            "value_template": function[SENSOR_VALUE_TEMPLATE],
            #"suggested_display_precision": 2,
            "device": {
                "identifiers": [sys_id],
                "name": "ASIAIR " + device_friendly_name_cap,
                "model": device_friendly_name_cap,
                "manufacturer": "ASIAIR-MQTT Bridge",
            },
        }
        if len(function) >= SENSOR_EXTRA_FIELDS + 1:
            config.update(function[SENSOR_EXTRA_FIELDS])

        if function[SENSOR_UNIT] != "" and function[SENSOR_UNIT] is not None:
            config["unit_of_measurement"] = function[SENSOR_UNIT]

        #if function[SENSOR_TYPE] == TYPE_TEXT:
        #    config["command_topic"] = ("astrolive/" + device_type + "/" + sys_id_ + "/cmd",)

        if function[SENSOR_DEVICE_CLASS] == DEVICE_CLASS_SWITCH:
            logging.debug("Device friendly name %s", device_function_low)
            if device_function_low == "dew_heater_on":
                config["command_topic"] = "asiair/set_control_value/cmd"
                config["command_template"] = "[\"AntiDewHeater\", {% if value == 'ON' %}1{% else %}0{% endif %}]"
                mqtt.subscribe("asiair/set_control_value/cmd")
            
        #    config["command_topic"] = (
        #        "astrolive/" + device_type + "/" + sys_id_ + "/set" + "_" + device_function_low
        #    )
        #    # Subscribe to command topic of the switch
        #    await self._publisher.subsribe_mqtt(
        #        "astrolive/" + device_type + "/" + sys_id_ + "/set" + "_" + device_function_low
        #    )

        mqtt.publish(root_topic + "config", json.dumps(config), qos=0, retain=True)

    logging.debug("Published MQTT Config for a %s", device_type)
    return None