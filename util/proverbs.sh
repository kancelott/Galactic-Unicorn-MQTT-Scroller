#!/bin/bash

# proverbs.sh: a script to periodically cause galactic Unicorn to display a proverb
#
# Usage example:  ./proverbs.sh 25

set -e

export interval=${interval:-$1}

# NOTE: This is possibly not the proper MQTT broker (see config.py)
export MQTT='test.mosquitto.org'

[ -n "${interval}" ] || interval=60

[ -s "/tmp/proverbs.txt" ] || curl --silent -L --max-time 10 -o /tmp/proverbs.txt \
   https://raw.githubusercontent.com/alltom/proverb/master/proverbs.txt

while : ; do
    # Pick a random proverb
    msg=$(shuf -n 1 /tmp/proverbs.txt)
    
    payload=$(jq -c -n \
                 --arg msg "$msg" \
                 --arg outline_colour "black" \
                 --arg msg_colour "any_except_black_or_brown" \
                 '{"msg": "\($msg)", "outline_colour": "\($outline_colour)", "msg_colour": "\($msg_colour)", "bg_colour": "random"}')

    echo $payload
    
    # NOTE: This is assuming that TOPIC_PREFIX (see config.py) is "galactic"
    mosquitto_pub -h "$MQTT" -t "galactic/msg" -m "$payload" ||:

    # Add jitter sleep of 0 to 15 seconds
    jitter=$(shuf -i 0-15 -n 1)
    sleep $jitter
    
    sleep $interval
done
