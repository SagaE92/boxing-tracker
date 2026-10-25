# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.20.0)

# Our own devicetree bindings (boxtrk,lsm6ds3trc-fifo)
list(APPEND DTS_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(boxing_tracker VERSION 0.1.0 LANGUAGES C)

target_include_directories(app PRIVATE src)
target_sources(app PRIVATE
  src/main.c
  src/imu_lsm6ds3trc.c
  src/ringbuf.c
  src/raw_pack.c
  src/punch_detect.c
  src/session.c
  src/ble_svc.c
  src/power.c
  src/battery.c
)
