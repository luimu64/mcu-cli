cmake_minimum_required(VERSION 3.20)

# Board/part configuration — override at configure time:
#   cmake -B build -DMCU=atmega328p -DF_CPU=16000000
set(MCU   "atmega328p" CACHE STRING "AVR part, passed to avr-gcc -mmcu=")
set(F_CPU "16000000" CACHE STRING "CPU clock in Hz")

project(nano_blink C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(
  -mmcu=${MCU}
  -DF_CPU=${F_CPU}UL
  -Os -g -Wall -Wextra
  -ffunction-sections -fdata-sections -fno-common
)
add_link_options(-mmcu=${MCU} -Wl,--gc-sections -Wl,-Map=${PROJECT_NAME}.map)

add_executable(${PROJECT_NAME} src/main.c)
set_target_properties(${PROJECT_NAME} PROPERTIES SUFFIX ".elf")

# avr-objcopy is what the programmer actually eats: hex (+ bin/map for other tools)
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
  COMMAND avr-objcopy -O ihex   -R .eeprom $<TARGET_FILE:${PROJECT_NAME}> ${PROJECT_NAME}.hex
  COMMAND avr-objcopy -O binary -R .eeprom $<TARGET_FILE:${PROJECT_NAME}> ${PROJECT_NAME}.bin
  COMMAND avr-size --format=avr --mcu=${MCU} $<TARGET_FILE:${PROJECT_NAME}>
  COMMENT "elf -> hex/bin + size report"
  VERBATIM
)
