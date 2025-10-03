from galactic import GalacticUnicorn
import time
import math
import random

def play_notification_tone():
    gu = GalacticUnicorn()
    volume = 1  # volume 0 to 1
    channel = gu.synth_channel(0)

    def play_tone_realistic(base_freq, base_volume, duration):
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
            time.sleep(wait)
            
            elapsed = time.ticks_ms() - start_time

        # Fade-out volume smoothly
        for i in range(fade_out_steps, 0, -1):
            vol = base_volume * (i / fade_out_steps) * (0.8 + 0.2 * math.sin(2 * math.pi * 3 * elapsed / 1000))
            channel.play_tone(int(freq), vol)
            gu.play_synth()
            time.sleep(fade_out_delay)
        gu.stop_playing()
        time.sleep(0.05)

    # The harmonious 3-tone major triad sequence
    tones = [440, 550, 660]  # A major triad: A4, C#5, E5

    for tone in tones:
        play_tone_realistic(tone, volume, 0.2)


play_notification_tone()