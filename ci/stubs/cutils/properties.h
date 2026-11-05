// A declaration-only stand-in for AOSP's libcutils header, which the TWRP
// check compiles against without a whole AOSP tree. The patch under test
// calls property_get() and relies on PROPERTY_VALUE_MAX; the definition
// comes from libcutils in the real build.
#pragma once

#define PROPERTY_VALUE_MAX 92

#ifdef __cplusplus
extern "C" {
#endif

int property_get(const char* key, char* value, const char* default_value);

#ifdef __cplusplus
}
#endif
