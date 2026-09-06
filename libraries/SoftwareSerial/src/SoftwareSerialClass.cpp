/*
 * SPDX-License-Identifier: MIT
 *
 * Process-wide owner for the SoftwareSerial single-active-port C HAL.
 */
#if defined(STCXX_CPP_CORE) && STCXX_CPP_CORE

#include "SoftwareSerial.h"

SoftwareSerial *SoftwareSerial::_activeObject = 0;

#endif /* STCXX_CPP_CORE */
