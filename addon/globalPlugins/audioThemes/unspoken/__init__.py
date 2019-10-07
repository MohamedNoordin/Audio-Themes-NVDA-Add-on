# Unspoken user interface feedback for NVDA
# By Bryan Smart (bryansmart@bryansmart.com) and Austin Hicks (camlorn38@gmail.com)
# Modified for use with the audio themes add-on by Musharraf Omer

import os
import sys
import time
import dataclasses
import weakref
import NVDAObjects
import speech
import sayAllHandler


sys.path.append(os.path.join(os.path.dirname(__file__), "deps"))

# this is a hack.
# Normally, we would modify Libaudioverse to know about Unspoken and NVDA.
# But if Windows sees a DLL is already loaded, it doesn't reload it.
# To that end, we grab the DLLs out of the Libaudioverse directory here.
# order is important.
import ctypes

file_directory = os.path.split(os.path.abspath(__file__))[0]
libaudioverse_directory = os.path.join(file_directory, "deps", "libaudioverse")
dll_hack = [
    ctypes.cdll.LoadLibrary(os.path.join(libaudioverse_directory, "libsndfile-1.dll"))
]
dll_hack.append(
    ctypes.cdll.LoadLibrary(os.path.join(libaudioverse_directory, "libaudioverse.dll"))
)

import libaudioverse

libaudioverse.initialize()
from . import mixer

# taken from Stackoverflow. Don't ask.
def clamp(my_value, min_value, max_value):
    return max(min(my_value, max_value), min_value)


@dataclasses.dataclass
class UnspokenPlayer:
    """Wraps the funcionality of the unspoken add-on."""

    sayAll: bool = True
    speakRoles: bool = True
    noSounds: bool = False
    volumeAdjust: bool = True

    def __post_init__(self):
        self.simulation = libaudioverse.Simulation(block_size=1024)
        self.hrtf_panner = libaudioverse.HrtfNode(self.simulation, "default")
        self.hrtf_panner.should_crossfade = False
        self.hrtf_panner.connect_simulation(0)
        # Hook to keep NVDA from announcing roles.
        self._NVDA_getSpeechTextForProperties = speech.getSpeechTextForProperties
        speech.getSpeechTextForProperties = self._hook_getSpeechTextForProperties
        self._last_played_object = None
        self._last_played_time = 0
        self._last_played_sound = None
        # these are in degrees.
        self._display_width = 180.0
        self._display_height_min = -40.0
        self._display_height_magnitude = 50.0
        # the mixer feeds us through NVDA.
        self.mixer = mixer.Mixer(self.simulation, 1)
        self._precompute_desktop_dimentions()

    def make_sound_object(self, filename):
        """Makes a sound object from libaudioverse."""
        libaudioverse_object = libaudioverse.BufferNode(self.simulation)
        buffer = libaudioverse.Buffer(self.simulation)
        buffer.load_from_file(filename)
        libaudioverse_object.buffer = buffer
        return libaudioverse_object

    def shouldNukeRoleSpeech(self):
        if self.sayAll and sayAllHandler.isRunning():
            return False
        if self.speakRoles:
            return False
        return True

    def _hook_getSpeechTextForProperties(
        self, reason=NVDAObjects.controlTypes.REASON_QUERY, *args, **kwargs
    ):
        role = kwargs.get("role", None)
        if role:
            if self.shouldNukeRoleSpeech():
                # NVDA will not announce roles if we put it in as _role.
                kwargs["_role"] = kwargs["role"]
                del kwargs["role"]
        return self._NVDA_getSpeechTextForProperties(reason, *args, **kwargs)

    def _compute_volume(self):
        if self.volumeAdjust:
            return 1.0
        driver = speech.getSynth()
        volume = getattr(driver, "volume", 100) / 100.0  # nvda reports as percent.
        volume = clamp(volume, 0.0, 1.0)
        return volume

    def play(self, obj, sound):
        if self.noSounds:
            return
        curtime = time.time()
        _last_ref = None if not self._last_played_object else self._last_played_object()
        if (curtime - self._last_played_time < 0.1) and (obj is _last_ref):
            return
        self._last_played_object = weakref.ref(obj)
        self._last_played_time = curtime
        self._play_object(obj, sound)
        self._last_played_sound = sound

    def _play_object(self, obj, sound):
        # Get location of the object.
        if obj.location != None:
            # Object has a location. Get its center.
            obj_x = obj.location[0] + (obj.location[2] / 2.0)
            obj_y = obj.location[1] + (obj.location[3] / 2.0)
        else:
            # Objects without location are assumed in the center of the screen.
            obj_x = self.desktop_max_x / 2.0
            obj_y = self.desktop_max_y / 2.0
        # Scale object position to audio display.
        angle_x = (
            (obj_x - self.desktop_max_x / 2.0) / self.desktop_max_x
        ) * self._display_width
        # angle_y is a bit more involved.
        percent = (self.desktop_max_y - obj_y) / self.desktop_max_y
        angle_y = (
            self._display_height_magnitude * percent + self._display_height_min
        )
        # clamp these to Libaudioverse's internal ranges.
        angle_x = clamp(angle_x, -90.0, 90.0)
        angle_y = clamp(angle_y, -90.0, 90.0)
        if self._last_played_sound:
            with self.simulation:
                self._last_played_sound.disconnect(0)
        sound.connect(0, self.hrtf_panner, 0)
        sound.position = 0.0
        self.hrtf_panner.azimuth = angle_x
        self.hrtf_panner.elevation = angle_y
        self.hrtf_panner.mul = self._compute_volume()

    def _precompute_desktop_dimentions(self):
        self.desktop = NVDAObjects.api.getDesktopObject()
        self.desktop_max_x = self.desktop.location[2]
        self.desktop_max_y = self.desktop.location[3]

    def play_target(target, fromFile=False):
        if not fromFile:
            target.disconnect(0)
            target.position = 0.0
            target.connect_simulation(0)
            return
        from .audioThemeHandler import libaudioverse, SIMULATION

        filePath = os.path.abspath(target)
        fileNode = libaudioverse.BufferNode(SIMULATION)
        buffer = libaudioverse.Buffer(SIMULATION)
        buffer.load_from_file(filePath)
        fileNode.buffer = buffer
        fileNode.connect_simulation(0)

