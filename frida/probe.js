setTimeout(function(){
  Java.perform(function(){
    try {
      var M = Java.use("com.helium.mobileapp.HeliumCloudMQTTModule");
      send("FOUND HeliumCloudMQTTModule");
      var methods = M.class.getDeclaredMethods();
      for (var i=0;i<methods.length;i++) send("  method: "+methods[i].getName());
    } catch(e){ send("ERR: "+e); }
  });
}, 1000);
