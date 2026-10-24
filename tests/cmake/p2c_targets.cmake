# P2c tests. The P2c vocabulary used here is built at build time, in the build directory, from the SYNTHETIC unit-test fixture
# (tests/p2c/fixtures/make_synthetic_corpus.py). It is a test vocabulary only; no P2c vocabulary is frozen in codec/ (D3 is open).
get_filename_component(HASHCODE_PROJECT_DIR "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
# Python >= 3.14 provides Unicode 16.0.0, which the P1 segmentation rules (codec/p1/build_vocabulary.py) are pinned to.
find_package(Python3 3.14 REQUIRED COMPONENTS Interpreter)
set(HASHCODE_P2C_FIXTURE_DIR "${CMAKE_BINARY_DIR}/hashcode_p2c_fixture")
set(HASHCODE_P2C_FIXTURE_OUTPUTS
    "${HASHCODE_P2C_FIXTURE_DIR}/p2c_fixture_vocabulary.bin"
    "${HASHCODE_P2C_FIXTURE_DIR}/p2c_fixture_vocabulary.sha256"
    "${HASHCODE_P2C_FIXTURE_DIR}/p2c_fixture_vocabulary.manifest.json"
    "${HASHCODE_P2C_FIXTURE_DIR}/p2c_fixture_vocabulary.heldout_check.tsv")
add_custom_command(
    OUTPUT ${HASHCODE_P2C_FIXTURE_OUTPUTS}
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${HASHCODE_P2C_FIXTURE_DIR}"
    COMMAND "${Python3_EXECUTABLE}" -I "${HASHCODE_PROJECT_DIR}/tests/p2c/fixtures/make_synthetic_corpus.py" "${HASHCODE_P2C_FIXTURE_DIR}/synthetic_fixture.jsonl"
    COMMAND "${Python3_EXECUTABLE}" -I "${HASHCODE_PROJECT_DIR}/codec/p2c/build_vocabulary.py"
            --corpus "${HASHCODE_P2C_FIXTURE_DIR}/synthetic_fixture.jsonl"
            --corpus-label "synthetic unit-test fixture (not a real corpus)"
            --out-dir "${HASHCODE_P2C_FIXTURE_DIR}" --name p2c_fixture_vocabulary
            --allow-unfilled  # test vocabulary only: the fixture cannot fill L/2 entries per language
    DEPENDS "${HASHCODE_PROJECT_DIR}/tests/p2c/fixtures/make_synthetic_corpus.py" "${HASHCODE_PROJECT_DIR}/codec/p2c/build_vocabulary.py"
            "${HASHCODE_PROJECT_DIR}/codec/p1/build_vocabulary.py" "${HASHCODE_PROJECT_DIR}/codec/p2a/p2a_vocabulary_v1.bin"
    COMMENT "Building the P2c test vocabulary from the synthetic fixture"
    VERBATIM)
add_custom_target(hashcode_p2c_fixture_vocabulary DEPENDS ${HASHCODE_P2C_FIXTURE_OUTPUTS})
add_executable(hashcode_p2c_tests "${HASHCODE_PROJECT_DIR}/tests/p2c/P2cCodecTest.cpp")
add_dependencies(hashcode_p2c_tests hashcode_p2c_fixture_vocabulary)
target_include_directories(hashcode_p2c_tests PRIVATE "${HASHCODE_PROJECT_DIR}/codec/include" "${HASHCODE_PROJECT_DIR}/benchmarks/phase1")
target_compile_definitions(hashcode_p2c_tests PRIVATE ${HASHCODE_P2A_DEFINITIONS}
    HASHCODE_P2C_FIXTURE_VOCABULARY="${HASHCODE_P2C_FIXTURE_DIR}/p2c_fixture_vocabulary.bin"
    HASHCODE_P2C_FIXTURE_SHA256="${HASHCODE_P2C_FIXTURE_DIR}/p2c_fixture_vocabulary.sha256"
    HASHCODE_P2C_FIXTURE_HELDOUT_CHECK="${HASHCODE_P2C_FIXTURE_DIR}/p2c_fixture_vocabulary.heldout_check.tsv")
target_link_libraries(hashcode_p2c_tests PRIVATE sgtt_core Catch2::Catch2WithMain)
set_target_properties(hashcode_p2c_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/hashcode_tests")
# The harness's optional p2c method (enabled only when HASHCODE_P2C_VOCABULARY is set at run time) needs the fixture for smoke runs.
add_dependencies(phase1_column_harness hashcode_p2c_fixture_vocabulary)
# P2c vocabulary checker (header-only codec; no upstream library needed).
add_executable(hashcode_p2c_check_vocabulary "${HASHCODE_PROJECT_DIR}/codec/p2c/check_vocabulary.cpp")
target_include_directories(hashcode_p2c_check_vocabulary PRIVATE "${HASHCODE_PROJECT_DIR}/codec/include")
set_target_properties(hashcode_p2c_check_vocabulary PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/hashcode_tools")
