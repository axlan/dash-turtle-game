# Turtle Bot Game for Dash Bot

A Python-based game controller for a Dash robot that combines real-time robotics control with a tile-based game interface.

## Overview

This project enables a Dash robot to navigate a grid-based game environment. Players can queue movement commands via keyboard, controller, or NFC cards, and the robot executes them while the game tracks progress toward a goal tile.

## Components

### Game Interface (dash_turtle_game)

- **Map Display** (map.py): Pygame-based GUI showing the game board with the turtle's position, observed/unobserved tiles, obstacles, and goal location. Supports drag-and-drop for repositioning the turtle and goal.

- **Card Queue Widget** (card_gui.py): Visual queue of queued movement commands (LEFT, RIGHT, UP) with scrolling and active card highlighting.

- **Main Controller** (main.py): Orchestrates the game loop, connects to the robot, processes sensor data, and updates the map based on obstacle detection.

### Robot Interface

- **Real Robot** (bot_interface.py): Controls a real Dash robot via WonderPy library, handling pose transformations between virtual game coordinates and robot coordinates. Implements forward/backward movement and rotation with RGB LED and sound feedback.

- **Simulated Robot** (sim_bot_interface.py): Virtual robot for testing without hardware, simulating movement and limited sensor data.

### Communication

- **MQTT Client** (mqtt_client.py): Subscribes to card reader and controller topics for remote command input.

Setting this up is beyond the scope of this README, but the basic idea is that it connects to a broker server to get events from IoT devices.

The controller is <https://github.com/axlan/toy_controller>, though it would be easy to add real controller support through PyGame.

The reader is a quick and dirty ESP32 firmware in the `reader_firmware` directory. This is just an ESP32 connected to a PN532 NFC reader.

## Coordinate Systems

The project manages three coordinate systems:

- **Pygame**: Pixel-based screen coordinates (standard Pygame orientation with origin at top left)
- **Virtual Game**: Unit-less tile coordinates where each tile is 1×1 with origin at bottom left
- **Robot**: Centimeter-based coordinates with orientation offset from virtual space

The virtual game is the main system used by the controller. The robot and map classes do the transformations to their respective coordinates.

## Getting Started

With `uv`:
```bash
uv sync
uv run dash-turtle-game
```

With `pip`:
```bash
pip install .
python -m src.dash_turtle_game.main
```

1. Customize the `SETTINGS` at the top of `src/dash_turtle_game/main.py`
2. When run, the GUI lets you set the turtle start position and orientation and the goal location with the mouse
3. [Optional] Queue movement commands via keyboard (arrow keys), NFC cards, or controller
4. Press connect to start controlling the robot
  - If not running a simulation the PC will attempt to do a BLE scan for a Dash robot. See [WonderPy/core/wwBTLEMgr.py](https://github.com/axlan/WonderPy/blob/bdeb3e9cf36b054469ad6cc84990f4593474902c/WonderPy/core/wwBTLEMgr.py#L78) for command line parameters to control this process.
5. Robot executes queued commands. It will stop if any command would make it run into an obstacle or off the map.
6. Further commands can be used to drive the robot around in realtime.
4. Reaching the goal makes the robot do a little dance
5. Disconnecting goes back to step 2
