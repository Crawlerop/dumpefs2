from construct import Struct, Const, Hex, Int32ul, this, Bytes, PaddedString, Array, Padding

PARTITION_TABLE = Struct(
    "magic1" / Const(b"\xAA\x73\xEE\x55"),
    "magic2" / Const(b"\xDB\xBD\x5E\xE3"),
    "p_ver" / Hex(Int32ul),
    "p_nbr" / Hex(Int32ul),
    "parts" / Array(this.p_nbr,
        Struct(
            "flash_id" / Bytes(1),
            Padding(1),
            "name" / PaddedString(14, "utf8"),
            "block_start" / Hex(Int32ul),
            "block_length" / Hex(Int32ul),
            "attr" / Hex(Int32ul),
        ),
    )
)

class Partition():
    def __init__(self):
        self.flash_id: int = None
        self.name: str = None
        self.start: int = None
        self.end: int = None
        self.length: int = None
        self.attr: int = None

    def __repr__(self) -> str:
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items() if k != "pm"),
        )

class PartitionTable():
    def __init__(self, data: bytes, block_size: int=0x20000):
        ptable = PARTITION_TABLE.parse(data)

        self.version: int = ptable.p_ver
        self.partitions: list[Partition] = []

        for p in ptable.parts:
            temp = Partition()
            temp.flash_id = int(p.flash_id)
            temp.name = p.name
            temp.start = p.block_start * block_size
            temp.end = (p.block_start * block_size) + (p.block_length * block_size) if p.block_length != 0xffffffff else -1
            temp.length = p.block_length * block_size if p.block_length != 0xffffffff else -1
            temp.attr = p.attr

            self.partitions.append(temp)

    def __repr__(self) -> str:
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items() if k != "pm"),
        )