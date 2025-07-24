from construct import Struct, Hex, Int32ul, Int16ul, Array
from .db import DatabaseItem
from .pm import PageManager
from .utils import actual_version, ilog2, by2int
from datetime import datetime
from stat import S_ISREG
from io import RawIOBase, SEEK_CUR, SEEK_END, SEEK_SET

EFS2_INODE_V2 = Struct(
    "mode" / Hex(Int16ul),
    "nlink" / Hex(Int16ul),
    "attr" / Hex(Int32ul),
    "size" / Hex(Int32ul),
    "uid" / Hex(Int16ul),
    "gid" / Hex(Int16ul),
    "generation" / Hex(Int32ul),
    "blocks" / Hex(Int32ul),
    "mtime" / Hex(Int32ul),
    "ctime" / Hex(Int32ul),
    "atime" / Hex(Int32ul),
    "reserved" / Array(7, Hex(Int32ul)),
    "direct_cluster_id" / Array(13, Hex(Int32ul)),
    "indirect_cluster_id" / Array(3, Hex(Int32ul)),
)

EFS2_INODE_V2_32BIT = Struct(
    "mode" / Hex(Int32ul),
    "nlink" / Hex(Int32ul),
    "attr" / Hex(Int32ul),
    "size" / Hex(Int32ul),
    "uid" / Hex(Int16ul),
    "gid" / Hex(Int16ul),
    "generation" / Hex(Int32ul),
    "blocks" / Hex(Int32ul),
    "mtime" / Hex(Int32ul),
    "ctime" / Hex(Int32ul),
    "atime" / Hex(Int32ul),
    "reserved" / Array(7, Hex(Int32ul)),
    "direct_cluster_id" / Array(13, Hex(Int32ul)),
    "indirect_cluster_id" / Array(3, Hex(Int32ul)),
)

EFS2_INODE_V1 = Struct(
    "mode" / Hex(Int16ul),
    "nlink" / Hex(Int16ul),
    "size" / Hex(Int32ul),
    "generation" / Hex(Int32ul),
    "blocks" / Hex(Int32ul),
    "mtime" / Hex(Int32ul),
    "ctime" / Hex(Int32ul),
    "direct_cluster_id" / Array(6, Hex(Int32ul)),
    "indirect_cluster_id" / Array(3, Hex(Int32ul)),
)

class INode():
    def __init__(self, item: DatabaseItem, pm: PageManager, encoding: str) -> None:
        # Compute INode bitmasks to determine the actual INode offset
        # log2(0x800 // 0x80) = log2(16) = 4, log2(0x200 // 0x3c) = log(8) = 3, log2(0x200 // 0x80) = log(4) = 2
        COMPUTED_INODE_SIZE = 0x80 if actual_version(pm.super.version) >= 0x24 or actual_version(pm.super.version) in [0xe, 0xf] else 0x3c

        # Sanyo Katana uses 32-bit INodes, so detect that
        if actual_version(pm.super.version) in [0xe, 0xf] and (pm.super.version >> 8) & 4: COMPUTED_INODE_SIZE += 4
        # Sanyo A5522SA uses old inode structure although other phones used the new ones.
        elif actual_version(pm.super.version) in [0xe, 0xf] and (pm.super.version >> 8) & 0x10: COMPUTED_INODE_SIZE = 0x3c

        COMPUTED_INODE_BITS = ilog2(pm.super.page_size // COMPUTED_INODE_SIZE)
        COMPUTED_INODE_MASK = (1 << COMPUTED_INODE_BITS) - 1

        struct_inode_data = EFS2_INODE_V2 if actual_version(pm.super.version) >= 0x24 or actual_version(pm.super.version) in [0xe, 0xf] else EFS2_INODE_V1

        # Do the same for Sanyo Katana
        if actual_version(pm.super.version) in [0xe, 0xf] and (pm.super.version >> 8) & 4: struct_inode_data = EFS2_INODE_V2_32BIT
        # Ditto for A5522SA
        elif actual_version(pm.super.version) in [0xe, 0xf] and (pm.super.version >> 8) & 0x10: struct_inode_data = EFS2_INODE_V1

        if item.inode is None:
            raise TypeError("Item is not an inode")

        inode_page = item.inode >> COMPUTED_INODE_BITS
        inode_index = item.inode & COMPUTED_INODE_MASK

        pm.forward_seek(inode_page, inode_index * COMPUTED_INODE_SIZE)
        inode = struct_inode_data.parse_stream(pm.file)

        if item.name == b"":
            self.name: str = "."

        elif item.name == b"\0":
            self.name: str = ".."

        else:
            self.name: str = item.name.decode(encoding)

        self.mode: int = inode.mode
        self.file_size: int = inode.size
        self.generation: int = inode.generation
        self.blocks: int = inode.blocks
        self.modified_time: datetime = datetime.fromtimestamp(inode.mtime)
        self.created_time: datetime = datetime.fromtimestamp(inode.ctime)

        self.id: int = item.inode

        self.direct_clusters = inode.direct_cluster_id
        self.indirect_clusters = inode.indirect_cluster_id

        if actual_version(pm.super.version) >= 0x24 or (actual_version(pm.super.version) in [0xe, 0xf] and (not (pm.super.version >> 8) & 0x10)):
            self.user_id: int = inode.uid
            self.group_id: int = inode.gid
            self.accessed_time: datetime = datetime.fromtimestamp(inode.atime)

        else:
            self.user_id: int = 0
            self.group_id: int = 0
            self.accessed_time: datetime = datetime.fromtimestamp(0)

        self.pm = pm
        self.table_count = pm.super.page_size // 4

    def __repr__(self) -> str:
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items() if k != "pm"),
        )

class InlineINode(INode):
    def __init__(self, name: str, mode: int, gid: int, ctime: datetime, data: bytes):
        self.name: str = name
        self.mode: int = mode
        self.group_id: int = gid
        self.created_time: datetime = ctime
        self.modified_time: datetime = ctime
        self.file_size: int = len(data)
        self.blocks: int = 1
        self.generation: int = 1
        self.data = data

class INodeReader(RawIOBase):
    def __init__(self, inode: INode) -> None:
        # 01 - Init
        if not S_ISREG(inode.mode):
            raise TypeError("Not a file")

        self.__offset = 0
        self.__closed = False

        # 02 - Setup Tables
        self.__inode_tables = [x for x in inode.direct_clusters]

        for depth, cluster in enumerate(inode.indirect_clusters):
            if cluster == 0xffffffff: # Terminate when null cluster is found
                break

            def recurse(depth, cluster):
                inode.pm.forward_seek(cluster)
                table = [by2int(inode.pm.file.read(4)) for _ in range(inode.table_count)]

                if depth <= 0:
                    return table

                else:
                    temp = []
                    for c in table:
                        if c == 0xffffffff: break
                        temp.extend(recurse(depth - 1, c))

                    return temp

            self.__inode_tables.extend(recurse(depth, cluster))

        self.__inode = inode

    def read(self, count=-1) -> bytes:
        temp = bytearray()

        # 03 - Check if EOF
        if self.__closed or self.__offset >= self.__inode.file_size or count == 0:
            return b""

        # 04 - Loop until count is zero
        read_count = (self.__inode.file_size - self.__offset) if count == -1 else count

        while read_count:
            self.__inode.pm.forward_seek(self.__inode_tables[self.__offset // self.__inode.pm.super.page_size])
            t_read_count = min(self.__inode.pm.super.page_size - (self.__offset % self.__inode.pm.super.page_size), read_count)

            temp += self.__inode.pm.file.read(t_read_count)
            self.__offset += t_read_count
            read_count -= t_read_count

        return bytes(temp)

    def tell(self) -> int:
        return self.__offset

    def seek(self, offset: int, where: int=SEEK_SET) -> None:
        if where == SEEK_SET:
            self.__offset = self.__offset

        elif where == SEEK_CUR:
            self.__offset += self.__offset

        elif where == SEEK_END:
            if offset <= 0: raise ValueError("offset in SEEK_END must not be 0")
            self.__offset = (self.__inode.file_size) - offset

    def close(self) -> None:
        self.__inode = None
        self.__closed = True
