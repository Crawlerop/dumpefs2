from construct import Struct, Hex, Int32ul, Int16ul, Int8ul, this, Byte, Bytes, Computed, GreedyRange, Const, IfThenElse, If
from .pm import PageManager
from .utils import actual_version
from datetime import datetime

EFS2_NODE_DATA_V2 = Struct(
    "prev" / Hex(Int32ul),
    "next" / Hex(Int32ul),
    "used" / Hex(Int16ul),
    "pad" / Hex(Int16ul),
    "gid" / Hex(Int32ul),
    "bogus_count" / Hex(Byte),
    "level" / Hex(Byte),
    "_data" / Bytes(this.used),
    "db" / Computed(lambda ctx: (EFS2_DB_UPPER_LEVEL if ctx.level > 0 else EFS2_DB_LOWER_LEVEL).parse(ctx._data))
)

EFS2_NODE_DATA_V1 = Struct(
    "prev" / Hex(Int32ul),
    "next" / Hex(Int32ul),
    "used" / Hex(Int16ul),    
    "bogus_count" / Hex(Byte),
    "level" / Hex(Byte),
    "_data" / Bytes(this.used),
    "db" / Computed(lambda ctx: (EFS2_DB_UPPER_LEVEL if ctx.level > 0 else EFS2_DB_LOWER_LEVEL).parse(ctx._data))
)

EFS2_DB_UPPER_LEVEL = Struct(
    "upper_cluster" / Hex(Int32ul),
    "nodes" / GreedyRange(Struct(
        "size" / Hex(Int8ul),
        "type" / Const(b"d"),
        "data" / Bytes(lambda ctx: ctx.size - 1),
        "next_cluster" / Hex(Int32ul),
    ))
)

EFS2_DB_LOWER_LEVEL = Struct(
    "nodes" / GreedyRange(Struct(
        "data_size" / Hex(Int8ul),
        "inode_size" / Hex(Int8ul),
        "type" / Const(b"d"),
        "parent_inode" / Hex(Int32ul),
        "name" / Bytes(lambda ctx: ctx.data_size - 5),
        "inode_type" / Bytes(1),
        "inode" / If(this.inode_type == b"i", Hex(Int32ul)),
        "inline" / IfThenElse(this.inode_type == b"n", Struct(
            "mode" / Hex(Int16ul),
            "data" / Bytes(lambda ctx: ctx._.inode_size - 3)
        ), If(this.inode_type == b"N", Struct(
            "mode" / Hex(Int16ul),
            "gid" / Hex(Int16ul),
            "ctime" / Hex(Int32ul),
            "data" / Bytes(lambda ctx: ctx._.inode_size - 9)
        ))),
        "symlink" / If(this.inode_type == b"s", Bytes(lambda ctx: ctx.inode_size - 1)),
        "long_name" / If(this.inode_type == b"L", Bytes(lambda ctx: ctx.inode_size - 1))
    ))
)

class InlineData():
    def __init__(self):
        self.is_long: bool = None
        self.mode: int = None
        self.group_id: int = None
        self.created_time: datetime = None
        self.data: bytes = None
        
    def __repr__(self):
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items()),
        )

class DatabaseItem():
    def __init__(self):
        self.name: bytes = None
        self.parent_inode: int = None
        
        self.inode_type: int = None
        self.inode: int = None
        self.inline: InlineData = None
        self.symlink_path: bytes = None
        
        self.long_name: bytes = None
        
    def __repr__(self):
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items()),
        )

class Database():
    def __init__(self, cluster: int, pm: PageManager, encoding: str) -> None:
        self.__pm = pm
        self.__sb_version = actual_version(pm.super.version)
        self.__nodes = self.__recurse_db(cluster)
        self.__encoding = encoding
        
    def __recurse_db(self, cluster: int, db_map: dict[int, list[DatabaseItem]]={}) -> None:
        struct_node_data = EFS2_NODE_DATA_V2 if self.__sb_version >= 0x24 else EFS2_NODE_DATA_V1
        self.__pm.forward_seek(cluster)

        node = struct_node_data.parse_stream(self.__pm.file)

        if node.level > 0:
            clusters = [node.db.upper_cluster] + [n.next_cluster for n in node.db.nodes]

            for c in clusters:
                db_map = self.__recurse_db(c, db_map)
                
        else:
            for n in node.db.nodes:
                temp = DatabaseItem()

                temp.name = n.name
                temp.parent_inode = n.parent_inode

                temp.inode_type = n.inode_type[0]
                temp.inode = n.inode

                if n.inline is not None:
                    temp.inline = InlineData()

                    if temp.inode_type == 0x4e:
                        temp.inline.mode = n.inline.mode
                        temp.inline.group_id = n.inline.gid
                        temp.inline.created_time = datetime.fromtimestamp(n.inline.ctime)
                        temp.inline.data = n.inline.data
                        temp.inline.is_long = True

                    else:
                        temp.inline.mode = n.inline.mode
                        temp.inline.data = n.inline.data
                        temp.inline.is_long = False

                temp.symlink_path = n.symlink
                temp.long_name = n.long_name
                
                if n.parent_inode not in db_map:
                    db_map[n.parent_inode] = []

                db_map[n.parent_inode].append(temp)
        
        return db_map
    
    def lookup(self, dir: int, name: str) -> DatabaseItem | None:
        for n in self.__nodes[dir]:
            if (name == "." and n.name == b"") or (name == ".." and n.name == b"\0") or (name == n.name.decode(self.__encoding)):
                return n

        return None
    
    def list(self, dir: int) -> list[DatabaseItem]:
        return self.__nodes[dir]
    
    def __repr__(self) -> str:
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items()),
        )