get_filename_component(HASHCODE_PROJECT_DIR "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
set(HASHCODE_P2A_DEFINITIONS
    HASHCODE_P2A_VOCABULARY="${HASHCODE_PROJECT_DIR}/codec/p2a/p2a_vocabulary_v1.bin"
    HASHCODE_P2A_VOCABULARY_SHA256="${HASHCODE_PROJECT_DIR}/codec/p2a/p2a_vocabulary_v1.sha256")
add_executable(hashcode_p2a_tests "${HASHCODE_PROJECT_DIR}/tests/p2a/P2aCodecTest.cpp")
target_include_directories(hashcode_p2a_tests PRIVATE "${HASHCODE_PROJECT_DIR}/codec/include" "${HASHCODE_PROJECT_DIR}/benchmarks/phase1")
target_compile_definitions(hashcode_p2a_tests PRIVATE ${HASHCODE_P1_DEFINITIONS} ${HASHCODE_P2A_DEFINITIONS})
target_link_libraries(hashcode_p2a_tests PRIVATE sgtt_core Catch2::Catch2WithMain)
set_target_properties(hashcode_p2a_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/hashcode_tests")
target_compile_definitions(phase1_column_harness PRIVATE ${HASHCODE_P2A_DEFINITIONS})
