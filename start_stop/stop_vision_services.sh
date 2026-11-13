#!/usr/bin/env bash

set -Eeuo pipefail

for service_name in jc04vision_PoseTrack jc04vision_PoseAvoid jc04vision_face jc04vision_hand camera; do
    sudo systemctl stop "${service_name}.service"
    printf 'Stopped: %s.service\n' "$service_name"
done
