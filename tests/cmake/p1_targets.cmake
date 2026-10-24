get_filename_component(HASHCODE_PROJECT_DIR "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
set(HASHCODE_P1_DEFINITIONS
    HASHCODE_P1_VOCABULARY="${HASHCODE_PROJECT_DIR}/codec/p1/p1_vocabulary_v1.bin"
    HASHCODE_P1_VOCABULARY_SHA256="${HASHCODE_PROJECT_DIR}/codec/p1/p1_vocabulary_v1.sha256")
add_executable(hashcode_p1_tests "${HASHCODE_PROJECT_DIR}/tests/p1/P1CodecTest.cpp")
target_include_directories(hashcode_p1_tests PRIVATE "${HASHCODE_PROJECT_DIR}/codec/include" "${HASHCODE_PROJECT_DIR}/benchmarks/phase1")
target_compile_definitions(hashcode_p1_tests PRIVATE ${HASHCODE_P1_DEFINITIONS})
target_link_libraries(hashcode_p1_tests PRIVATE sgtt_core Catch2::Catch2WithMain)
set_target_properties(hashcode_p1_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/hashcode_tests")
target_include_directories(phase1_column_harness PRIVATE "${HASHCODE_PROJECT_DIR}/codec/include")
target_compile_definitions(phase1_column_harness PRIVATE ${HASHCODE_P1_DEFINITIONS})
