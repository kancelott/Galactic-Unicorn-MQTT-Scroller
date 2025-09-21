#!/bin/bash

# galactic.sh: a script to periodically cause galactic Unicorn to display a message
#
# Usage example:  ./galactic.sh "This is a test" 10

# set -xe

export msg=${msg:-$1}
export interval=${interval:-$2}
export counter=${counter:-$3}

# NOTE: This is possibly not the proper MQTT broker (see config.py)
export MQTT='test.mosquitto.org'

[ -n "${msg}" ] || msg='This is a test message. Have a great day'
[ -n "${interval}" ] || interval=60
[ -n "${counter}" ] || counter=0

while : ; do
    now=$(date "+%D %T")
    payload=$(jq -c -n \
                 --arg counter "$counter" \
                 --arg msg "$now $msg" \
                 --arg outline_colour "black_or_brown" \
                 --arg msg_colour "any_except_black_or_brown" \
                 '{"msg": "\($msg) \($counter)", "outline_colour": "\($outline_colour)", "msg_colour": "\($msg_colour)", "bg_colour": "random"}')

    echo $payload

    # NOTE: This is assuming that TOPIC_PREFIX (see config.py) is "galactic"
    mosquitto_pub -h "$MQTT" -t "galactic/msg" -m "$payload" ||:
    # mosquitto_pub -h "$MQTT" -t "galactic/ping" -n ||:

    sleep $interval
    counter=$((counter + 1))
done
