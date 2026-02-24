from enum import StrEnum, auto
import time
import math
from queue import Queue
from dataclasses import replace
import threading

from .constants import TurtlePose, Settings, SensorData, normalize_ang360, BotSounds


class RobotControl:
    def __init__(self, conf: Settings) -> None:
        self.virtual_pos = TurtlePose(
            conf.START_TILE[0] + 0.5,
            conf.START_TILE[1] + 0.5,
            conf.START_THETA,
        )

    def update_sensors(self, sensors: SensorData):
        pass

    def turn(self, turn_clockwise: bool):
        new_theta = normalize_ang360(self.virtual_pos.theta + (-90.0 if turn_clockwise else 90.0))
        self.virtual_pos = replace(self.virtual_pos, theta = new_theta)

    def forward(self, reverse=False):
        virtual_dist = -1.0 if reverse else 1.0
        rad = math.radians(self.virtual_pos.theta)
        new_x = self.virtual_pos.x + math.cos(rad) * virtual_dist
        new_y = self.virtual_pos.y + math.sin(rad) * virtual_dist
        self.virtual_pos = replace(self.virtual_pos, x=new_x, y=new_y)

    def get_pose(self):
        return self.virtual_pos

    def set_bot_rgb(self):
        pass

    def do_celebrate(self):
        pass

    def set_main_button_led(self, is_on: bool):
        pass

    def stop(self):
        pass

    def play_sound(self, sound: BotSounds):
        pass


class RobotInterface:

    def __init__(self, conf: Settings) -> None:
        self.conf = conf
        self.sensor_queue: Queue[SensorData | None] = Queue()
        self.robot_ctrl = RobotControl(conf)
        self.running = False

    def run(self):
        self.running = True
        try:
            while self.running:
                self.sensor_queue.put_nowait(
                    SensorData(
                        x=self.robot_ctrl.virtual_pos.x,
                        y=self.robot_ctrl.virtual_pos.y,
                        degrees=self.robot_ctrl.virtual_pos.theta,
                        is_idle=True,
                        distance_front_left_facing=0,
                        distance_front_right_facing=0,
                    )
                )
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass

        self.sensor_queue.put_nowait(None)

    def stop(self):
        self.running = False
