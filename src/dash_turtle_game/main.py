import time
from threading import Thread

from .map import ConnectionState, GameManager
from .constants import CmdEvent, TileType, Settings
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
    BOT_CONNECT_TIMEOUT_SEC=10.0,
)

# TODO:
# Tune obstacle detection
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


# Can write this as either asyncio, or Thread. With asyncio, I can be sure
# that the context won't switch while using a piece of data, but I can't
# call the blocking WWRobot functions. To keep things simple, I'll keep it
# multithreaded.
def robot_ctrl(sys_ctrl: 'SystemControl'):
    assert sys_ctrl.bot_intr is not None

    bot_inter = sys_ctrl.bot_intr
    game_gui = sys_ctrl.game_gui
    mqtt_client = sys_ctrl.mqtt_client

    start_time = time.time()
    sensors = None
    
    while True:
        try:
            sensors = bot_inter.sensor_queue.get(timeout=0.1)
            break
        except:
            if time.time() - start_time > SETTINGS.BOT_CONNECT_TIMEOUT_SEC:
                break
        events = list(game_gui.get_window_events())
        if CmdEvent.QUIT in events:
            sys_ctrl.stop()
            return
        elif CmdEvent.TOGGLE_CONNECT in events:
            bot_inter.stop()
            return

    if sensors is None or bot_inter.robot_ctrl is None:
        print("Robot interface terminated")
        return
    
    with game_gui.get_map() as locked_map:
        locked_map.connected_state = ConnectionState.CONNECTED

    robot_ctrl = bot_inter.robot_ctrl

    # robot.commands.body.do_forward(10, 3)
    robot_ctrl.set_bot_rgb()
    last_print = time.time()

    celebrated = False
    last_idle = False
    moving_forward = False

    queue_cmds = False
    cmd_queue: list[CmdEvent] = []

    try:
        while True:
            try:
                sensors = bot_inter.sensor_queue.get(timeout=1)
            except:
                bot_inter.stop()
                return

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

            map_pose = robot_ctrl.get_pose()
            map_x = int(map_pose.x)
            map_y = int(map_pose.y)

            with game_gui.get_map() as locked_map:
                locked_map.set_all_tiles_unobserved()
                locked_map.turtle_pose = map_pose
                locked_map.set_observed_tile(map_x, map_y, TileType.EMPTY)
            
            new_cmds = list(game_gui.get_window_events())
            if mqtt_client is not None:
                new_cmds += list(mqtt_client.get_messages())

            if CmdEvent.QUIT in new_cmds:
                sys_ctrl.stop()
                return
            elif CmdEvent.TOGGLE_CONNECT in new_cmds:
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

            if (map_x >= SETTINGS.MAP_SIZE_TILES[0]
                or map_y >= SETTINGS.MAP_SIZE_TILES[1]
                or map_x < 0
                or map_y < 0
            ):
                # TODO: figure out what causes this. Sensor parsing error? Rollover?
                print("Unexpected map position")
                print(sensors)
                print(map_pose)
                exit(1)
                continue

            if sensors.is_idle:
                if not celebrated and game_gui.get_tile(map_x, map_y).type == TileType.GOAL:
                    # This blocks the GUI, should probably not, but not a huge issue.
                    robot_ctrl.do_celebrate()
                    celebrated = True

                if map_pose.theta < 45 or map_pose.theta > (360 - 45):
                    front_x = map_x + 1
                    front_y = map_y
                elif map_pose.theta < 135:
                    front_x = map_x
                    front_y = map_y + 1
                elif map_pose.theta < 225:
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
                    with game_gui.get_map() as locked_map:
                        if (
                            sensors.distance_front_left_facing
                            > SETTINGS.FRONT_DETECTION_THRESHOLD
                            and sensors.distance_front_right_facing
                            > SETTINGS.FRONT_DETECTION_THRESHOLD
                        ):
                            locked_map.set_observed_tile(front_x, front_y, TileType.BLOCKED)
                        else:
                            locked_map.set_observed_tile(front_x, front_y, TileType.EMPTY)

                if requested_move:
                    if looking_off_map:
                        print("Move off map")
                        robot_ctrl.play_sound(BotSounds.NO_WAY)
                    elif game_gui.get_tile(front_x, front_y).type == TileType.BLOCKED:
                        print("Move blocked")
                        robot_ctrl.play_sound(BotSounds.NO_WAY)
                    else:
                        robot_ctrl.forward()
                        moving_forward = True

            if time.time() - last_print > SETTINGS.TIME_BETWEEN_PRINT_SEC:
                # print(f'{int(robot.sensors.distance_rear):3},{int(robot.sensors.distance_front_right_facing):3},{int(robot.sensors.distance_front_left_facing):3}')
                # print(f'{robot.sensors.distance_rear}')
                # if sensors.is_idle:
                #     print(f'map: {map_x}, {map_y}, {map_pose.theta}')
                #     print(f'front: {front_x}, {front_y}')
                # print(robot.sensors.distance_front_left_facing, robot.sensors.distance_front_right_facing)
                print(sensors)
                print(map_pose)
                if len(cmd_queue) > 0:
                    print(cmd_queue)
                last_print = time.time()

    except KeyboardInterrupt:
        pass


class SystemControl:
    def __init__(self) -> None:
        self.mqtt_client = None
        if SETTINGS.MQTT_BROKER_ADDR:
            mqtt_client = MQTTCommandClient(SETTINGS.MQTT_BROKER_ADDR)
            mqtt_client.connect()

        self.game_gui = GameManager(SETTINGS)
        self.running = True
        self.bot_intr: RobotInterface | None = None

    def main(self):
        is_connecting = False
        while self.running:
            try:
                while not is_connecting:
                    for event in self.game_gui.get_window_events():
                        if event == CmdEvent.TOGGLE_CONNECT:
                            with self.game_gui.get_map() as locked_map:
                                locked_map.connected_state = ConnectionState.CONNECTING
                            is_connecting = True
                        elif event == CmdEvent.QUIT:
                            raise KeyboardInterrupt()
                    time.sleep(0.1)
            except KeyboardInterrupt:
                self.stop()
                return

            # Get start and goal from map.
            self.bot_intr = RobotInterface(self.game_gui.get_updated_settings())
            ctrl_thread = Thread(target=robot_ctrl, args=(self,))
            ctrl_thread.start()

            # This blocks until the connection to the bot is ended.
            self.bot_intr.run()
            self.bot_intr = None

            ctrl_thread.join()
            with self.game_gui.get_map() as locked_map:
                locked_map.connected_state = ConnectionState.IDLE
            is_connecting = False

    def stop(self):
        self.running = False
        if self.bot_intr is not None:
            self.bot_intr.stop()
            self.bot_intr = None
        if self.mqtt_client is not None:
            self.mqtt_client.disconnect()
        self.game_gui.stop()

if __name__ == "__main__":
    SystemControl().main()
