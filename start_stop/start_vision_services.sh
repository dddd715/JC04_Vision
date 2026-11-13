#!/usr/bin/env bash

set -Eeuo pipefail

for service_name in camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack; do
    sudo systemctl start "${service_name}.service"
    printf 'Started: %s.service\n' "$service_name"
done
