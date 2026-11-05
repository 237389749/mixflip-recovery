// A declaration-only stand-in for AOSP's libbase header, which the TWRP
// check compiles against without a whole AOSP tree. graphics_drm.cpp
// reads a few properties through it; the definitions come from libbase in
// the real build.
#pragma once

#include <string>

namespace android {
namespace base {

std::string GetProperty(const std::string& key, const std::string& default_value);
bool GetBoolProperty(const std::string& key, bool default_value);
int GetIntProperty(const std::string& key, int default_value);

}  // namespace base
}  // namespace android
