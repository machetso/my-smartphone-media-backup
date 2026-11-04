#!/bin/sh
# Build the phone app (release, shrunk) and put it where the PC app serves it from.
set -e
cd "$(dirname "$0")/../android"
JAVA_HOME="${JAVA_HOME:-$HOME/Android/jdk}" ./gradlew assembleRelease -q
mkdir -p ../assets/companion
cp app/build/outputs/apk/release/app-release.apk ../assets/companion/MediaBackup.apk
ls -la ../assets/companion/MediaBackup.apk
