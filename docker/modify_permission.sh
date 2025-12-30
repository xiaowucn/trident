#!/bin/bash

find /opt/trident/ /etc/supervisor /etc/nginx/ /data /docker/ -type d -exec chmod 777 '{}' \;
find /opt/trident/ /etc/supervisor /etc/nginx/ /data -type f -exec chmod 666 '{}' \;

find /docker/ -type f -name "*.sh" -exec chmod 755 '{}' \;
find /docker/ -type f -name "*.pyc" -exec chmod 755 '{}' \;
find /docker/ -type f -name "*.conf" -exec chmod 755 '{}' \;
