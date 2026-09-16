[app]
title = Premium LG Remote
package.name = premiumlgremote
package.domain = com.premiumremote

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,json,ttf,otf

version = 1.0.0

requirements = python3,kivy==2.3.1,websocket-client==1.8.0,arabic-reshaper==3.0.0,python-bidi==0.6.6

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_MULTICAST_STATE

android.api = 35
android.minapi = 23
android.ndk = 27c
android.ndk_api = 23

android.archs = arm64-v8a,armeabi-v7a

android.allow_backup = True
android.accept_sdk_license = True

android.logcat_filters = *:S python:D
android.copy_libs = 1

# webOS TVs may expose the legacy websocket endpoint on port 3000.
# SSL/TLS port 3001 is attempted first by main.py.
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1