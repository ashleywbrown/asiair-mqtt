# asiair-homeassistant
An MQTT bridge between the ZWO ASIAIR and Home Assistant.

This is still a prototype, with very messy code, but kept on GitHub for versioning and back up!

This is inspired (and borrows some code from) both [astrolive](https://github.com/mawinkler/astrolive) and [ASIAIRstatus](https://github.com/frankhirsch/ASIAIRstatus). I did experiment with creating a new connection type in astrolive, but it's very focused around the Alpaca concepts of device capabilities and the ASIAIR does not expose all of those. ASIAIR also has an event interface wheras astrolive is pull-only.

This code can probably be modified to provide an ASIAIR-Alpaca bridge if ZWO are not forthcoming there.

Command lists were pulled from this [Cloudy Nights thread](https://www.cloudynights.com/topic/900861-seestar-s50asiair-jailbreak-ssh/page-4) and some subsequent packet inspections of the ASIAIR image transfer protocol.