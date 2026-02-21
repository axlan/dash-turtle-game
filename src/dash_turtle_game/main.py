import asyncio
import copy
import random
import time
import math
from threading import Thread
from queue import Queue

import WonderPy.core.wwMain
from WonderPy.core.wwConstants import WWRobotConstants
from WonderPy.components.wwMedia import WWMedia
from WonderPy.core.wwRobot import WWRobot

from .map import GameMap, CmdEvent, TurtlePose, TileType, TileState
from .mqtt_client import MQTTCommandClient

START_TILE = (0, 5)
START_THETA = 270
GOAL_TILE = (4, 1)
MAP_SIZE_TILES = (6, 6)
TILE_SIZE_CM = 30.48
TILE_SIZE_PIXELS = 64

FRONT_DETECTION_THRESHOLD = 12
TURN_TIME = 4
FORWARD_TIME = 4

TIME_BETWEEN_PRINT_SEC = 2.0

# TODO:
# Tune obstacle detection
# Add imminent collision avoidance
# Add command queue with GUI HUD
# Integrate with RFID cards
# Handle disconnect gracefully


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


def normalize_ang360(angle: float) -> float:
    return angle % 360.0


def normalize_ang180(angle: float) -> float:
    angle = normalize_ang360(angle)
    return angle if angle < 180 else angle - 360.0


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


def set_bot_rgb(robot: WWRobot):
    robot.commands.RGB.stage_ear_left(0, 1, 0)
    robot.commands.RGB.stage_front(0, 0, 1)
    robot.commands.RGB.stage_ear_right(1, 0, 0)


def do_celebrate(robot: WWRobot):
    def random_color():
        return random.random(), random.random(), random.random()

    robot.commands.media.stage_audio(WWMedia.WWSound.WWSoundDash.TRUMPET_01, 1.0)

    robot.commands.body.stage_pose(
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
        robot.commands.RGB.stage_ear_left(*random_color())
        robot.commands.RGB.stage_ear_right(*random_color())
        robot.commands.RGB.stage_front(*random_color())
        time.sleep(0.2)
        if time.time() - start > 3 and not did_yipee:
            robot.commands.media.stage_audio(WWMedia.WWSound.WWSoundDash.YIPPEE_02, 1.0)
            did_yipee = True

    set_bot_rgb(robot)


class RobotPoseMapper:
    def __init__(
        self, robot: WWRobot, start_pose_virtual: TurtlePose, pos_scale: float
    ) -> None:
        self.robot = robot
        pose = robot.sensors.pose
        self.start_pose_robot = TurtlePose(pose.x, pose.y, pose.degrees)
        self.start_pose_virtual = copy.copy(start_pose_virtual)
        self.theta_offset = self.start_pose_virtual.theta - self.start_pose_robot.theta
        self.pos_scale = pos_scale
        self.virtual_pos = copy.copy(start_pose_virtual)

    def turn(self, turn_clockwise: bool):
        self.virtual_pos.theta += -90.0 if turn_clockwise else 90.0
        self.virtual_pos.theta = normalize_ang360(self.virtual_pos.theta)
        desired_degrees = self.virtual_pos.theta - self.theta_offset
        cur_pose = self.robot.sensors.pose
        print(cur_pose.degrees, desired_degrees)
        self.robot.commands.body.stage_pose(
            cur_pose.x,
            cur_pose.y,
            desired_degrees,
            TURN_TIME,
            mode=WWRobotConstants.WWPoseMode.WW_POSE_MODE_GLOBAL,
        )

    def forward(self):
        virtual_dist = 1.0
        rad = math.radians(self.virtual_pos.theta)
        self.virtual_pos.x += math.cos(rad) * virtual_dist
        self.virtual_pos.y += math.sin(rad) * virtual_dist

        # Transform from virtual coordinates to robot coordinates
        # 1. Remove virtual start offset and convert to cm
        # 2. Rotate to the robots sensor orientation
        # 3. Add back the robots start position offset
        desired_x = (self.virtual_pos.x - self.start_pose_virtual.x) / self.pos_scale
        desired_y = (self.virtual_pos.y - self.start_pose_virtual.y) / self.pos_scale
        desired_x, desired_y = rotate_point(
            desired_x, desired_y, 90 - self.theta_offset
        )
        desired_x += self.start_pose_robot.x
        desired_y += self.start_pose_robot.y
        self.robot.commands.body.stage_pose(
            desired_x,
            desired_y,
            self.robot.sensors.pose.degrees,
            FORWARD_TIME,
            mode=WWRobotConstants.WWPoseMode.WW_POSE_MODE_GLOBAL,
        )

    def get_pose(self):
        cur_pose = self.robot.sensors.pose
        # Remove start offset so robot starts at 0,0
        bot_x = cur_pose.x - self.start_pose_robot.x
        bot_y = cur_pose.y - self.start_pose_robot.y
        # Apply rotation so robot starts at correct angle
        # -90 to handle turtle bot coordinates face in +y direction
        bot_x, bot_y = rotate_point(bot_x, bot_y, self.theta_offset - 90)
        return TurtlePose(
            bot_x * self.pos_scale + self.start_pose_virtual.x,
            bot_y * self.pos_scale + self.start_pose_virtual.y,
            normalize_ang360(cur_pose.degrees + self.theta_offset),
        )


def set_observed_tile(map: GameMap, x: int, y: int, tile: TileType):
    if map.tiles[x][y].type != TileType.GOAL:
        map.tiles[x][y] = TileState(tile, observed=True, text=map.tiles[x][y].text)
    else:
        map.tiles[x][y].observed = True


class RobotInterface:

    def __init__(self) -> None:
        self.is_running = True
        self.ctrl_thread = None
        self.queue = Queue()
        self.ctrl_thread: Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def on_connect(self, robot: WWRobot):
        self.loop = asyncio.get_event_loop()
        print("Starting a task for %s." % (robot.name))
        self.ctrl_thread = Thread(
            target=self.robot_ctrl, args=(robot,), name="robot_ctrl"
        )
        self.ctrl_thread.start()

    def on_sensors(self, robot):
        self.queue.put_nowait(1)

    # Can write this as either asyncio, or Thread. With asyncio, I can be sure
    # that the context won't switch while using a piece of data, but I can't
    # call the blocking WWRobot functions. To keep things simple, I'll keep it
    # multithreaded.
    def robot_ctrl(self, robot: WWRobot):
        # robot.commands.body.do_forward(10, 3)
        set_bot_rgb(robot)
        map = GameMap(num_map_tiles=MAP_SIZE_TILES, tile_size_pixels=TILE_SIZE_PIXELS)
        last_print = time.time()

        self.queue.get()
        bot_mapper = RobotPoseMapper(
            robot,
            TurtlePose(
                START_TILE[0] + 0.5,
                START_TILE[1] + 0.5,
                START_THETA,
            ),
            pos_scale=1.0 / TILE_SIZE_CM,
        )

        map.tiles[GOAL_TILE[0]][GOAL_TILE[1]] = TileState(TileType.GOAL)
        celebrated = False

        last_idle = False

        with MQTTCommandClient("192.168.1.110") as mqtt_client:
            try:
                while self.is_running:
                    robot_idle = robot.sensors.pose.watermark_inferred == 255

                    if last_idle and not robot_idle:
                        robot.commands.monoLED.stage_button_main(0)
                    elif not last_idle and robot_idle:
                        robot.commands.monoLED.stage_button_main(1)
                    last_idle = robot_idle

                    bot_pose = bot_mapper.get_pose()

                    map.turtle_pose = bot_pose

                    def handle_events(events):
                        requested_move = False
                        request_turn = False
                        turn_clockwise = False
                        for event in events:
                            if event == CmdEvent.QUIT:
                                if self.loop is not None:
                                    print("GUI Exited...")
                                    WonderPy.core.wwMain.stop()
                            elif event == CmdEvent.LEFT:
                                request_turn = True
                                turn_clockwise = False
                            elif event == CmdEvent.RIGHT:
                                request_turn = True
                                turn_clockwise = True
                            elif event == CmdEvent.UP:
                                requested_move = True

                            # Can only handle one action at a time
                            break
                        return request_turn, requested_move, turn_clockwise

                    request_turn, requested_move, turn_clockwise = handle_events(
                        map.GetWindowEvents()
                    )

                    if not requested_move and not request_turn:
                        request_turn, requested_move, turn_clockwise = handle_events(
                            mqtt_client.get_messages()
                        )

                    if not robot_idle and (request_turn or requested_move):
                        robot.commands.media.stage_audio(
                            WWMedia.WWSound.WWSoundDash.SIGH_DASH, 1.0
                        )
                    elif request_turn:
                        bot_mapper.turn(turn_clockwise)

                    for i, t in enumerate(map.GetAllTiles()):
                        t.observed = False

                    # Set all tiles to be unobserved and with their letter.
                    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                    for c, col_tiles in enumerate(map.tiles):
                        for r, t in enumerate(col_tiles):
                            i = c + (MAP_SIZE_TILES[1] - r - 1) * MAP_SIZE_TILES[0]
                            t.observed = False
                            t.text = letters[i]

                    map_x = int(map.turtle_pose.x)
                    map_y = int(map.turtle_pose.y)

                    if map_x >= MAP_SIZE_TILES[0] and map_y >= MAP_SIZE_TILES[1]:
                        print("Unexpected map position")
                        print(
                            f"robot pose: x:{robot.sensors.pose.x}, y:{robot.sensors.pose.y}, theta: {robot.sensors.pose.degrees}"
                        )
                        print(f"map pose: {map.turtle_pose}")
                        continue

                    set_observed_tile(map, map_x, map_y, TileType.EMPTY)

                    if robot_idle:
                        if (
                            not celebrated
                            and map.tiles[map_x][map_y].type == TileType.GOAL
                        ):
                            # This blocks the GUI, should probably not, but not a huge issue.
                            do_celebrate(robot)
                            celebrated = True

                        if map.turtle_pose.theta < 45 or map.turtle_pose.theta > (
                            360 - 45
                        ):
                            front_x = map_x + 1
                            front_y = map_y
                        elif map.turtle_pose.theta < 135:
                            front_x = map_x
                            front_y = map_y + 1
                        elif map.turtle_pose.theta < 225:
                            front_x = map_x - 1
                            front_y = map_y
                        else:
                            front_x = map_x
                            front_y = map_y - 1

                        looking_off_map = (
                            front_x < 0
                            or front_x >= MAP_SIZE_TILES[0]
                            or front_y < 0
                            or front_y >= MAP_SIZE_TILES[1]
                        )

                        if not looking_off_map:
                            if (
                                robot.sensors.distance_front_left_facing.reflectance
                                is not None
                                and robot.sensors.distance_front_left_facing.reflectance
                                > FRONT_DETECTION_THRESHOLD
                                and robot.sensors.distance_front_right_facing.reflectance
                                is not None
                                and robot.sensors.distance_front_right_facing.reflectance
                                > FRONT_DETECTION_THRESHOLD
                            ):
                                set_observed_tile(
                                    map, front_x, front_y, TileType.BLOCKED
                                )
                            else:
                                set_observed_tile(map, front_x, front_y, TileType.EMPTY)

                        if requested_move:
                            if looking_off_map:
                                print("Move off map")
                                robot.commands.media.stage_audio(
                                    WWMedia.WWSound.WWSoundDash.NO_WAY, 1.0
                                )
                            elif map.tiles[front_x][front_y].type == TileType.BLOCKED:
                                print("Move blocked")
                                robot.commands.media.stage_audio(
                                    WWMedia.WWSound.WWSoundDash.NO_WAY, 1.0
                                )
                            else:
                                bot_mapper.forward()

                    if time.time() - last_print > TIME_BETWEEN_PRINT_SEC:
                        # print(f'{int(robot.sensors.distance_rear.reflectance):3},{int(robot.sensors.distance_front_right_facing.reflectance):3},{int(robot.sensors.distance_front_left_facing.reflectance):3}')
                        # print(f'{robot.sensors.distance_rear}')
                        # if robot_idle:
                        #     print(f'map: {map_x}, {map_y}, {map.turtle_pose.theta}')
                        #     print(f'front: {front_x}, {front_y}')
                        # print(robot.sensors.distance_front_left_facing.reflectance, robot.sensors.distance_front_right_facing.reflectance)
                        print(bot_mapper.get_pose())
                        last_print = time.time()

                    map.Draw()

                    self.queue.get()
            except KeyboardInterrupt:
                pass

        map.Stop()

    def Stop(self):
        if self.ctrl_thread:
            self.is_running = False
            self.queue.put_nowait(0)
            self.ctrl_thread.join()


# kick off the program !
if __name__ == "__main__":
    robot = RobotInterface()
    WonderPy.core.wwMain.start(robot)
    robot.Stop()
