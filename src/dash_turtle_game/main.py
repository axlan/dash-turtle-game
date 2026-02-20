import asyncio
import copy
import time
import math
from threading import Thread
from queue import Queue

import WonderPy.core.wwMain
from WonderPy.core.wwConstants import WWRobotConstants
from WonderPy.components.wwMedia import WWMedia
from WonderPy.core.wwRobot import WWRobot

from .map import GameMap, WindowEvent, TurtlePose, TileType, TileState

START_TILE = (0, 0)
START_THETA = 90
GOAL_TILE = (1, 3)
MAP_SIZE_TILES = (6, 6)
TILE_SIZE_CM = 30.48
TILE_SIZE_PIXELS = 64

FRONT_DETECTION_THRESHOLD = 12
TURN_TIME = 4
FORWARD_TIME = 4

TIME_BETWEEN_PRINT_SEC = 2.0

# TODO:
# Auto reconnect to fix initial failed start
# Tune obstacle detection
# Make sounds on refuse commands
# Add goal animation
# Add command queue with GUI HUD
# Integrate with toy controller
# Integrate with RFID cards


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


# Traceback (most recent call last):
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/bleak/backends/bluezdbus/client.py", line 316, in connect
#     await self._get_services(
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/bleak/backends/bluezdbus/client.py", line 677, in _get_services
#     self.services = await manager.get_services(
#                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/bleak/backends/bluezdbus/manager.py", line 719, in get_services
#     await self._wait_for_services_discovery(device_path)
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/bleak/backends/bluezdbus/manager.py", line 873, in _wait_for_services_discovery
#     done, _ = await asyncio.wait(
#               ^^^^^^^^^^^^^^^^^^^
#   File "/usr/lib/python3.12/asyncio/tasks.py", line 464, in wait
#     return await _wait(fs, timeout, return_when, loop)
#            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#   File "/usr/lib/python3.12/asyncio/tasks.py", line 550, in _wait
#     await waiter
# asyncio.exceptions.CancelledError

# The above exception was the direct cause of the following exception:

# Traceback (most recent call last):
#   File "<frozen runpy>", line 198, in _run_module_as_main
#   File "<frozen runpy>", line 88, in _run_code
#   File "/home/jdiamond/src/dash-turtle-game/src/dash_turtle_game/main.py", line 150, in <module>
#     WonderPy.core.wwMain.start(robot)
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/WonderPy/core/wwMain.py", line 6, in start
#     WonderPy.core.wwBTLEMgr.WWBTLEManager(delegate_instance, arguments).run()
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/WonderPy/core/wwBTLEMgr.py", line 323, in run
#     asyncio.run(self.scan_and_connect())
#   File "/usr/lib/python3.12/asyncio/runners.py", line 194, in run
#     return runner.run(main)
#            ^^^^^^^^^^^^^^^^
#   File "/usr/lib/python3.12/asyncio/runners.py", line 118, in run
#     return self._loop.run_until_complete(task)
#            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#   File "/usr/lib/python3.12/asyncio/base_events.py", line 687, in run_until_complete
#     return future.result()
#            ^^^^^^^^^^^^^^^
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/WonderPy/core/wwBTLEMgr.py", line 122, in scan_and_connect
#     async with BleakClient(scanned_device.address, timeout=30) as temp_client:
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/bleak/__init__.py", line 598, in __aenter__
#     await self.connect()
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/bleak/__init__.py", line 620, in connect
#     await self._backend.connect(self._pair_before_connect, **kwargs)
#   File "/home/jdiamond/src/dash-turtle-game/.venv/lib/python3.12/site-packages/bleak/backends/bluezdbus/client.py", line 148, in connect
#     async with async_timeout(timeout):
#   File "/usr/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
#     raise TimeoutError from exc_val
# TimeoutError


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
        robot.commands.RGB.stage_all(1, 0, 0)
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

        try:
            while self.is_running:

                bot_pose = bot_mapper.get_pose()
                map.turtle_pose = bot_pose

                # print(f'map: {rot_x}, {rot_y}, {START_THETA + bot_theta}')

                requested_move = False
                for event in map.GetWindowEvents():
                    if event == WindowEvent.QUIT:
                        if self.loop is not None:
                            print("GUI Exited...")
                            WonderPy.core.wwMain.stop()
                        break
                    elif event == WindowEvent.LEFT:
                        bot_mapper.turn(turn_clockwise=False)
                    elif event == WindowEvent.RIGHT:
                        bot_mapper.turn(turn_clockwise=True)
                    elif event == WindowEvent.UP:
                        requested_move = True

                    # Can only handle one action at a time
                    break

                # Set all tiles to be unobserved
                for t in map.GetAllTiles():
                    t.observed = False

                map_x = int(map.turtle_pose.x)
                map_y = int(map.turtle_pose.y)

                if map_x < MAP_SIZE_TILES[0] and map_y < MAP_SIZE_TILES[1]:
                    map.tiles[map_x][map_y] = TileState(TileType.EMPTY, observed=True)

                robot_idle = robot.sensors.pose.watermark_inferred == 255
                if robot_idle:

                    if map.turtle_pose.theta < 45 or map.turtle_pose.theta > (360 - 45):
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
                            map.tiles[front_x][front_y] = TileState(
                                TileType.BLOCKED, observed=True
                            )
                        else:
                            map.tiles[front_x][front_y] = TileState(
                                TileType.EMPTY, observed=True
                            )

                    if requested_move:
                        if looking_off_map:
                            print("Move off map")
                        elif map.tiles[front_x][front_y].type == TileType.BLOCKED:
                            print("Move blocked")
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
