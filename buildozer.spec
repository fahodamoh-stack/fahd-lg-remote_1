[app]

title = Fahd LG Remote
package.name = fahdlgremote
package.domain = com.fahdremote

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json

version = 1.0.0

requirements = python3,kivy==2.3.1,websocket-client==1.8.0

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_MULTICAST_STATE

android.api = 35
android.minapi = 23
android.ndk = 25b
android.archs = arm64-v8a

android.accept_sdk_license = True
android.private_storage = True
android.enable_androidx = True

android.logcat_filters = *:S python:D

p4a.branch = v2024.01.21

[buildozer]

log_level = 2
warn_on_root = 1