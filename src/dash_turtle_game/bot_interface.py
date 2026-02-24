from enum import StrEnum
import random
import time
import math
from queue import Queue
from dataclasses import replace

import WonderPy.core.wwMain
from WonderPy.core.wwConstants import WWRobotConstants
from WonderPy.components.wwMedia import WWMedia
from WonderPy.core.wwRobot import WWRobot

from .constants import TurtlePose, Settings, SensorData, normalize_ang360, BotSounds

# Coordinates notes:
# Pygame draws things in pixels with:
#     -y
# -x      +x
#     +y
#
# The robot reports things in cm with theta rotated -90 and a random offset in x,y,theta for the robot's start state
#
# The control uses unitless distance where each tile is 1x1
#

def rotate_point(x, y, sigma_degrees):
    """
    Rotate a point (x, y) around the origin by sigma degrees counterclockwise.

    Args:
        x: x-coordinate of the point
        y: y-coordinate of the point
        sigma_degrees: rotation angle in degrees (positive = counterclockwise)

    Returns:
        tuple: (x', y') - the rotated point coordinates
    """
    # Convert degrees to radians
    sigma_radians = math.radians(sigma_degrees)

    # Apply rotation formulas
    x_prime = x * math.cos(sigma_radians) - y * math.sin(sigma_radians)
    y_prime = x * math.sin(sigma_radians) + y * math.cos(sigma_radians)

    return x_prime, y_prime


class RobotControl:
    def __init__(self, robot: WWRobot, sensors: SensorData, conf: Settings) -> None:
        self.robot = robot
        self.conf = conf
        self.sensors = sensors
        self.start_pose_robot = TurtlePose(sensors.x, sensors.y, sensors.degrees)
        self.start_pose_virtual = TurtlePose(
            conf.START_TILE[0] + 0.5,
            conf.START_TILE[1] + 0.5,
            conf.START_THETA,
        )
        self.theta_offset = self.start_pose_virtual.theta - self.start_pose_robot.theta
        self.pos_scale = 1.0 / conf.TILE_SIZE_CM
        self.virtual_pos = self.start_pose_virtual

    def update_sensors(self, sensors: SensorData):
        self.sensors = sensors

    def turn(self, turn_clockwise: bool):
        new_theta = normalize_ang360(self.virtual_pos.theta + (-90.0 if turn_clockwise else 90.0))
        self.virtual_pos = replace(self.virtual_pos, theta = new_theta)
        desired_degrees = self.virtual_pos.theta - self.theta_offset
        self.robot.commands.body.stage_pose(
            self.sensors.x,
            self.sensors.y,
            desired_degrees,
            self.conf.TURN_TIME,
            mode=WWRobotConstants.WWPoseMode.WW_POSE_MODE_GLOBAL,
        )

    def forward(self, reverse=False):
        virtual_dist = -1.0 if reverse else 1.0
        rad = math.radians(self.virtual_pos.theta)
        new_x = self.virtual_pos.x + math.cos(rad) * virtual_dist
        new_y = self.virtual_pos.y + math.sin(rad) * virtual_dist
        self.virtual_pos = replace(self.virtual_pos, x=new_x, y=new_y)

        # Transform from virtual coordinates to robot coordinates
        # 1. Remove virtual start offset and convert to cm
        # 2. Rotate to the robots sensor orientation
        # 3. Add back the robots start position offset
        desired_x = (new_x - self.start_pose_virtual.x) / self.pos_scale
        desired_y = (new_y - self.start_pose_virtual.y) / self.pos_scale
        desired_x, desired_y = rotate_point(
            desired_x, desired_y, 90 - self.theta_offset
        )
        desired_x += self.start_pose_robot.x
        desired_y += self.start_pose_robot.y
        self.robot.commands.body.stage_pose(
            desired_x,
            desired_y,
            self.sensors.degrees,
            self.conf.FORWARD_TIME,
            mode=WWRobotConstants.WWPoseMode.WW_POSE_MODE_GLOBAL,
        )

    def get_pose(self):
        # Remove start offset so robot starts at 0,0
        bot_x = self.sensors.x - self.start_pose_robot.x
        bot_y = self.sensors.y - self.start_pose_robot.y
        # Apply rotation so robot starts at correct angle
        # -90 to handle turtle bot coordinates face in +y direction
        bot_x, bot_y = rotate_point(bot_x, bot_y, self.theta_offset - 90)
        return TurtlePose(
            bot_x * self.pos_scale + self.start_pose_virtual.x,
            bot_y * self.pos_scale + self.start_pose_virtual.y,
            normalize_ang360(self.sensors.degrees + self.theta_offset),
        )

    def set_bot_rgb(self):
        self.robot.commands.RGB.stage_ear_left(0, 1, 0)
        self.robot.commands.RGB.stage_front(0, 0, 1)
        self.robot.commands.RGB.stage_ear_right(1, 0, 0)

    def do_celebrate(self):
        def random_color():
            return random.random(), random.random(), random.random()

        self.robot.commands.media.stage_audio(
            WWMedia.WWSound.WWSoundDash.TRUMPET_01, 1.0
        )

        self.robot.commands.body.stage_pose(
            0,
            0,
            degrees=360,
            time=4,
            wrap_theta=False,
            mode=WWRobotConstants.WWPoseMode.WW_POSE_MODE_RELATIVE_MEASURED,
        )

        start = time.time()
        did_yipee = False
        while time.time() - start < 6:
            self.robot.commands.RGB.stage_ear_left(*random_color())
            self.robot.commands.RGB.stage_ear_right(*random_color())
            self.robot.commands.RGB.stage_front(*random_color())
            time.sleep(0.2)
            if time.time() - start > 3 and not did_yipee:
                self.robot.commands.media.stage_audio(
                    WWMedia.WWSound.WWSoundDash.YIPPEE_02, 1.0
                )
                did_yipee = True

        self.set_bot_rgb()

    def set_main_button_led(self, is_on: bool):
        self.robot.commands.monoLED.stage_button_main(1 if is_on else 0)

    def stop(self):
        self.robot.commands.body.stage_stop()

    def play_sound(self, sound: BotSounds):
        sound_str = {
            BotSounds.SIGH: WWMedia.WWSound.WWSoundDash.SIGH_DASH,
            BotSounds.NO_WAY: WWMedia.WWSound.WWSoundDash.NO_WAY,
        }[sound]
        self.robot.commands.media.stage_audio(sound_str)


class RobotInterface:

    def __init__(self, conf: Settings) -> None:
        self.conf = conf
        self.sensor_queue: Queue[SensorData | None] = Queue()
        self.robot_ctrl: RobotControl | None = None

    def on_sensors(self, robot: WWRobot):
        left_reflect = (
            robot.sensors.distance_front_left_facing.reflectance
            if robot.sensors.distance_front_left_facing.reflectance is not None
            else 0
        )
        right_reflect = (
            robot.sensors.distance_front_right_facing.reflectance
            if robot.sensors.distance_front_right_facing.reflectance is not None
            else 0
        )

        sensors = SensorData(
            x=robot.sensors.pose.x,
            y=robot.sensors.pose.y,
            degrees=robot.sensors.pose.degrees,
            is_idle=robot.sensors.pose.watermark_inferred == 255,
            distance_front_left_facing=left_reflect,
            distance_front_right_facing=right_reflect,
        )

        if self.robot_ctrl is None:
            self.robot_ctrl = RobotControl(robot, sensors, self.conf)

        self.sensor_queue.put_nowait(sensors)

    def run(self):
        WonderPy.core.wwMain.start(self)

    def stop(self):
        WonderPy.core.wwMain.stop()
        self.sensor_queue.put_nowait(None)
