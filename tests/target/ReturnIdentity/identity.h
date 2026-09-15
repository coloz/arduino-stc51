#ifndef RETURN_IDENTITY_H
#define RETURN_IDENTITY_H

struct Identity {
    const Identity *self;
    unsigned value;
    explicit Identity(unsigned value = 17) : self(this), value(value) {}
    Identity(const Identity &other) : self(this), value(other.value) {}
    Identity(Identity &&other) : self(this), value(other.value) { other.value = 0; }
    ~Identity() {}
    bool valid() const { return self == this; }
};

Identity makeIdentity(unsigned value);
Identity forwardIdentity(unsigned value);
Identity (*identityFactory())(unsigned);

#endif
