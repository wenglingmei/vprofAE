add_library(ProfileVarPass MODULE
  ProfileVar.cpp
  ValueFlow.cpp
  SaveSrcInfo.cpp
)

# Use C++11 to compile our pass (i.e., supply -std=c++11).
target_compile_features(ProfileVarPass PRIVATE cxx_range_for cxx_auto_type)

# LLVM is (typically) built with no C++ RTTI. We need to match that;
# otherwise, we'll get linker errors about missing RTTI data.
set_target_properties(ProfileVarPass PROPERTIES
    COMPILE_FLAGS "-fno-rtti"
)
set_target_properties(ProfileVarPass PROPERTIES
  LINK_FLAGS "-Wl,-znodelete -lSegFault"
)
target_link_libraries(ProfileVarPass
   "$<$<PLATFORM_ID:Darwin>:-undefined dynamic_lookup>")
