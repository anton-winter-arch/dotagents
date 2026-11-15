"""Write readings in the archive format. Nothing imports this module."""


def export(readings, out):
    for time, height, _ in readings:
        out.write(f"{time};{height:.2f}\n")
