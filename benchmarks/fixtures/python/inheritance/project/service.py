from base import Base
class Service(Base):
    def run(self, value): return self.save(value)
class Other:
    def run(self, value): return value
