from construct import Const, Int32ul, Int8ul, Int16ul, Hex, Array, Struct
from .pm import PageManager
from .super import Superblock

EFS2_INFO_DATA = Struct(
    "magic" / Const(b"\xa0\x3e\xb9\xa7"),
    "version" / Hex(Int32ul),
    "inode_top" / Hex(Int32ul),
    "inode_next" / Hex(Int32ul),
    "inode_free" / Hex(Int32ul),
    "root_inode" / Hex(Int32ul),
    "partial_delete" / Hex(Int8ul),
    "partial_delete_mid" / Hex(Int8ul),
    "partial_delete_gid" / Hex(Int16ul),
    "partial_delete_data" / Array(4, Hex(Int32ul)),
)

class EFSInfo():
    def __init__(self, cluster: int, pm: PageManager) -> None:
        pm.forward_seek(cluster)
        info = EFS2_INFO_DATA.parse_stream(pm.file)
        self.root_inode: int = info.root_inode
        self.version: int = info.version
        
    def __repr__(self) -> str:
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items()),
        )