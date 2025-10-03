import json
import math
import random
import re
import time
import urandom
import uasyncio as asyncio
from galactic import GalacticUnicorn
from picographics import PicoGraphics, DISPLAY_GALACTIC_UNICORN as DISPLAY
from machine import Pin, PWM, Timer, reset
from mqtt_as import MQTTClient, config
from mqtt_config import wifi_led, blue_led, TOPIC_PREFIX  # Local definitions

# constants for controlling scrolling text
DEFAULT_BRIGHTNESS = 0.5
DEFAULT_MESSAGE_COLOUR = (255, 255, 255)
DEFAULT_OUTLINE_COLOUR = (0, 0, 0)
DEFAULT_BG_COLOUR = (0, 0, 0)
PADDING = 2
HOLD_TIME = 0
STEP_TIME = 0.03  # Edit to slow down/speed up text - lower for faster scrolling
MESSAGE_REPEAT_MIN = 60

# create galactic object and graphics surface for drawing
gu = GalacticUnicorn()
graphics = PicoGraphics(DISPLAY)
graphics.set_font("bitmap8")
current_task = None

WIDTH = GalacticUnicorn.WIDTH
HEIGHT = GalacticUnicorn.HEIGHT
ROTATE_180 = True

# notification tone
TONES = [523.25, 311.13, 392, 466.16]
volume = 1.0

# define known colours
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

async def play_tone_realistic(channel, base_freq, base_volume, duration):
    start_time = time.ticks_ms()
    elapsed = 0
    fade_out_steps = 10
    fade_out_delay = 0.005

    while elapsed < duration * 1000 - fade_out_steps * fade_out_delay * 1000:
        vibrato = 5 * math.sin(2 * math.pi * 5 * elapsed / 1000)
        freq = base_freq + vibrato
        tremolo = base_volume * (0.8 + 0.2 * math.sin(2 * math.pi * 3 * elapsed / 1000))
        channel.play_tone(int(freq), tremolo)
        gu.play_synth()
        wait = 0.01 + random.uniform(-0.002, 0.002)
        await asyncio.sleep(wait)

        elapsed = time.ticks_ms() - start_time

    # Fade-out volume smoothly
    for i in range(fade_out_steps, 0, -1):
        vol = base_volume * (i / fade_out_steps) * (0.8 + 0.2 * math.sin(2 * math.pi * 3 * elapsed / 1000))
        channel.play_tone(int(freq), vol)
        gu.play_synth()
        await asyncio.sleep(fade_out_delay)
    gu.stop_playing()
    await asyncio.sleep_ms(10)


async def play_notification_tone():
    channel = gu.synth_channel(0)
    for t in TONES:
        await play_tone_realistic(channel, t, volume, 0.2)


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

        # Extract text and colour strings
        text = data.get("msg", data.get("message", data.get("text", data.get("txt", ""))))
        progress = data.get("progress", data.get("percent", data.get("value", 0)))

        text_colour_value = data.get("msg_colour", data.get("text_colour", data.get("txt_colour", data.get(
                "msg_color", data.get("text_color", data.get("txt_color"))))))
        bg_colour_value = data.get("bg_colour", data.get("bg_color"))
        outline_colour_value = data.get("outline_colour", data.get("outline_color"))

        # Parse colours if present, or fall back to defaults
        bg_colour = parse_rgb(bg_colour_value) or DEFAULT_BG_COLOUR
        outline_colour = parse_rgb(outline_colour_value) or DEFAULT_OUTLINE_COLOUR
        text_colour = parse_rgb(text_colour_value) or DEFAULT_MESSAGE_COLOUR

        return text, bg_colour, outline_colour, text_colour, progress

    except ValueError:
        # If the message is not valid JSON, return the defaults
        return msg, DEFAULT_BG_COLOUR, DEFAULT_OUTLINE_COLOUR, DEFAULT_MESSAGE_COLOUR, 0


def clear_screen():
    graphics.set_pen(graphics.create_pen(0, 0, 0))
    graphics.clear()
    gu.update(graphics)


def outline_msg(text, outline_colour, msg_colour, x, y):
    if not ROTATE_180:
        rotate = 0
    else:
        rotate = 180

    # draw outline
    graphics.set_pen(graphics.create_pen(
            int(outline_colour[0]), int(outline_colour[1]), int(outline_colour[2])))
    graphics.text(text, x - 1, y - 1, -1, 1, rotate)
    graphics.text(text, x    , y - 1, -1, 1, rotate)
    graphics.text(text, x + 1, y - 1, -1, 1, rotate)
    graphics.text(text, x - 1, y    , -1, 1, rotate)
    graphics.text(text, x + 1, y    , -1, 1, rotate)
    graphics.text(text, x - 1, y + 1, -1, 1, rotate)
    graphics.text(text, x    , y + 1, -1, 1, rotate)
    graphics.text(text, x + 1, y + 1, -1, 1, rotate)

    # draw text
    graphics.set_pen(graphics.create_pen(
            int(msg_colour[0]), int(msg_colour[1]), int(msg_colour[2])))
    graphics.text(text, x, y, -1, 1, rotate)


# MQTT Message Display
async def handle_scroll_message(topic, msg, retained):
    STATE_PRE_SCROLL = 0
    STATE_SCROLLING = 1
    STATE_POST_SCROLL = 2
    shift = 0
    state = STATE_PRE_SCROLL
    last_time = time.ticks_ms()
    start_time = time.ticks_ms()

    text, bg_colour, outline_colour, msg_colour, _ = parse_msg(msg.decode('utf-8'))
    if not text:
        print("clearing screen")
        clear_screen()
        return
    message = str("                " + text + "             ")
    msg_width = graphics.measure_text(message, 1)

    # play notification sound
    asyncio.create_task(play_notification_tone())

    # scrolling loop
    while True:
        # stop scrolling after 30 min continous
        elapsed_ms = time.ticks_diff(time.ticks_ms(), start_time)
        if elapsed_ms >= MESSAGE_REPEAT_MIN * 60 * 1000:
            clear_screen()
            return

        time_ms = time.ticks_ms()
        if state == STATE_PRE_SCROLL and time_ms - last_time > HOLD_TIME * 1000:
            if msg_width + PADDING * 2 >= WIDTH:
                state = STATE_SCROLLING
            last_time = time_ms
        if state == STATE_SCROLLING and time_ms - last_time > STEP_TIME * 1000:
            shift += 1
            if shift >= (msg_width + PADDING * 2) - WIDTH - 1:
                state = STATE_PRE_SCROLL
                shift = 0
                last_time = time_ms
            last_time = time_ms
        if state == STATE_POST_SCROLL and time_ms - last_time > HOLD_TIME * 1000:
            state = STATE_PRE_SCROLL
            shift = 0
            last_time = time_ms

        # draw bg
        graphics.set_pen(graphics.create_pen(
                int(bg_colour[0]), int(bg_colour[1]), int(bg_colour[2])))
        graphics.clear()

        # draw text
        if not ROTATE_180:
            outline_msg(message, outline_colour, msg_colour, PADDING - shift, 2)
        else:
            outline_msg(message, outline_colour, msg_colour, WIDTH - PADDING + shift, 8)
        gu.update(graphics)

        # pause for a moment (important or the USB serial device will fail)
        await asyncio.sleep_ms(1)


# MQTT Progress Bar Message Display
async def handle_progress_message(topic, msg, retained):
    HUE_START = 0
    HUE_END = 100

    # draws percentage icon
    def draw_percentage(x, y):
        graphics.rectangle(x + 1, y + 1, 2, 2)
        graphics.line(x + 1, y + 5, x + 6, y)
        graphics.rectangle(x + 4, y + 4, 2, 2)

    text, bg_colour, outline_colour, msg_colour, progress = parse_msg(msg.decode('utf-8'))
    if not text:
        print("clearing screen")
        clear_screen()
        return

    # calculate colour from the brightness value
    hue = max(0, HUE_START + ((progress - 0) * (HUE_END - HUE_START) / (100 - 0)))
    bar_colour = graphics.create_pen_hsv(hue / 360, 1.0, 1.0)

    # draw bg
    graphics.set_pen(graphics.create_pen(
            int(bg_colour[0]), int(bg_colour[1]), int(bg_colour[2])))
    graphics.clear()

    # draw the text
    if not ROTATE_180:
        outline_msg(text, outline_colour, msg_colour, 0, 1)
    else:
        outline_msg(text, outline_colour, msg_colour, WIDTH - 1, 9)

    # draw percentage
    text_width = graphics.measure_text(f"{progress:.0f}  ", scale=1)
    if not ROTATE_180:
        outline_msg(f"{progress:.0f}", outline_colour, msg_colour, WIDTH - text_width + 3, 1)
        draw_percentage(WIDTH - 6, 2)
    else:
        outline_msg(f"{progress:.0f}", outline_colour, msg_colour, text_width - 4, 9)
        draw_percentage(-1, 2)

    # draw bar background
    graphics.set_pen(graphics.create_pen(
        int(KNOWN_COLOURS["grey"][0]), int(KNOWN_COLOURS["grey"][1]), int(KNOWN_COLOURS["grey"][2])))
    if not ROTATE_180:
        graphics.rectangle(0, 9, WIDTH, 10)
    else:
        graphics.rectangle(0, 0, WIDTH, 2)

    # draw bar for the current percent
    graphics.set_pen(bar_colour)
    if not ROTATE_180:
        graphics.rectangle(0, 9, int((progress / 100) * WIDTH), 10)
    else:
        graphics.rectangle(max(int(WIDTH - ((progress / 100) * WIDTH)), 0), 0, WIDTH, 2)

    gu.update(graphics)
    await asyncio.sleep(1)


# Respond to incoming messages
async def messages(client):
    global current_task

    async for topic, msg, retained in client.queue:
        # cancel the current task if it exists
        if current_task and not current_task.done():
            current_task.cancel()
            try:
                await current_task
            except asyncio.CancelledError:
                pass

        # incoming message!
        topic_str = topic.decode()
        print(f'Topic: "{topic_str}", Retained: {retained}, Message: \n{msg.decode()}')

        # create the new task
        if topic_str.lower().endswith("/msg"):
            current_task = asyncio.create_task(handle_scroll_message(topic, msg, retained))

        elif topic_str.lower().endswith("/progress"):
            current_task = asyncio.create_task(handle_progress_message(topic, msg, retained))
            pass


# Handle button presses
async def button_handler():
    global current_task
    global volume

    gu.set_brightness(DEFAULT_BRIGHTNESS)
    while True:
        # sleep - clear display and stop running task
        if gu.is_pressed(GalacticUnicorn.SWITCH_SLEEP):
            current_task.cancel()
            graphics.set_pen(graphics.create_pen(0, 0, 0))
            graphics.clear()
            gu.update(graphics)

        if not ROTATE_180:
            # brightness adjust
            if gu.is_pressed(GalacticUnicorn.SWITCH_BRIGHTNESS_UP):
                gu.adjust_brightness(+0.1)
            if gu.is_pressed(GalacticUnicorn.SWITCH_BRIGHTNESS_DOWN):
                gu.adjust_brightness(-0.1)

            # volume adjust
            if gu.is_pressed(GalacticUnicorn.SWITCH_VOLUME_UP):
                volume = min(volume + 0.1, 1)
            if gu.is_pressed(GalacticUnicorn.SWITCH_VOLUME_DOWN):
                volume = max(volume - 0.1, 0)

        else:
            # brightness button adjust (inverted)
            if gu.is_pressed(GalacticUnicorn.SWITCH_BRIGHTNESS_UP):
                gu.adjust_brightness(-0.1)
            if gu.is_pressed(GalacticUnicorn.SWITCH_BRIGHTNESS_DOWN):
                gu.adjust_brightness(+0.1)

            # volume adjust (inverted)
            if gu.is_pressed(GalacticUnicorn.SWITCH_VOLUME_UP):
                volume = max(volume - 0.1, 0)
            if gu.is_pressed(GalacticUnicorn.SWITCH_VOLUME_DOWN):
                volume = min(volume + 0.1, 1)

        await asyncio.sleep_ms(200)


# Heartbeat connection status
async def heartbeat(client):
    s = True
    while True:
        if not client.isconnected():
            # flashing fast = not connected
            sleep_value = 250
            s = not s
        else:
            # steady = all good
            sleep_value = 3000
            s = True
        blue_led(s)
        await asyncio.sleep_ms(sleep_value)


# Respond to connectivity being (re)established
async def up(client):
    while True:
        # wait on an Event
        await client.up.wait()
        client.up.clear()

        # renew subscriptions
        await client.subscribe(TOPIC_PREFIX + "/msg", 1)
        await client.subscribe(TOPIC_PREFIX + "/progress", 1)


async def main(client):
    # connection status LED
    asyncio.create_task(heartbeat(client))

    # button handler
    asyncio.create_task(button_handler())

    try:
        # connect to wifi and MQTT broker
        print("Connecting... ", end='')
        await client.connect()
        print("OK!")
    except OSError as e:
        print("Connection failed")
        return

    # handle messages
    for coroutine in (up, messages):
        asyncio.create_task(coroutine(client))

    while True:
        await asyncio.sleep(5)


# setup MQTT client
config["queue_len"] = 1
MQTTClient.DEBUG = False  # Optional
client = MQTTClient(config)

try:
    asyncio.run(main(client))
except Exception as e:
    print(e)
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop()
