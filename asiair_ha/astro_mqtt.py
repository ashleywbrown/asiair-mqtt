import asyncio

import sys
import logging
from asiair import ZwoAsiair
from mqttpublisher import mqtt_publisher

logging.basicConfig(#filename="./ASIAIR_"+str(sys.argv[2])+".log",
                    #filemode="a",
                    format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S",
                    level=logging.DEBUG)

# get connection details from params
asisair_host  = str(sys.argv[1])
mqtt_host     = str(sys.argv[2])
mqtt_port     = int(sys.argv[3])
mqtt_username     = str(sys.argv[4])
mqtt_password     = str(sys.argv[5])

async def main():
    asiair = ZwoAsiair.create('ASIAIR', address=asisair_host)
    await asiair.connect()
    # remove this interface
    printer = await asyncio.create_task(mqtt_publisher(
        asiair.update_q, asiair.image_available, asiair.cmd_q_4700,
        'asiair', mqtt_host, mqtt_port, mqtt_username, mqtt_password
        ))
    await asiair.discover()
    logging.info("Beginning polling loops...")
    await asiair.poll()
    await printer

asyncio.run(main())