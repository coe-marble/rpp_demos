cmake_minimum_required(VERSION 3.16)
project(rpp_communication_benchmarks)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rmw REQUIRED)
find_package(nlohmann_json REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME} "msg/Packet.msg")
rosidl_get_typesupport_target(packet_typesupport ${PROJECT_NAME} "rosidl_typesupport_cpp")

add_executable(rpp_bench_ros_cpp ../cpp/ros_worker.cpp)
target_include_directories(rpp_bench_ros_cpp PRIVATE ../cpp)
target_link_libraries(rpp_bench_ros_cpp PRIVATE
  rclcpp::rclcpp
  rmw::rmw
  ${packet_typesupport}
  nlohmann_json::nlohmann_json
)
install(TARGETS rpp_bench_ros_cpp RUNTIME DESTINATION bin)

option(RPP_BENCH_BUILD_RPP "Build the RPP script driver as well as the ROS driver" ON)
set(RPP_BENCH_HOME "$ENV{RPP_HOME}" CACHE PATH "Prepared benchmark RPP home")
if(RPP_BENCH_BUILD_RPP)
  find_package(rpp_cpp REQUIRED)
  set(generated "${RPP_BENCH_HOME}/interfaces/cpp")
  set(schema "${generated}/capnp_gen/communication_benchmarks/transport.capnp.c++")
  if(NOT EXISTS "${schema}")
    message(FATAL_ERROR "Run communication/prepare.py first and set RPP_BENCH_HOME to its home directory")
  endif()
  add_executable(rpp_bench_rpp_cpp ../cpp/rpp_worker.cpp "${schema}")
  target_include_directories(rpp_bench_rpp_cpp PRIVATE ../cpp "${generated}")
  target_link_libraries(rpp_bench_rpp_cpp rpp_cpp::rpp_cpp)
  install(TARGETS rpp_bench_rpp_cpp RUNTIME DESTINATION bin)
endif()

ament_export_dependencies(rosidl_default_runtime)
ament_package()
