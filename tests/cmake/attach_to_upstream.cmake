# Injected into the upstream build with:
#   -DCMAKE_PROJECT_static-global-token-table_INCLUDE=<this file>
# The deferred include runs after upstream has defined sgtt_core and Catch2, so external/ stays unmodified.
# Deferred arguments are expanded when the call runs, so capture the path now.
set(HASHCODE_ROUNDTRIP_TARGETS "${CMAKE_CURRENT_LIST_DIR}/roundtrip_targets.cmake")
set(HASHCODE_PHASE1_TARGETS "${CMAKE_CURRENT_LIST_DIR}/../../benchmarks/cmake/phase1_targets.cmake")
set(HASHCODE_COLUMN_TARGETS "${CMAKE_CURRENT_LIST_DIR}/column_targets.cmake")
cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL include "${HASHCODE_ROUNDTRIP_TARGETS}")
cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL include "${HASHCODE_COLUMN_TARGETS}")
cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL include "${HASHCODE_PHASE1_TARGETS}")
