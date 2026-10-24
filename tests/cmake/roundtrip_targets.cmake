get_filename_component(HASHCODE_TESTS_DIR "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
add_executable(hashcode_roundtrip_tests "${HASHCODE_TESTS_DIR}/roundtrip/RoundTripTest.cpp")
target_link_libraries(hashcode_roundtrip_tests PRIVATE sgtt_core Catch2::Catch2WithMain)
set_target_properties(hashcode_roundtrip_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/hashcode_tests")
