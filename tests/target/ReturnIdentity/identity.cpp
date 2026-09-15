#include "identity.h"

Identity makeIdentity(unsigned value) { return Identity(value); }
Identity forwardIdentity(unsigned value) { return makeIdentity(value); }
Identity (*identityFactory())(unsigned) { return &makeIdentity; }
