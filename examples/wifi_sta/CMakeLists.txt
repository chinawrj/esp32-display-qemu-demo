cmake_minimum_required(VERSION 3.16)

# Bring in the esp_wifi_qemu component from the parent repo
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(wifi_sta_example)
