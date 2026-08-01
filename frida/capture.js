// Frida gadget (script mode) hook to capture the runtime AWS IoT MQTT secrets
// and the cloud publish payload from com.helium.mobileapp.
//
// Output sink: the app's own private files dir. Because the app is now
// debuggable, `adb shell run-as com.helium.mobileapp cat files/helium_capture.log`
// reads it back. (script-mode console.log has no client sink; File() into the
// app dir is writable by the app uid — this is the robust path.)

var LOG = "/data/data/com.helium.mobileapp/files/helium_capture.log";

function w(line) {
  // primary sink when a Frida client is attached (listen mode)
  try { console.log("[cap] " + line); } catch (_) {}
  // secondary sink: app's private file, readable via run-as (app is debuggable)
  try {
    var f = new File(LOG, "a");
    f.write("[" + Date.now() + "] " + line + "\n");
    f.flush();
    f.close();
  } catch (e) {}
}

w("=== capture.js loaded ===");

function startWhenJavaReady() {
  if (typeof Java === "undefined" || !Java.available) {
    w("Java runtime not ready yet, retrying in 200ms...");
    setTimeout(startWhenJavaReady, 200);
    return;
  }
  w("Java runtime available; entering perform");
  Java.perform(main);
}

function main() {
  w("Java.perform entered");

  function hookMQTT() {
    var Mod = Java.use("com.helium.mobileapp.HeliumCloudMQTTModule");

    // connect(ReadableMap options, Promise promise)
    Mod.connect.overload(
      "com.facebook.react.bridge.ReadableMap",
      "com.facebook.react.bridge.Promise"
    ).implementation = function (options, promise) {
      try {
        var host = options.getString("host");
        var port = null;
        try { port = options.getString("port"); } catch (e) {}
        var clientId = options.getString("clientId");
        var p12File = options.getString("p12File");
        var p12Password = options.getString("p12Password");
        var caFile = options.getString("caFile");
        w("*** connect() ***");
        w("  host=" + host);
        w("  port=" + port);
        w("  clientId=" + clientId);
        w("  p12File=" + p12File);
        w("  p12Password=" + p12Password);
        w("  caFile=" + caFile);
      } catch (e) {
        w("connect() dump error: " + e);
      }
      return this.connect(options, promise);
    };
    w("hooked connect()");

    // publish(String topic, String payload)
    Mod.publish.overload("java.lang.String", "java.lang.String").implementation =
      function (topic, payload) {
        w("*** publish() ***");
        w("  topic=" + topic);
        w("  payload=" + payload);
        return this.publish(topic, payload);
      };
    w("hooked publish()");

    // subscribe(String topic) — helps confirm ack topic
    try {
      Mod.subscribe.overload("java.lang.String").implementation = function (topic) {
        w("*** subscribe() topic=" + topic);
        return this.subscribe(topic);
      };
      w("hooked subscribe()");
    } catch (e) { w("subscribe hook skipped: " + e); }
  }

  // The module class may not be loaded at gadget start; retry.
  var tries = 0;
  var timer = setInterval(function () {
    tries++;
    try {
      hookMQTT();
      clearInterval(timer);
      w("MQTT hooks installed on attempt " + tries);
    } catch (e) {
      if (tries === 1 || tries % 10 === 0) w("waiting for MQTT class (try " + tries + "): " + e);
      if (tries > 600) { clearInterval(timer); w("gave up waiting for MQTT class"); }
    }
  }, 500);

  // Belt-and-braces: raw p12 password at KeyStore.load(InputStream, char[]).
  try {
    var KeyStore = Java.use("java.security.KeyStore");
    KeyStore.load.overload("java.io.InputStream", "[C").implementation = function (is, pw) {
      try {
        if (pw !== null) {
          var s = "";
          for (var i = 0; i < pw.length; i++) s += String.fromCharCode(pw[i]);
          w("*** KeyStore.load password=" + JSON.stringify(s) + " (len " + pw.length + ")");
        } else {
          w("KeyStore.load password=null");
        }
      } catch (e) { w("KeyStore.load dump error: " + e); }
      return this.load(is, pw);
    };
    w("hooked KeyStore.load([C)");
  } catch (e) {
    w("KeyStore hook error: " + e);
  }
}

startWhenJavaReady();
