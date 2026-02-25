#include <stdint.h>

#include <PubSubClient.h>
#include <WiFiManager.h>

#include "PN532/PN532_HSU/PN532_HSU.h"
#include "PN532/PN532/PN532.h"
#include "PN532/NDEF/NfcAdapter.h"

static constexpr const char *DEVICE_NAME = "CardReader";
static constexpr const char *MQTT_SERVER = "192.168.1.110";
static constexpr const char *MQTT_TOPIC = "card_reader/card_text";

PN532_HSU pn532(Serial2);
NfcAdapter nfc = NfcAdapter(pn532);

WiFiClient espClient;
PubSubClient mqtt_client(espClient);

bool reconnect()
{
    static long long next_reconnect = 0;
    if (next_reconnect > millis() || !WiFi.isConnected())
    {
        return false;
    }

    mqtt_client.setServer(MQTT_SERVER, 1883);
    Serial.print("Attempting MQTT connection...");
    // Attempt to connect
    if (mqtt_client.connect(DEVICE_NAME))
    {
        Serial.println("connected");
        return true;
    }
    else
    {
        Serial.print("failed, rc=");
        Serial.print(mqtt_client.state());
        Serial.println(" try again in 5 seconds");
        // Wait 5 seconds before retrying
        next_reconnect = millis() + 5000;
    }

    return false;
}

void setup(void)
{
    // has to be fast to dump the entire memory contents!
    Serial.begin(115200);

    Serial.println("Looking for PN532...");

    nfc.begin();

    while (true)
    {
        // WiFiManager, Local intialization. Once its business is done, there is no need to keep it around
        WiFiManager wm;

        // Automatically connect using saved credentials,
        // if connection fails, it starts an access point with the specified name ( "AutoConnectAP"),
        // if empty will auto generate SSID, if password is blank it will be anonymous AP (wm.autoConnect())
        // then goes into a blocking loop awaiting configuration and will return success result
        if (wm.autoConnect(DEVICE_NAME))
        {
            Serial.print("Wifi connected, IP address: ");
            Serial.println(WiFi.localIP());
            break;
        }
        else
        {
            Serial.print("Failed retrying.");
        }
    }

    // client.setSocketTimeout(0xFFFF);
    mqtt_client.setKeepAlive(0xFFFF);

    Serial.println("Waiting for an ISO14443A Card ...");
}

void loop(void)
{
    static bool card_read = false;
    if (nfc.tagPresent())
    {
        if (!card_read)
        {
            card_read = true;
            NfcTag tag = nfc.read();
            tag.print();

            if (tag.hasNdefMessage() && tag.getNdefMessage().getRecordCount() == 1)
            {
                auto record = tag.getNdefMessage().getRecord(0);
                if (record.getTypeLength() == 1 && record.getType()[0] == 'T' && record.getPayloadLength() > 3)
                {
                    byte payload[64];
                    record.getPayload(payload);

                    String json_payload = "{\"uid\": \"" + tag.getUidString() + "\", \"txt\": \"" +
                                          String((char *)payload + 3, record.getPayloadLength() - 3) + "\"}";

                    // mosquitto_sub -h 192.168.1.110 -t "card_reader/card_text"
                    if (!mqtt_client.publish(MQTT_TOPIC, json_payload.c_str()))
                    {
                        Serial.println("Json pub failed.");
                    }
                }
            }
        }
    }
    else
    {
        card_read = false;
    }

    if (!mqtt_client.connected())
    {
        reconnect();
    }

    mqtt_client.loop();
}