from construct import Int16ul, Int32ul, Const, Hex, Array, Computed, Struct, IfThenElse, this
from .pm import PageManager
from .efs2 import EFS2
from .super import Superblock, UpperDataIndex
from .info import EFSInfo
from .db import Database
from io import RawIOBase
from .utils import ilog2

CEFS_FACTORY_V2 = Struct(
    Const(b'\x87\x67\x85\x34'),
    Const(b'\x59\x77\x34\x92'),
    "fact_version" / Hex(Int16ul),
    "version" / Hex(Int16ul),
    "block_size" / Hex(Int32ul),
    "page_size" / Hex(Int32ul),
    "block_count" / Hex(Int32ul),
    "block_length" / Hex(Computed(this.block_size *  this.page_size)),
    "page_total" / Hex(Computed(this.block_size * this.block_count)),
    "cefs_page_count" / Hex(Int32ul),
    "upper_data" / IfThenElse((this.version & 0xff) >= 0x24, Array(32, Hex(Int32ul)), Array(7, Hex(Int32ul)))
)

CEFS_FACTORY_V1 = Struct(
    "page_header" / Hex(Int32ul),
    "magic1" / Const(b'\x87\x67\x85\x34'),
    "magic2" / Const(b'\x59\x77\x34\x92'),
    "fact_version" / Hex(Int16ul),
    "version" / Hex(Int16ul),
    "block_size" / Hex(Int32ul),
    "page_size" / Hex(Int32ul),
    "block_count" / Hex(Int32ul),
    "block_length" / Hex(Computed(this.block_size *  this.page_size)),
    "page_total" / Hex(Computed(this.block_size * this.block_count)),
    "cefs_page_count" / Hex(Int32ul),
    "upper_data" / IfThenElse((this.version & 0xff) >= 0x24, Array(32, Hex(Int32ul)), Array(7, Hex(Int32ul)))
)

class CEFSFactory(Superblock):
    def __init__(self, data: bytes):
        factory = (CEFS_FACTORY_V2 if data[:8] == b'\x87\x67\x85\x34\x59\x77\x34\x92' else CEFS_FACTORY_V1).parse(data)
        
        # 01 - Header
        self.factory_version: int = factory.fact_version
        self.version: int = factory.version
        self.age: int = 0

        # 02 - Filesystem Information
        self.block_size: int = factory.block_size
        self.page_size: int = factory.page_size
        self.block_count: int = factory.block_count

        # 03 - Computed info
        self.block_length: int = factory.block_length
        self.page_total: int = factory.page_total
        
        self.block_shift: int = ilog2(factory.block_size)
        self.block_mask: int = ~((1 << self.block_shift) - 1)
        
        # 04 - Page management
        self.cefs_page_count: int = factory.cefs_page_count
        
        # 05 - Upper Data
        self.upper_data: list[int] = factory.upper_data

class CEFSPM(PageManager):
    def __init__(self, sb: CEFSFactory, file: RawIOBase, base_offset: int) -> None:
        super().__init__(sb, file, base_offset)
        file.seek(sb.page_size + base_offset)

        self.__map = file.read(0x100000)
        self.__ptables = [0xffffffff] * sb.cefs_page_count
        self.__rtables = [0xffffffff] * sb.cefs_page_count

    def __check_fcache_free(self, cluster: int) -> int:
        fc_offset = cluster >> 3
        fc_bit = cluster & 7

        if self.super.factory_version >= 3:
            return self.__map[fc_offset] & (1 << fc_bit) # 1: Free, 0: Used

        else:
            return (self.__map[fc_offset] & (1 << (7 - fc_bit))) == 0 # 0: Free, 1: Used

    def compute_ptables(self) -> None:
        self.super: CEFSFactory

        cluster = 0
        page = self._base_offset // self.super.page_size

        fs_page_start = (((self.super.page_size << 3) + self.super.cefs_page_count + -1) // (self.super.page_size << 3)) + 1

        while cluster < self.super.cefs_page_count:
            while cluster < self.super.cefs_page_count and self.__check_fcache_free(cluster):
                cluster += 1

            if cluster < self.super.cefs_page_count:
                self.__ptables[cluster] = page if self.super.factory_version >= 3 else page + fs_page_start
                self.__rtables[self.__ptables[cluster]] = cluster
                cluster += 1
                page += 1

    def get_forward(self, cluster: int) -> int:
        return self.__ptables[cluster]

    def get_reverse(self, page: int) -> int:
        return self.__rtables[page]

class CEFS(EFS2):
    def __init__(self, file: RawIOBase, base_offset: int=0, encoding: str="latin-1") -> None:
        self.encoding: str = encoding
        self._file: RawIOBase = file
        self._closed: bool = True

        if base_offset == -1:
            base_offset = 0

        file.seek(base_offset)
        factory = CEFSFactory(file.read(0x80000))

        self._pm: CEFSPM = CEFSPM(factory, file, base_offset)
        self._pm.compute_ptables()

        self.efs_info: EFSInfo = EFSInfo(factory.upper_data[UpperDataIndex.FS_INFO], self._pm)
        self._db: Database = Database(factory.upper_data[UpperDataIndex.DB_ROOT], self._pm, self.encoding)

        self._cur_db: int = self.efs_info.root_inode
        self.pwd: str = "/"

        self._closed: bool = False