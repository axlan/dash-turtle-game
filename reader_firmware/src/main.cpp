#include <stdint.h>

#include <Adafruit_PN532.h>
#include <PubSubClient.h>
#include <WiFiManager.h>

#define RESET_PIN 18

static constexpr const char *DEVICE_NAME = "CardReader";
static constexpr const char *MQTT_SERVER = "192.168.1.110";
static constexpr const char *MQTT_TOPIC = "card_reader/card_text";

WiFiClient espClient;
PubSubClient mqtt_client(espClient);

char card_text[64];

uint8_t last_uid[] = {0, 0, 0, 0, 0, 0, 0};

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

Adafruit_PN532 nfc(RESET_PIN, &Serial2); // Hardware Serial
void setup(void)
{
  // has to be fast to dump the entire memory contents!
  Serial.begin(115200);

  Serial.println("Looking for PN532...");

  nfc.begin();

  uint32_t versiondata = nfc.getFirmwareVersion();
  if (!versiondata)
  {
    Serial.print("Didn't find PN53x board");
    while (1)
    {
      delay(1000); // halt
    };
  }
  // Got ok data, print it out!
  Serial.print("Found chip PN5");
  Serial.println((versiondata >> 24) & 0xFF, HEX);
  Serial.print("Firmware ver. ");
  Serial.print((versiondata >> 16) & 0xFF, DEC);
  Serial.print('.');
  Serial.println((versiondata >> 8) & 0xFF, DEC);

  while (true)
  {
    // WiFiManager, Local intialization. Once its business is done, there is no need to keep it around
    WiFiManager wm;

    // reset settings - wipe stored credentials for testing
    // these are stored by the esp library
    // wm.resetSettings();

    // Automatically connect using saved credentials,
    // if connection fails, it starts an access point with the specified name ( "AutoConnectAP"),
    // if empty will auto generate SSID, if password is blank it will be anonymous AP (wm.autoConnect())
    // then goes into a blocking loop awaiting configuration and will return success result

    // res = wm.autoConnect(); // auto generated AP name from chipid
    // res = wm.autoConnect("AutoConnectAP"); // anonymous ap
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

void parseTextRecord(uint8_t *payload, uint32_t length)
{
  if (length < 1)
    return;

  uint8_t statusByte = payload[0];
  bool utf16 = (statusByte >> 7) & 1;     // 0 = UTF-8, 1 = UTF-16
  uint8_t langLength = statusByte & 0x3F; // Language code length

  if (length < 1u + langLength)
    return;

  // Extract language code (e.g. "en")
  char lang[8] = {0};
  for (uint8_t i = 0; i < langLength && i < 7; i++)
  {
    lang[i] = (char)payload[1 + i];
  }

  // Extract text
  uint32_t textOffset = 1 + langLength;
  uint32_t textLength = length - textOffset;

  Serial.print("Language: ");
  Serial.println(lang);
  Serial.print("Encoding: ");
  Serial.println(utf16 ? "UTF-16" : "UTF-8");
  Serial.print("Text: ");

  if (utf16)
  {
    // Basic UTF-16 handling - print ASCII-range chars only
    for (uint32_t i = 0; i + 1 < textLength; i += 2)
    {
      uint16_t ch = ((uint16_t)payload[textOffset + i + 1] << 8) | payload[textOffset + i];
      if (ch < 128)
        Serial.print((char)ch);
    }
  }
  else
  {
    for (uint32_t i = 0; i < textLength; i++)
    {
      Serial.print((char)payload[textOffset + i]);
    }
    memcpy(card_text, payload + textOffset, textLength);
  }
  Serial.println();
}

void parseNDEFMessage(uint8_t *msg, uint16_t length)
{
  uint16_t offset = 0;

  while (offset < length)
  {
    if (offset >= length)
      break;

    uint8_t flags = msg[offset++];
    bool mb = (flags >> 7) & 1; // Message Begin
    bool me = (flags >> 6) & 1; // Message End
    bool cf = (flags >> 5) & 1; // Chunk Flag
    bool sr = (flags >> 4) & 1; // Short Record (payload length is 1 byte)
    bool il = (flags >> 3) & 1; // ID Length present
    uint8_t tnf = flags & 0x07; // Type Name Format

    if (offset >= length)
      break;
    uint8_t typeLength = msg[offset++];

    uint32_t payloadLength;
    if (sr)
    {
      payloadLength = msg[offset++];
    }
    else
    {
      payloadLength = ((uint32_t)msg[offset] << 24) |
                      ((uint32_t)msg[offset + 1] << 16) |
                      ((uint32_t)msg[offset + 2] << 8) |
                      (uint32_t)msg[offset + 3];
      offset += 4;
    }

    uint8_t idLength = 0;
    if (il)
    {
      idLength = msg[offset++];
    }

    // Read type
    char type[16] = {0};
    for (uint8_t t = 0; t < typeLength && t < 15; t++)
    {
      type[t] = (char)msg[offset++];
    }

    // Skip ID
    offset += idLength;

    // TNF 0x01 = Well Known, type "T" = Text record
    if (tnf == 0x01 && typeLength == 1 && type[0] == 'T')
    {
      parseTextRecord(msg + offset, payloadLength);
    }
    else
    {
      Serial.print("Skipping record, TNF: 0x");
      Serial.print(tnf, HEX);
      Serial.print(", Type: ");
      Serial.println(type);
    }

    offset += payloadLength;

    if (me)
      break; // Last record in message
  }
}

void parseNDEF(uint8_t *data, uint16_t length)
{
  uint16_t i = 0;

  while (i < length)
  {
    uint8_t tlvType = data[i++];

    if (tlvType == 0x00)
      continue; // NULL TLV, skip
    if (tlvType == 0xFE)
      break; // Terminator TLV, stop

    if (i >= length)
      break;
    uint16_t tlvLength = data[i++];

    // 3-byte length encoding (for payloads > 254 bytes)
    if (tlvLength == 0xFF)
    {
      if (i + 2 >= length)
        break;
      tlvLength = ((uint16_t)data[i] << 8) | data[i + 1];
      i += 2;
    }

    if (tlvType == 0x03)
    { // NDEF Message TLV
      Serial.println("Found NDEF message TLV");
      parseNDEFMessage(data + i, tlvLength);
    }

    i += tlvLength;
  }
}

void loop(void)
{
  uint8_t success;                       // Flag to check if there was an error with the PN532
  uint8_t uid[] = {0, 0, 0, 0, 0, 0, 0}; // Buffer to store the returned UID
  uint8_t uidLength;                     // Length of the UID (4 or 7 bytes depending on ISO14443A card type)
  uint8_t currentblock;                  // Counter to keep track of which block we're on
  bool authenticated = false;            // Flag to indicate if the sector is authenticated
  uint8_t data[16];                      // Array to store block data during reads
  uint8_t ndefData[48];                  // 3 blocks * 16 bytes

  // Keyb on NDEF and Mifare Classic should be the same
  uint8_t keyuniversal[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

  // Wait for an ISO14443A type cards (Mifare, etc.).  When one is found
  // 'uid' will be populated with the UID, and uidLength will indicate
  // if the uid is 4 bytes (Mifare Classic) or 7 bytes (Mifare Ultralight)
  success = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength);

  if (success)
  {
    // Display some basic information about the card
    Serial.println("Found an ISO14443A card");
    Serial.print("  UID Length: ");
    Serial.print(uidLength, DEC);
    Serial.println(" bytes");
    Serial.print("  UID Value: ");
    nfc.PrintHex(uid, uidLength);
    Serial.println("");

    if (uidLength == 4)
    {

      // We probably have a Mifare Classic card ...
      Serial.println("Seems to be a Mifare Classic card (4 byte UID)");

      uint8_t key[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
      // Authenticate ONCE for sector 1 (covers blocks 4, 5, 6)
      bool ok = nfc.mifareclassic_AuthenticateBlock(uid, uidLength, 4, 1, key);
      Serial.println(ok ? "Auth OK" : "Auth FAIL");

      if (ok)
      {
        // Now read all three blocks without re-authenticating
        for (uint8_t block = 4; block <= 6; block++)
        {
          if (!nfc.mifareclassic_ReadDataBlock(block, data))
          {
            Serial.print("Read failed on block ");
            Serial.println(block);
            return;
          }
          nfc.PrintHexChar(data, 16);
          memcpy(ndefData + (block - 4) * 16, data, 16);
        }

        // Parse NDEF from the raw bytes
        // MIFARE Classic NDEF starts with a MAD (Memory Application Directory)
        // but the TLV-wrapped NDEF message in sector 1 looks like:
        //   0x03 <length> <NDEF message bytes> 0xFE (terminator)
        memset(card_text, 0, sizeof(card_text));
        parseNDEF(ndefData, sizeof(ndefData));
        if (strlen(card_text) > 0)
        {
          // Convert UID to hex string
          char uid_hex[15] = {0};  // Max 7 bytes * 2 chars + null terminator
          for (uint8_t i = 0; i < uidLength; i++)
          {
            sprintf(uid_hex + i * 2, "%02X", uid[i]);
          }

          // Create JSON payload: {"uid": "UID_AS_HEX", "txt": "card_text"}
          char json_payload[256] = {0};
          sprintf(json_payload, "{\"uid\": \"%s\", \"txt\": \"%s\"}", uid_hex, card_text);

          // mosquitto_sub -h 192.168.1.110 -t "card_reader/card_text"
          if (!mqtt_client.publish(MQTT_TOPIC, json_payload))
          {
            Serial.println("Json pub failed.");
          }
        }
      }
    }
    else
    {
      Serial.println("Ooops ... this doesn't seem to be a Mifare Classic card!");
    }
  }

  if (!mqtt_client.connected())
  {
    reconnect();
  }

  mqtt_client.loop();
}