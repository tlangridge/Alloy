"""Version constraints such as ``^1.2``, ``>=1.4, <2 || 3.*``."""


class Constraint(object):
    @classmethod
    def parse(cls, text):
        """Parse constraint text; raises InvalidConstraint."""
        raise NotImplementedError('Constraint.parse is not implemented yet')

    def allows(self, version):
        """True if ``version`` (a Version or version string) satisfies the constraint."""
        raise NotImplementedError('Constraint.allows is not implemented yet')
