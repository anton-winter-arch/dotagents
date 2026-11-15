"""A gauge station and the readings it has taken."""


class Station:
    def __init__(self, name):
        self.name = name
        self.readings = []

    def read_day(self, lines):
        self.readings = [ln.strip() for ln in lines if "," in ln]
        return self.readings

    def summary(self):
        return f"{self.name}: {len(self.readings)} readings"
