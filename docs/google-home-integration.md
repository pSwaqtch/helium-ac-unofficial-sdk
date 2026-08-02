# Google Assistant & Home Assistant Integration

This guide outlines the best architectural approaches for integrating the Helium AC unofficial SDK with Google Assistant (Google Home / Gemini) using Home Assistant as the translation layer.

## Why Home Assistant?

Building a native "Google Smart Home Action" from scratch requires setting up an OAuth2 server and handling complex Google JSON intents (SYNC, QUERY, EXECUTE). It's a massive development effort for a single air conditioner. 

**Home Assistant** acts as the perfect middleman. It can easily communicate with the Helium API using simple REST commands and has built-in, native bridging to Google Assistant.

---

## 1. The Absolute Best Way: Local Hardware (Recommended)

The most reliable, lowest-latency, and future-proof setup involves running Home Assistant on a physical device (like a Raspberry Pi or an old laptop) in the same room as your AC.

### Why this is the best:
* **Immunity to the Cloud:** The vendor's cloud app is notoriously unreliable. If you use the `cloud` transport, you still rely on Helium's AWS servers. If the company shuts down their servers or changes authentication, your setup breaks.
* **100% Local Reliability:** By using the local `ble` (Bluetooth) transport, commands go directly from your local server to the AC through the air. It works instantly and forever, even if your internet goes down.
* **Easy Google Integration:** You can use **Nabu Casa** (Home Assistant Cloud) for a 1-click integration with Google Assistant, without exposing any local network ports to the public internet.

---

## 2. The "Zero Hardware" Way: Cloud Server (Oracle VPC)

If you absolutely do not want to buy or maintain a physical server in your house, you can host both this SDK and Home Assistant on a free cloud instance (like an Oracle VPC).

### How it works:
1. You run this project's API on the Oracle VPS using the `cloud` transport.
2. You run **Home Assistant** (e.g., via Docker) on that exact same Oracle VPS.
3. Home Assistant talks to the Helium API over `localhost`.
4. You link your cloud-hosted Home Assistant to Google Home.

### Pros & Cons:
* **Pros:** $0 upfront cost, no hardware at home.
* **Cons:** You are dependent on Helium's AWS cloud staying online. If the cloud API changes or goes down, you lose control of the AC.

---

## Home Assistant Configuration Example

Regardless of whether you host locally or on a VPC, here is the YAML configuration you need to add to your Home Assistant `configuration.yaml` file to link it to the Helium API.

Assuming your Helium API is running at `192.168.1.100:5055` (replace with `localhost:5055` if hosted on the same machine):

### 1. REST Commands (Sending Actions)
```yaml
rest_command:
  helium_ac_power_on:
    url: "http://192.168.1.100:5055/api/ac/command?transport=cloud" # or ?transport=ble
    method: POST
    headers:
      content-type: "application/json"
    payload: '{"power": "on"}'

  helium_ac_power_off:
    url: "http://192.168.1.100:5055/api/ac/command?transport=cloud"
    method: POST
    headers:
      content-type: "application/json"
    payload: '{"power": "off"}'
    
  helium_ac_set_temp:
    url: "http://192.168.1.100:5055/api/ac/command?transport=cloud"
    method: POST
    headers:
      content-type: "application/json"
    payload: '{"temperature": {{ temperature }}}'
```

### 2. REST Sensor (Reading State)
```yaml
sensor:
  - platform: rest
    name: "Helium AC State"
    resource: "http://192.168.1.100:5055/api/ac/state?transport=cloud"
    value_template: "{{ value_json.power }}"
    json_attributes:
      - temperature
      - room
      - mode
```

### 3. Exposing to Google Assistant
Once you have created scripts or a `climate` template entity using the above commands, you can expose them to Google Assistant:
* **Easy route:** Use [Home Assistant Cloud](https://www.nabucasa.com/) (Settings -> Voice Assistants -> Google Assistant).
* **Free route:** Follow the [Google Assistant Manual Integration guide](https://www.home-assistant.io/integrations/google_assistant/).
