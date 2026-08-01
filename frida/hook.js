/*
 * Frida hook for the Helium app.
 * Dumps the MQTT connect() options (contains p12Password, host, clientId) and
 * every publish(topic, payload) so we get the cloud command schema too.
 *
 * Target: com.helium.mobileapp.HeliumCloudMQTTModule
 */
function main() {
    console.log("[hook] Java.perform running");

    function tryHook() {
        try {
            var M = Java.use("com.helium.mobileapp.HeliumCloudMQTTModule");

            // connect(ReadableMap options, Promise promise)
            M.connect.overload(
                "com.facebook.react.bridge.ReadableMap",
                "com.facebook.react.bridge.Promise"
            ).implementation = function (options, promise) {
                console.log("\n[hook] ===== HeliumCloudMQTTModule.connect() =====");
                try {
                    var it = options.keySetIterator();
                    while (it.hasNextKey()) {
                        var k = it.nextKey();
                        var v = "";
                        try { v = options.getString(k); } catch (e) { v = "(non-string)"; }
                        console.log("[hook]   " + k + " = " + v);
                    }
                } catch (e) {
                    console.log("[hook]   options dump error: " + e);
                }
                return this.connect(options, promise);
            };
            console.log("[hook] connect() hooked");

            // publish(String topic, String payload)
            M.publish.overload("java.lang.String", "java.lang.String")
                .implementation = function (topic, payload) {
                console.log("\n[hook] >>> PUBLISH");
                console.log("[hook]   topic   : " + topic);
                console.log("[hook]   payload : " + payload);
                return this.publish(topic, payload);
            };
            console.log("[hook] publish() hooked");
        } catch (e) {
            console.log("[hook] class not loaded yet: " + e);
            return false;
        }
        return true;
    }

    if (!tryHook()) {
        // retry after the RN module registers
        var iv = setInterval(function () {
            if (tryHook()) clearInterval(iv);
        }, 800);
    }

    // Also catch the low-level p12 password use, in case connect() is inlined.
    try {
        var KS = Java.use("java.security.KeyStore");
        KS.load.overload("java.io.InputStream", "[C").implementation = function (is, pw) {
            if (pw) {
                var s = "";
                for (var i = 0; i < pw.length; i++) s += pw[i];
                console.log("[hook] KeyStore.load password = '" + s + "'");
            }
            return this.load(is, pw);
        };
        console.log("[hook] KeyStore.load hooked");
    } catch (e) {
        console.log("[hook] KeyStore hook error: " + e);
    }
}

// wait until the Java VM is available (gadget may load us very early)
function waitForJava() {
    if (typeof Java !== "undefined" && Java.available) {
        Java.perform(main);
    } else {
        setTimeout(waitForJava, 500);
    }
}
waitForJava();
