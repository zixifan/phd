// This file defines utility macros for working with C++.
#pragma once

#include "phd/private/macros_impl.h"

#ifdef DEBUG
#error "C preprocessor macro DEBUG() already defined!"
#endif

#ifdef INFO
#error "C preprocessor macro INFO() already defined!"
#endif

#ifdef WARN
#error "C preprocessor macro WARN() already defined!"
#endif

#ifdef ERROR
#error "C preprocessor macro ERROR() already defined!"
#endif

#ifdef FATAL
#error "C preprocessor macro FATAL() already defined!"
#endif

// Log the given message with varying levels of severity. The arguments should
// be a format string. A newline is appended to the message when printed.
#define DEBUG(...) LOG_WITH_PREFIX("D", __VA_ARGS__)
#define LOG(...) LOG_WITH_PREFIX("I", __VA_ARGS__)
#define WARN(...) LOG_WITH_PREFIX("W", __VA_ARGS__)
#define ERROR(...) LOG_WITH_PREFIX("E", __VA_ARGS__)
// Terminate the program with exit code 1, printing the given message to
// stderr. The arguments should be a format string. A newline is appended
// to the message when printed.
#define FATAL(...) LOG_WITH_PREFIX("F", __VA_ARGS__); exit(1);

#ifdef CHECK
#error "C preprocessor macro CHECK() already defined!"
#endif

// Check that `conditional` is true else fail fatally.
#define CHECK(conditional) \
  {  \
    if (!conditional) { \
      FATAL("CHECK(" #conditional ") failed!"); \
    } \
  }
