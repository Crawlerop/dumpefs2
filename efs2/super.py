from construct import Int16ul, Int32ul, Const, Hex, Array, Computed, Struct, IfThenElse, this
from .utils import actual_version, ilog2, by2int
from enum import IntEnum

_EFS2_SUPERBLOCK = Struct(
    "page_header" / Hex(Int32ul),
    "version" / Hex(Int16ul),
    "age" / Hex(Int16ul),
    "magic1" / Const(b'\x45\x46\x53\x53'),
    "magic2" / Const(b'\x75\x70\x65\x72'),
    "block_size" / Hex(Int32ul),
    "page_size" / Hex(Int32ul),
    "block_count" / Hex(Int32ul),
    "block_length" / Hex(Computed(this.block_size * this.page_size)),
    "page_total" / Hex(Computed(this.block_size * this.block_count)),
    "is_nand" / IfThenElse(actual_version(this.version) > 0xa, Computed((this.version & 1) == 1), Computed((this.version & 1) == 0)),
    "log_head" / Hex(Int32ul),
    "alloc_next" / Array(4, Hex(Int32ul)),
    "gc_next" / Array(4, Hex(Int32ul)),
    "upper_data" / IfThenElse(actual_version(this.version) >= 0x24, Array(32, Hex(Int32ul)), Array(7, Hex(Int32ul))),
    "nand_info" / IfThenElse(this.is_nand, Struct(
        "nodes_per_page" / Hex(Int16ul),
        "page_depth" / Hex(Int16ul),
        "super_nodes" / Hex(Int16ul),
        "num_regions" / Hex(Int16ul),
        "regions" / Array(this.num_regions, Hex(Int32ul)),
        "logr_badmap" / Hex(Int32ul),
        "pad" / Hex(Int32ul),        
        "ptables" / IfThenElse(this._.page_size == 0x800, Array(0xe2, Hex(Int32ul)), IfThenElse(actual_version(this._.version) >= 0x24, Array(0x22, Hex(Int32ul)), Array(0x30, Hex(Int32ul)))), # Cluster to Page
        "rtables" / IfThenElse(this._.page_size == 0x800, Array(0xe2, Hex(Int32ul)), IfThenElse(actual_version(this._.version) >= 0x24, Array(0x22, Hex(Int32ul)), Array(0x30, Hex(Int32ul)))), # Page to Cluster
    ), Struct(
        "nor_writing_style" / Hex(Int16ul)
    ))
    # "db_root_clust" / Computed(this.upper_data[2]),
    # "fs_info_clust" / Computed(this.upper_data[3])
)

'''
Upper Data information:

/* These first two fields are used by the buffer management code itself to
 * keep track of free clusters. */
FS_FIELD_FREEMAP_BASE   0
FS_FIELD_FREE_CHAIN     1

/* This field stores the root of the database.  Since the database needs to
 * change this when the tree changes depth, it uses a field to store this
 * information. */
FS_FIELD_DB_ROOT        2

/* This field stores the cluster number of the info-block for the
 * filesystem.  This is described in fs_mount.[ch]. */
FS_FIELD_FS_INFO        3

/* This field is used to keep track of the number of allocated clusters. */
FS_FIELD_NUM_ALLOC      4

/* This field is now unused and uninitialized.
 * (It was formerly the difference between the soft and hard limits.) */
FS_FIELD_UNUSED         5

/* This field tracks allocations to the general pool */
FS_FIELD_GENERAL_POOL   6

/* This field holds the space limit for the given build */
FS_FIELD_SPACE_LIMIT    7
'''

crc30_table = [
    0x00000000, 0x2030b9c7, 0x2051ca49, 0x0061738e,
    0x20932d55, 0x00a39492, 0x00c2e71c, 0x20f25edb,
    0x2116e36d, 0x01265aaa, 0x01472924, 0x217790e3,
    0x0185ce38, 0x21b577ff, 0x21d40471, 0x01e4bdb6,
    0x221d7f1d, 0x022dc6da, 0x024cb554, 0x227c0c93,
    0x028e5248, 0x22beeb8f, 0x22df9801, 0x02ef21c6,
    0x030b9c70, 0x233b25b7, 0x235a5639, 0x036aeffe,
    0x2398b125, 0x03a808e2, 0x03c97b6c, 0x23f9c2ab,
    0x240a47fd, 0x043afe3a, 0x045b8db4, 0x246b3473,
    0x04996aa8, 0x24a9d36f, 0x24c8a0e1, 0x04f81926,
    0x051ca490, 0x252c1d57, 0x254d6ed9, 0x057dd71e,
    0x258f89c5, 0x05bf3002, 0x05de438c, 0x25eefa4b,
    0x061738e0, 0x26278127, 0x2646f2a9, 0x06764b6e,
    0x268415b5, 0x06b4ac72, 0x06d5dffc, 0x26e5663b,
    0x2701db8d, 0x0731624a, 0x075011c4, 0x2760a803,
    0x0792f6d8, 0x27a24f1f, 0x27c33c91, 0x07f38556,
    0x2824363d, 0x08148ffa, 0x0875fc74, 0x284545b3,
    0x08b71b68, 0x2887a2af, 0x28e6d121, 0x08d668e6,
    0x0932d550, 0x29026c97, 0x29631f19, 0x0953a6de,
    0x29a1f805, 0x099141c2, 0x09f0324c, 0x29c08b8b,
    0x0a394920, 0x2a09f0e7, 0x2a688369, 0x0a583aae,
    0x2aaa6475, 0x0a9addb2, 0x0afbae3c, 0x2acb17fb,
    0x2b2faa4d, 0x0b1f138a, 0x0b7e6004, 0x2b4ed9c3,
    0x0bbc8718, 0x2b8c3edf, 0x2bed4d51, 0x0bddf496,
    0x0c2e71c0, 0x2c1ec807, 0x2c7fbb89, 0x0c4f024e,
    0x2cbd5c95, 0x0c8de552, 0x0cec96dc, 0x2cdc2f1b,
    0x2d3892ad, 0x0d082b6a, 0x0d6958e4, 0x2d59e123,
    0x0dabbff8, 0x2d9b063f, 0x2dfa75b1, 0x0dcacc76,
    0x2e330edd, 0x0e03b71a, 0x0e62c494, 0x2e527d53,
    0x0ea02388, 0x2e909a4f, 0x2ef1e9c1, 0x0ec15006,
    0x0f25edb0, 0x2f155477, 0x2f7427f9, 0x0f449e3e,
    0x2fb6c0e5, 0x0f867922, 0x0fe70aac, 0x2fd7b36b,
    0x3078d5bd, 0x10486c7a, 0x10291ff4, 0x3019a633,
    0x10ebf8e8, 0x30db412f, 0x30ba32a1, 0x108a8b66,
    0x116e36d0, 0x315e8f17, 0x313ffc99, 0x110f455e,
    0x31fd1b85, 0x11cda242, 0x11acd1cc, 0x319c680b,
    0x1265aaa0, 0x32551367, 0x323460e9, 0x1204d92e,
    0x32f687f5, 0x12c63e32, 0x12a74dbc, 0x3297f47b,
    0x337349cd, 0x1343f00a, 0x13228384, 0x33123a43,
    0x13e06498, 0x33d0dd5f, 0x33b1aed1, 0x13811716,
    0x14729240, 0x34422b87, 0x34235809, 0x1413e1ce,
    0x34e1bf15, 0x14d106d2, 0x14b0755c, 0x3480cc9b,
    0x3564712d, 0x1554c8ea, 0x1535bb64, 0x350502a3,
    0x15f75c78, 0x35c7e5bf, 0x35a69631, 0x15962ff6,
    0x366fed5d, 0x165f549a, 0x163e2714, 0x360e9ed3,
    0x16fcc008, 0x36cc79cf, 0x36ad0a41, 0x169db386,
    0x17790e30, 0x3749b7f7, 0x3728c479, 0x17187dbe,
    0x37ea2365, 0x17da9aa2, 0x17bbe92c, 0x378b50eb,
    0x185ce380, 0x386c5a47, 0x380d29c9, 0x183d900e,
    0x38cfced5, 0x18ff7712, 0x189e049c, 0x38aebd5b,
    0x394a00ed, 0x197ab92a, 0x191bcaa4, 0x392b7363,
    0x19d92db8, 0x39e9947f, 0x3988e7f1, 0x19b85e36,
    0x3a419c9d, 0x1a71255a, 0x1a1056d4, 0x3a20ef13,
    0x1ad2b1c8, 0x3ae2080f, 0x3a837b81, 0x1ab3c246,
    0x1b577ff0, 0x3b67c637, 0x3b06b5b9, 0x1b360c7e,
    0x3bc452a5, 0x1bf4eb62, 0x1b9598ec, 0x3ba5212b,
    0x3c56a47d, 0x1c661dba, 0x1c076e34, 0x3c37d7f3,
    0x1cc58928, 0x3cf530ef, 0x3c944361, 0x1ca4faa6,
    0x1d404710, 0x3d70fed7, 0x3d118d59, 0x1d21349e,
    0x3dd36a45, 0x1de3d382, 0x1d82a00c, 0x3db219cb,
    0x1e4bdb60, 0x3e7b62a7, 0x3e1a1129, 0x1e2aa8ee,
    0x3ed8f635, 0x1ee84ff2, 0x1e893c7c, 0x3eb985bb,
    0x3f5d380d, 0x1f6d81ca, 0x1f0cf244, 0x3f3c4b83,
    0x1fce1558, 0x3ffeac9f, 0x3f9fdf11, 0x1faf66d6
]

def Compute_CRC30(buf):
    data = 0
    crc30 = 0x3FFFFFFF
    len = buf.__len__()
    buf_ptr = 0
    
    while len >= 8:
        crc30 = crc30_table[ ((crc30 >> (30 - 8)) ^ buf[buf_ptr]) & 0xff ] ^ (crc30 << 8)
        len -= 8
        buf_ptr += 1
        
    if len > 0:
        data = by2int(buf[buf_ptr:buf_ptr+4]) << (30 - 8)
        
        while len > 0:
            if ( ((crc30 ^ data) & (1 << 29)) != 0 ):
                crc30 <<= 1
                crc30 ^= 0x6030B9C7

            else:
                crc30 <<= 1

            data <<= 1
            len -= 1
        
    crc30 = ~crc30
    return (crc30 + 0xffffffff + 1) & 0x3FFFFFFF
        

class UpperDataIndex(IntEnum):
    FREEMAP_BASE = 0
    FREE_CHAIN = 1
    DB_ROOT = 2
    FS_INFO = 3
    NUM_ALLOC = 4
    UNUSED = 5
    GENERAL_POOL = 6
    SPACE_LIMIT = 7

class Regions(IntEnum):
    PAGETABLE_START = 0
    PAGETABLE_END = 1
    SUPER_LOG_START = 2
    SUPER_LOG_END = 3

class Superblock():
    def __init__(self, data: bytes | bytearray):
        sb = _EFS2_SUPERBLOCK.parse(data)
        
        # 01 - Header
        self.version: int = sb.version
        self.age: int = sb.age
        self.checksum: int = by2int(data[sb.page_size-4:sb.page_size])
        self.computed_checksum: int = Compute_CRC30(data[:(sb.page_size * 8) - 32])
        
        # 02 - Filesystem Information
        self.block_size: int = sb.block_size
        self.page_size: int = sb.page_size
        self.block_count: int = sb.block_count
        
        # 03 - Computed info
        self.block_length: int = sb.block_length
        self.page_total: int = sb.page_total
        self.is_nand: int = sb.is_nand
        
        self.block_shift: int = ilog2(sb.block_size)
        self.block_mask: int = ~((1 << self.block_shift) - 1)
        
        # 04 - Page management
        self.log_head: int = sb.log_head
        self.alloc_next: list[int] = sb.alloc_next
        self.gc_next: list[int] = sb.gc_next
        
        # 05 - Upper Data (see top)
        self.upper_data: list[int] = sb.upper_data
        
        # 06 - Flash-speciic information
        if sb.is_nand:
            self.nodes_per_page: int = sb.nand_info.nodes_per_page
            self.page_depth: int = sb.nand_info.page_depth
            
            nodes_per_page_bits = ilog2(sb.nand_info.nodes_per_page)
            
            self.depth_shift: list[int] = [x * nodes_per_page_bits for x in range(sb.nand_info.page_depth)]
            self.depth_masks: list[int] = [((1 << nodes_per_page_bits) - 1) << self.depth_shift[x] for x in range(sb.nand_info.page_depth)]
            
            self.regions: list[int] = sb.nand_info.regions
            self.ptables: list[int] = sb.nand_info.ptables
            self.rtables: list[int] = sb.nand_info.rtables
            
        else:
            self.nor_writing_style: int = sb.nand_info.nor_writing_style
            
    def __repr__(self) -> str:
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items()),
        )