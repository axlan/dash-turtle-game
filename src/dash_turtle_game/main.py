import asyncio
import time
import math
from threading import Thread
from queue import Queue

import pygame
import WonderPy.core.wwMain
from WonderPy.core.wwConstants import WWRobotConstants
from WonderPy.components.wwMedia import WWMedia
from WonderPy.core.wwRobot import WWRobot

from .map import GameMap, WindowEvent, TurtlePose

# TODO:
# Auto reconnect to fix initial failed start
# Fix coordinates not lining up

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


START_TILE = (2, 2)
START_THETA = 90
GOAL_TILE = (1, 3)
MAP_SIZE_TILES = (6,6)
TILE_SIZE_CM = 30.48
TILE_SIZE_PIXELS = 64

TURN_TIME = 4

POSE_MODE = WWRobotConstants.WWPoseMode.WW_POSE_MODE_RELATIVE_MEASURED



def normalize_ang(angle: float) -> float:
    return angle % 360.0


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

async def stop_loop():
    loop = asyncio.get_event_loop()
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

class RobotInterface:

    def __init__(self) -> None:
        self.is_running = True
        self.ctrl_thread = None
        self.queue = Queue()
        self.ctrl_thread: Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        

    async def on_connect(self, robot:WWRobot):
        self.loop = asyncio.get_event_loop()
        print("Starting a task for %s." % (robot.name))
        self.ctrl_thread = Thread(target=self.robot_ctrl, args=(robot,), name='robot_ctrl')
        self.ctrl_thread.start()

    def on_sensors(self, robot):
        self.queue.put_nowait(1)

    # Can write this as either asyncio, or Thread. With asyncio, I can be sure
    # that the context won't switch while using a piece of data, but I can't
    # call the blocking WWRobot functions. To keep things simple, I'll keep it
    # multithreaded.
    def robot_ctrl(self, robot: WWRobot):
        #robot.commands.body.do_forward(10, 3)
        robot.commands.RGB.stage_all(1,0,0)
        map = GameMap(num_map_tiles=MAP_SIZE_TILES,
                      goal_tile=GOAL_TILE,
                      tile_size_pixels=TILE_SIZE_PIXELS)
        
        position_scale = TILE_SIZE_PIXELS / TILE_SIZE_CM
        position_offset = (TILE_SIZE_CM * (START_TILE[0] + 0.5), TILE_SIZE_CM * (START_TILE[1] + 0.5))

        self.queue.get()
        start_pose = TurtlePose(robot.sensors.pose.x, robot.sensors.pose.y, robot.sensors.pose.degrees)

        last_print = time.time()

        try:
            while self.is_running:

                # print(f'raw: {robot.sensors.pose.x}, {robot.sensors.pose.y}, {robot.sensors.pose.degrees + 90}')

                bot_x = robot.sensors.pose.x - start_pose.x
                bot_y = robot.sensors.pose.y - start_pose.y
                 
                bot_theta = normalize_ang(robot.sensors.pose.degrees - start_pose.theta)
                # -90 to handle turtle bot facing in +y direction
                rot_x, rot_y = rotate_point(bot_x, bot_y, START_THETA - start_pose.theta - 90)
                map.turtle_pose.x = (position_offset[0] + rot_x) * position_scale
                map.turtle_pose.y = (position_offset[1] + rot_y) * position_scale
                # +90 to Handle turtle bot facing in +y direction
                map.turtle_pose.theta = START_THETA + bot_theta + 90

                # print(f'map: {rot_x}, {rot_y}, {START_THETA + bot_theta}')

                if time.time() - last_print > 2:
                    print(robot.sensors.distance_rear)
                    last_print = time.time()


                for event in map.GetWindowEvents():
                    if event == WindowEvent.QUIT:
                        if self.loop is not None:
                            asyncio.run_coroutine_threadsafe(stop_loop(), self.loop)
                        break
                    elif event == WindowEvent.LEFT:
                        robot.commands.body.stage_pose(0, 0, 90, TURN_TIME, mode=POSE_MODE)
                    elif event == WindowEvent.RIGHT:
                        robot.commands.body.stage_pose(0, 0, -90, TURN_TIME, mode=POSE_MODE)
                    elif event == WindowEvent.UP:
                        robot.commands.body.stage_pose(0, TILE_SIZE_CM, 0, TURN_TIME, mode=POSE_MODE)

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
