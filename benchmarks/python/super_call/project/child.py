from base import Base
class Child(Base):
    def save(self, value): return super().save(value)
