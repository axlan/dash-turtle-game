import time
from threading import Thread

from .map import GameMap
from .constants import CmdEvent, TileType, TileState, Settings
from .mqtt_client import MQTTCommandClient
from .bot_interface import RobotInterface, BotSounds

SETTINGS = Settings(
    START_TILE=(3, 5),
    START_THETA=90,
    GOAL_TILE=(5, 0),
    MAP_SIZE_TILES=(6, 6),
    TILE_SIZE_CM=30.48,
    TILE_SIZE_PIXELS=128,
    FRONT_DETECTION_THRESHOLD=12,
    CRASH_DETECTION_THRESHOLD=64,
    TURN_TIME=4.0,
    FORWARD_TIME=4.0,
    TIME_BETWEEN_PRINT_SEC=2.0,
    MQTT_BROKER_ADDR="192.168.1.110",
)

# TODO:
# Tune obstacle detection
# Decouple running GUI with robot sensor updates
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


def set_observed_tile(map: GameMap, x: int, y: int, tile: TileType):
    if map.tiles[x][y].type != TileType.GOAL:
        map.tiles[x][y] = TileState(tile, observed=True, text=map.tiles[x][y].text)
    else:
        map.tiles[x][y].observed = True


# Can write this as either asyncio, or Thread. With asyncio, I can be sure
# that the context won't switch while using a piece of data, but I can't
# call the blocking WWRobot functions. To keep things simple, I'll keep it
# multithreaded.
def robot_ctrl(bot_inter: RobotInterface, mqtt_client: MQTTCommandClient | None):

    sensors = bot_inter.sensor_queue.get()
    if sensors is None or bot_inter.robot_ctrl is None:
        print("Robot interface terminated")
        return

    robot_ctrl = bot_inter.robot_ctrl

    # robot.commands.body.do_forward(10, 3)
    robot_ctrl.set_bot_rgb()
    map = GameMap(
        num_map_tiles=SETTINGS.MAP_SIZE_TILES,
        tile_size_pixels=SETTINGS.TILE_SIZE_PIXELS,
    )
    last_print = time.time()

    map.tiles[SETTINGS.GOAL_TILE[0]][SETTINGS.GOAL_TILE[1]] = TileState(TileType.GOAL)
    celebrated = False
    last_idle = False
    moving_forward = False

    queue_cmds = False
    cmd_queue: list[CmdEvent] = []

    try:
        while True:
            sensors = bot_inter.sensor_queue.get()
            if sensors is None:
                print("Robot interface terminated")
                return
            robot_ctrl.update_sensors(sensors)

            if last_idle and not sensors.is_idle:
                robot_ctrl.set_main_button_led(False)
            elif not last_idle and sensors.is_idle:
                robot_ctrl.set_main_button_led(True)
                moving_forward = False
            last_idle = sensors.is_idle

            if moving_forward:
                if (
                    sensors.distance_front_left_facing
                    > SETTINGS.CRASH_DETECTION_THRESHOLD
                    or sensors.distance_front_right_facing
                    > SETTINGS.CRASH_DETECTION_THRESHOLD
                ):
                    moving_forward = False
                    robot_ctrl.stop()
                    robot_ctrl.forward(reverse=True)

            map.turtle_pose = robot_ctrl.get_pose()

            new_cmds = list(map.GetWindowEvents())
            if mqtt_client is not None:
                new_cmds += list(mqtt_client.get_messages())

            if CmdEvent.QUIT in new_cmds:
                print("GUI Exited...")
                bot_inter.stop()
                return

            requested_move = False
            if queue_cmds:
                cmd_queue += new_cmds
            else:
                cur_cmd = CmdEvent.NONE
                if len(cmd_queue) > 0:
                    if sensors.is_idle:
                        cur_cmd = cmd_queue.pop(0)
                elif len(new_cmds) > 0:
                    if not sensors.is_idle:
                        print("Wait for previous command to complete.")
                        robot_ctrl.play_sound(BotSounds.SIGH)
                    else:
                        # Only handle first event if multiple received in same update.
                        cur_cmd = new_cmds[0]

                if cur_cmd in (CmdEvent.LEFT, CmdEvent.RIGHT):
                    turn_clockwise = cur_cmd == CmdEvent.RIGHT
                    robot_ctrl.turn(turn_clockwise)
                elif cur_cmd == CmdEvent.UP:
                    requested_move = True

            for i, t in enumerate(map.GetAllTiles()):
                t.observed = False

            # Set all tiles to be unobserved and with their letter.
            letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            for c, col_tiles in enumerate(map.tiles):
                for r, t in enumerate(col_tiles):
                    i = (
                        c
                        + (SETTINGS.MAP_SIZE_TILES[1] - r - 1)
                        * SETTINGS.MAP_SIZE_TILES[0]
                    )
                    t.observed = False
                    t.text = letters[i]

            map_x = int(map.turtle_pose.x)
            map_y = int(map.turtle_pose.y)

            if (map_x >= SETTINGS.MAP_SIZE_TILES[0]
                or map_y >= SETTINGS.MAP_SIZE_TILES[1]
                or map_x < 0
                or map_y < 0
            ):
                # TODO: figure out what causes this. Sensor parsing error? Rollover?
                print("Unexpected map position")
                print(sensors)
                print(map.turtle_pose)
                exit(1)
                continue

            set_observed_tile(map, map_x, map_y, TileType.EMPTY)

            if sensors.is_idle:
                if not celebrated and map.tiles[map_x][map_y].type == TileType.GOAL:
                    # This blocks the GUI, should probably not, but not a huge issue.
                    robot_ctrl.do_celebrate()
                    celebrated = True

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
                    or front_x >= SETTINGS.MAP_SIZE_TILES[0]
                    or front_y < 0
                    or front_y >= SETTINGS.MAP_SIZE_TILES[1]
                )

                if not looking_off_map:
                    if (
                        sensors.distance_front_left_facing
                        > SETTINGS.FRONT_DETECTION_THRESHOLD
                        and sensors.distance_front_right_facing
                        > SETTINGS.FRONT_DETECTION_THRESHOLD
                    ):
                        set_observed_tile(map, front_x, front_y, TileType.BLOCKED)
                    else:
                        set_observed_tile(map, front_x, front_y, TileType.EMPTY)

                if requested_move:
                    if looking_off_map:
                        print("Move off map")
                        robot_ctrl.play_sound(BotSounds.NO_WAY)
                    elif map.tiles[front_x][front_y].type == TileType.BLOCKED:
                        print("Move blocked")
                        robot_ctrl.play_sound(BotSounds.NO_WAY)
                    else:
                        robot_ctrl.forward()
                        moving_forward = True

            if time.time() - last_print > SETTINGS.TIME_BETWEEN_PRINT_SEC:
                # print(f'{int(robot.sensors.distance_rear):3},{int(robot.sensors.distance_front_right_facing):3},{int(robot.sensors.distance_front_left_facing):3}')
                # print(f'{robot.sensors.distance_rear}')
                # if sensors.is_idle:
                #     print(f'map: {map_x}, {map_y}, {map.turtle_pose.theta}')
                #     print(f'front: {front_x}, {front_y}')
                # print(robot.sensors.distance_front_left_facing, robot.sensors.distance_front_right_facing)
                print(sensors)
                print(map.turtle_pose)
                if len(cmd_queue) > 0:
                    print(cmd_queue)
                last_print = time.time()

            map.Draw()
    except KeyboardInterrupt:
        pass

    map.Stop()


def main():
    mqtt_client = None
    if SETTINGS.MQTT_BROKER_ADDR:
        mqtt_client = MQTTCommandClient(SETTINGS.MQTT_BROKER_ADDR)
        mqtt_client.connect()
    bot_intr = RobotInterface(SETTINGS)
    ctrl_thread = Thread(target=robot_ctrl, args=(bot_intr, mqtt_client))
    ctrl_thread.start()

    bot_intr.run()

    ctrl_thread.join()
    if mqtt_client is not None:
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
