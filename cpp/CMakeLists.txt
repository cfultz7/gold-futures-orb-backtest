cmake_minimum_required(VERSION 3.16)
project(gc_orb CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# -ffp-contract=off: no fused multiply-add, so floating-point results match the Python simulator
# bit for bit even when built with -march=native.
add_compile_options(-Wall -Wextra -ffp-contract=off)

option(ORB_WITH_KDB "Build the kdb+ IPC event source into orb_bt" OFF)
set(KDB_C_DIR "" CACHE PATH "Directory with k.h and c.o from github.com/KxSystems/kdb (c/c/k.h, l64/c.o)")

find_package(Threads REQUIRED)

add_library(orbcore STATIC
  src/config.cpp
  src/dataset.cpp
  src/walkforward.cpp
  src/report.cpp)
target_include_directories(orbcore PUBLIC include)

add_executable(wf_grid src/wf_grid.cpp)
target_link_libraries(wf_grid PRIVATE orbcore Threads::Threads)

add_executable(orb_bt src/orb_bt.cpp src/csv_source.cpp)
target_link_libraries(orb_bt PRIVATE orbcore)

if(ORB_WITH_KDB)
  if(NOT EXISTS "${KDB_C_DIR}/k.h" OR NOT EXISTS "${KDB_C_DIR}/c.o")
    message(FATAL_ERROR "ORB_WITH_KDB needs KDB_C_DIR containing k.h and c.o")
  endif()
  target_sources(orb_bt PRIVATE src/kdb_source.cpp "${KDB_C_DIR}/c.o")
  target_include_directories(orb_bt PRIVATE "${KDB_C_DIR}")
  target_compile_definitions(orb_bt PRIVATE ORB_WITH_KDB)
  target_link_libraries(orb_bt PRIVATE Threads::Threads ${CMAKE_DL_LIBS} m)
endif()
