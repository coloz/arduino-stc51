This probe executes the installed `div`, `ldiv`, `lldiv`, `imaxdiv`, checked
addition and checked subtraction library implementations. It covers signed
quotient/remainder behavior, large integer values, exact limits and reported
overflow. It was added after six `libsdcc` members differed between native Mac
and Linux builds. Different code bytes alone do not establish incorrect behavior.

All aggregate return values remain inside native C. The Arduino C++ sketch
receives only a byte containing the failure mask. Run on a device with sufficient
Flash; this is a runtime-library regression, not a minimum-size application.
