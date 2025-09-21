# Asynchronous mqtt client with clean session (C) Copyright Peter Hinch 2017-2019.
# Released under the MIT licence.

# Public brokers https://github.com/mqtt/mqtt.github.io/wiki/public_brokers

# The use of clean_session means that after a connection failure subscriptions
# must be renewed (MQTT spec 3.1.2.4). This is done by the connect handler.
# Note that publications issued during the outage will be missed. If this is
# an issue see unclean.py.

# red LED: ON == WiFi fail
# blue LED heartbeat: demonstrates scheduler is running.


# Import libraries - config.py sets up wifi and mqtt
import time
import network
from galactic import GalacticUnicorn
from picographics import PicoGraphics, DISPLAY_GALACTIC_UNICORN as DISPLAY
import json
import re
import urandom

from mqtt_as import MQTTClient, config
from config import wifi_led, blue_led, TOPIC_PREFIX  # Local definitions
import uasyncio as asyncio
import machine
from machine import Pin, PWM
from time import sleep


# constants for controlling scrolling text
PADDING = 2
MESSAGE_COLOUR = (255, 255, 255)
OUTLINE_COLOUR = (0, 0, 0)
MESSAGE = ""
# BACKGROUND_COLOUR = (10, 0, 96) # Blue
BACKGROUND_COLOUR = (255, 255, 0)  # Yellow
HOLD_TIME = 2.0
STEP_TIME = 0.045  # Edit to slow down/speed up text - lower for faster scrolling


# create galactic object and graphics surface for drawing
gu = GalacticUnicorn()
graphics = PicoGraphics(DISPLAY)

width = GalacticUnicorn.WIDTH
height = GalacticUnicorn.HEIGHT

# state constants
STATE_PRE_SCROLL = 0
STATE_SCROLLING = 1
STATE_POST_SCROLL = 2

shift = 0
state = STATE_PRE_SCROLL

# Global variables
stats = {
    "wifi_connection": 0,
    "mqtt_connection": 0,
    "msg_cb": 0,
    "uptime_minutes": 0,
}
wifi_is_up = False
ip_address = "0.0.0.0"
ping_event = asyncio.Event()  # Create an asyncio Event

# Define known colours
KNOWN_COLOURS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "magenta": (255, 0, 255),
    "purple": (128, 0, 128),
    "cyan": (0, 255, 255),
    "orange": (255, 165, 0),
    "black": (0, 0, 0),
    "none": (0, 0, 0),
    "nil": (0, 0, 0),
    "null": (0, 0, 0),
    "white": (255, 255, 255),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),  # Alternate spelling
    "pink": (255, 192, 203),
    "brown": (165, 42, 42),
    "lime": (0, 255, 0),
    "navy": (0, 0, 128),
    "teal": (0, 128, 128),
    "olive": (128, 128, 0),
    "maroon": (128, 0, 0),
    "aqua": (0, 255, 255),
    "silver": (192, 192, 192),
    "gold": (255, 215, 0),
    "beige": (245, 245, 220),
    "violet": (238, 130, 238),
}

# set the font
graphics.set_font("bitmap8")

# calculate the message width so scrolling can happen
msg_width = graphics.measure_text(MESSAGE, 1)

last_time = time.ticks_ms()


def simple_split(input_string):
    # Manually split the string by non-lowercase alphabet characters
    word = ""
    words = []
    for char in input_string:
        if "a" <= char <= "z":  # Check if the character is between 'a' and 'z'
            word += char
        else:
            if word:  # If a word is collected, add it to the list
                words.append(word)
                word = ""  # Reset the word
    if word:  # Add the last word if there is one
        words.append(word)
    return words


def pick_colour(input_string):
    words = simple_split(input_string)
    # Set comprehension for words not in KNOWN_COLOURS
    cmd_in_words = {word for word in words if word not in KNOWN_COLOURS}

    # List comprehension for colours that exist in KNOWN_COLOURS. Repeats increases chance of colour.
    given_colours = [word for word in words if word in KNOWN_COLOURS]

    # if no colours are provided, we will use them all as potential values
    if not given_colours:
        # no colours we know about. Make sure that there is at least a "random" or "pick" mentioned
        if not cmd_in_words.intersection({"random", "select", "pick", "choose", "any"}):
            return
        keys = tuple(KNOWN_COLOURS.keys())  # Convert keys to a tuple once
    elif cmd_in_words.intersection(
        {"not", "no", "ignore", "exclude", "minus", "except", "remove", "nor"}
    ):
        ## Assuming there are unique values for every colour, this should do it
        ## keys = tuple([word for word in KNOWN_COLOURS if word not in set(given_colours)])
        ## But since there are repeated values for colours (like gray and grey), we need to look at values
        ## to know for cetain what to exclude.
        unwanted_values = {KNOWN_COLOURS[given_colour] for given_colour in given_colours}
        keys = tuple(
            [word for word in KNOWN_COLOURS if KNOWN_COLOURS[word] not in unwanted_values]
        )
    else:
        keys = tuple(given_colours)

    random_key = keys[urandom.getrandbits(8) % len(keys)]  # Randomly select a key
    return KNOWN_COLOURS[random_key]


def parse_rgb(colour_str, retry=0):
    if retry > 1:
        return None
    if colour_str is None:
        return None

    try:
        # Remove any square, curly, round braces, and whitespace from the string
        colour_str = re.sub(r"[\[\]\(\)\{\}\s]", "", colour_str)

        # Split the string by commas
        parts = colour_str.split(",")

        # special cases
        if len(parts) > 0 and retry == 1:
            # 0
            if parts[0] == "0" or not parts[0]:
                parts = ["0", "0", "0"]
            else:
                return pick_colour(colour_str.lower())

        # Convert each part to an integer, interpreting as hex if it starts with '0x'
        r, g, b = [
            (
                int(part.strip(), 16)
                if part.strip().lower().startswith("0x")
                else int(part.strip())
            )
            for part in parts
        ]

        # Ensure the values are within the valid range
        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
            return (r, g, b)

    except TypeError:
        pass  # Implicit return None
    except ValueError:
        pass  # Implicit return None

    # Recurse call to try parsing value as a string
    return parse_rgb(str(colour_str), retry + 1)


def parse_msg(msg):
    try:
        # Attempt to parse the message as JSON
        data = json.loads(msg)

        # Extract text or use empty string if not found
        text = data.get("msg", data.get("text", data.get("txt", msg)))
        text_colour = data.get(
            "msg_colour", data.get("text_colour", data.get("txt_colour", msg)))
        # Support spelling of colour without the u
        if text_colour is None:
            text_colour = data.get(
                "msg_color", data.get("text_color", data.get("txt_color", msg)))
        )

        # Parse colours if present, or fall back to defaults
        bg_colour_value = data.get("bg_colour", data.get("bg_color"))
        bg_colour = parse_rgb(bg_colour_value) or BACKGROUND_COLOUR
        outline_colour_value = data.get("outline_colour", data.get("outline_color"))
        outline_colour = parse_rgb(outline_colour_value) or OUTLINE_COLOUR
        msg_colour = parse_rgb(text_colour) or MESSAGE_COLOUR

        return text, bg_colour, outline_colour, msg_colour
    except ValueError:
        # If the message is not valid JSON, return the defaults
        return msg, BACKGROUND_COLOUR, OUTLINE_COLOUR, MESSAGE_COLOUR


# MQTT Message Subscription and Display


def sub_cb(topic, msg, retained):
    global stats

    topic_str = topic.decode()
    print(f'Topic: "{topic_str}" Message: "{msg.decode()}" Retained: {retained}')

    if topic_str.lower().endswith("/status"):
        return

    if topic_str.lower().endswith("/ping"):
        ping_event.set()
        return

    stats["msg_cb"] += 1

    # go no further if this is not a msg topic
    if not topic_str.lower().endswith("/msg"):
        return

    # state constants
    brightness = 0.5
    gu.set_brightness(brightness)
    STATE_PRE_SCROLL = 0
    STATE_SCROLLING = 1
    STATE_POST_SCROLL = 2

    shift = 0
    state = STATE_PRE_SCROLL

    def outline_text(text, outline_colour, msg_colour, x, y):
        graphics.set_pen(
            graphics.create_pen(
                int(outline_colour[0]), int(outline_colour[1]), int(outline_colour[2])
            )
        )
        graphics.text(text, x - 1, y - 1, -1, 1)
        graphics.text(text, x, y - 1, -1, 1)
        graphics.text(text, x + 1, y - 1, -1, 1)
        graphics.text(text, x - 1, y, -1, 1)
        graphics.text(text, x + 1, y, -1, 1)
        graphics.text(text, x - 1, y + 1, -1, 1)
        graphics.text(text, x, y + 1, -1, 1)
        graphics.text(text, x + 1, y + 1, -1, 1)

        graphics.set_pen(
            graphics.create_pen(int(msg_colour[0]), int(msg_colour[1]), int(msg_colour[2]))
        )
        graphics.text(text, x, y, -1, 1)

    DATA, bg_colour, outline_colour, msg_colour = parse_msg(msg.decode("utf-8"))
    if not DATA:
        print("Ignoring empty payload")
        return

    MESSAGE = str("                " + DATA + "             ")
    # calculate the message width so scrolling can happen
    msg_width = graphics.measure_text(MESSAGE, 1)
    last_time = time.ticks_ms()
    print(DATA)

    while True:
        time_ms = time.ticks_ms()

        if gu.is_pressed(GalacticUnicorn.SWITCH_BRIGHTNESS_UP):
            gu.adjust_brightness(+0.01)

        if gu.is_pressed(GalacticUnicorn.SWITCH_BRIGHTNESS_DOWN):
            gu.adjust_brightness(-0.01)

        if state == STATE_PRE_SCROLL and time_ms - last_time > HOLD_TIME * 1000:
            if msg_width + PADDING * 2 >= width:
                state = STATE_SCROLLING
            last_time = time_ms

        if state == STATE_SCROLLING and time_ms - last_time > STEP_TIME * 1000:
            shift += 1
            if shift >= (msg_width + PADDING * 2) - width - 1:
                state = STATE_POST_SCROLL
                brightness = 0
                gu.set_brightness(brightness)
                gu.update(graphics)
                print("message display finished")
                break

            last_time = time_ms

        if state == STATE_POST_SCROLL and time_ms - last_time > HOLD_TIME * 1000:
            state = STATE_PRE_SCROLL
            shift = 0
            last_time = time_ms

        graphics.set_pen(
            graphics.create_pen(int(bg_colour[0]), int(bg_colour[1]), int(bg_colour[2]))
        )
        graphics.clear()

        outline_text(MESSAGE, outline_colour, msg_colour, x=PADDING - shift, y=2)

        # update the display
        gu.update(graphics)

        # pause for a moment (important or the USB serial device will fail)
        time.sleep(0.001)


# Get the IP address
def get_ip_address():
    sta_if = network.WLAN(network.STA_IF)
    return sta_if.ifconfig()[0] if sta_if.isconnected() else "0.0.0.0"


# Demonstrate scheduler is operational.
async def heartbeat():
    # Rates for the heart
    # fast = no wifi
    # 1 sec = no mqtt
    # 3 sec = all good, hopefully
    s = True
    while True:
        if not wifi_is_up:
            sleep_value = 250
        else:
            sleep_value = 1000 if stats["mqtt_connection"] == 0 else 3000
        await asyncio.sleep_ms(sleep_value)
        blue_led(s)
        s = not s


# Count for how long the board has been operational
async def updateuptime():
    global stats

    while True:
        await asyncio.sleep(60)
        stats["uptime_minutes"] += 1  # Increment uptime count


async def wifi_han(state):
    global stats
    global ip_address
    global wifi_is_up

    wifi_is_up = state
    wifi_led(not state)
    if state:  # WiFi is up
        stats["wifi_connection"] += 1  # Increment connection count
        ip_address = get_ip_address()
    else:
        stats["mqtt_connection"] = 0
    print(
        "WiFi is",
        "UP." if state else "DOWN.",
        f"Address is {ip_address}.",
        "Wifi up count",
        stats["wifi_connection"],
    )
    await asyncio.sleep(1)


# If you connect with clean_session True, must re-subscribe (MQTT spec 3.1.2.4)
async def conn_han(client):
    global stats
    stats["mqtt_connection"] += 1  # Increment connection count
    # await client.subscribe(TOPIC_PREFIX + "/#", 1)
    await client.subscribe(TOPIC_PREFIX + "/msg", 1)
    await client.subscribe(TOPIC_PREFIX + "/ping", 1)
    print("mqtt connected", stats["mqtt_connection"], "times now")
    ping_event.set()


async def main(client):
    print("starting\n")
    try:
        await client.connect()
    except OSError:
        print("Connection failed.")
        await asyncio.sleep(15)
        machine.reset()
        return

    n = 0
    tick_sleep = 1800
    try:
        while True:
            n += 1

            # Wait for the tick_sleep or an external event
            try:
                await asyncio.wait_for(ping_event.wait(), tick_sleep)
                ping_event.clear()
                print("publish from ping/mqtt_connect", n)
            except asyncio.TimeoutError:
                print("publish", n)
                pass  # Timeout indicates tick_sleep passed without event being set

            payload_dict = {
                "repub_count": client.REPUB_COUNT,
                "ip_address": ip_address,
                "mqtt_connection_count": stats["mqtt_connection"],
                "wifi_connection_count": stats["wifi_connection"],
                "msg_cb_count": stats["msg_cb"],
                "uptime_minutes": stats["uptime_minutes"],
            }
            payload = json.dumps(payload_dict)

            # If WiFi is down the following will pause for the duration.
            await client.publish(TOPIC_PREFIX + "/status", payload, qos=0)
            await asyncio.sleep(urandom.getrandbits(2))
    except Exception as e:
        print("Failed:", e)
        await asyncio.sleep(15)
        machine.reset()
        return


# Define configuration
config["subs_cb"] = sub_cb
config["wifi_coro"] = wifi_han
config["connect_coro"] = conn_han
config["clean"] = True

# Set up client
MQTTClient.DEBUG = False  # Optional

client = MQTTClient(config)
asyncio.create_task(heartbeat())
asyncio.create_task(updateuptime())


try:
    asyncio.run(main(client))
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop()
