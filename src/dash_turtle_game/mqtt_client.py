from collections.abc import Iterator
import json
from queue import Queue
import logging

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.reasoncodes import ReasonCode

from .constants import CmdEvent

logger = logging.getLogger(__name__)


CONTROLLER_TOPIC = "controller/buttons_pressed"


class MQTTCommandClient:
    def __init__(self, host: str, port: int = 1883) -> None:
        self._host = host
        self._port = port

        self._messages: Queue[CmdEvent] = Queue()

        self._client = mqtt.Client(CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self.pressed_buttons: list[str] = []

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata,
        flags,
        reason_code: ReasonCode,
        properties,
    ) -> None:
        if reason_code == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Connected to broker at {self._host}:{self._port}")
            client.subscribe(CONTROLLER_TOPIC)
        else:
            logger.warning(
                f"Connection failed (rc={reason_code}), will attempt reconnect"
            )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata,
        disconnect_flags,
        reason_code: ReasonCode,
        properties,
    ) -> None:
        logger.info("Disconnected from broker")
        if reason_code != mqtt.MQTT_ERR_SUCCESS:
            # Unexpected disconnect — paho will attempt to reconnect automatically
            # when loop_start() is used (reconnect_delay_set can tune back-off).
            logger.warning(
                f"Unexpected disconnection (rc={reason_code}), will attempt reconnect"
            )

    def _on_message(
        self, client: mqtt.Client, userdata, message: mqtt.MQTTMessage
    ) -> None:
        logger.debug(f"Message received on {message.topic}: {message.payload}")
        json_str = message.payload.decode("ascii")
        if message.topic == CONTROLLER_TOPIC:
            new_buttons = json.loads(json_str)
            for val in new_buttons:
                if val not in self.pressed_buttons:
                    if val == "A":
                        self._messages.put_nowait(CmdEvent.LEFT)
                    elif val == "B":
                        self._messages.put_nowait(CmdEvent.UP)
                    elif val == "C":
                        self._messages.put_nowait(CmdEvent.RIGHT)
            self.pressed_buttons = new_buttons

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self, timeout: float = 10.0) -> None:
        """Connect to the broker and block until the connection is established.

        Raises ``ConnectionError`` if the broker rejects the connection or if
        the timeout expires before a response is received.
        """
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()

    def disconnect(self) -> None:
        """Gracefully disconnect from the broker and stop the network loop."""
        self._client.disconnect()
        self._client.loop_stop()

    def get_messages(self) -> Iterator[CmdEvent]:
        """Return a snapshot of all messages received so far and clear the buffer."""
        while not self._messages.empty():
            yield self._messages.get_nowait()

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "MQTTCommandClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()


# --- Example Usage ---

if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.DEBUG)

    with MQTTCommandClient(
        host="192.168.1.110", port=1883
    ) as client:
        print("Listening for messages for 5 seconds...")

        # Poll for messages in a loop
        start_time = time.time()
        while time.time() - start_time < 5:
            messages = client.get_messages()
            if messages:
                for msg in messages:
                    print(f"  {msg.name}")
            else:
                print("No messages")
            time.sleep(0.1)  # Poll every 100ms

        print("Done listening")
