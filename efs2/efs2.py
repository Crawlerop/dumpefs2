from .super import Superblock, Regions, UpperDataIndex
from io import RawIOBase
from construct import ConstError, StreamError
from .pm_nand import NANDLog, NANDPM
from .pm_nor import NORLog, NORPM
from .info import EFSInfo
from .db import Database, DatabaseItem
from .inode import INode, InlineINode, INodeReader
from stat import S_ISDIR, S_ISLNK, S_IFLNK, S_IFREG
from datetime import datetime
from io import BytesIO

class EFS2():
    def __init__(self, file: RawIOBase, base_offset: int=-1, super: int=-1, io_wrapper: RawIOBase=None, encoding: str="latin-1", log=True, end_offset: int=-1) -> None:
        self._file: RawIOBase = file
        self.__super: Superblock = None
        self._closed: bool = True

        self.encoding: str = encoding

        if base_offset != -1:
            file.seek(base_offset)

        cur_superblock_offset = 0
        superblock_offsets = []
        superblocks = []

        while True if end_offset < 0 else file.tell() < end_offset:
            try:
                sb_offs = file.tell()
                sb = Superblock(file.read(0x4000))

                superblock_offsets.append(sb_offs)
                superblocks.append(sb)

                if self.__super is None or (sb.age > self.__super.age and sb.computed_checksum == sb.checksum):
                    cur_superblock_offset = superblock_offsets[-1]
                    self.__super = sb

            except ConstError:
                pass

            except StreamError:
                break

        if len(superblocks) <= 0:
            raise Exception("could not find EFS2 superblock")

        if super != -1:
            self.__super = superblocks[super]
            cur_superblock_offset = superblock_offsets[super]

        if io_wrapper is not None:
            self._file = io_wrapper(self._file)
            self._file.seek(cur_superblock_offset)
            self.__super = Superblock(self._file.read(0x4000))

        self.efs_size: int = self.__super.page_total * self.__super.page_size

        if self.__super.is_nand:
            sb_count = self.__super.regions[Regions.SUPER_LOG_END] - self.__super.regions[Regions.SUPER_LOG_START]

            self.efs_end: int = superblock_offsets[0] + (sb_count * self.__super.block_length)
            self.efs_start: int = (self.efs_end - (self.__super.page_total * self.__super.page_size))

        else:
            self.efs_end: int = superblock_offsets[-1] + self.__super.block_length
            self.efs_start: int = superblock_offsets[0]

        if base_offset == -1:
            print(f"EFS Autostart: 0x{self.efs_start:08x}")
            base_offset = self.efs_start

        self.base_offset: int = base_offset
        self.superblock_start_offset: int = cur_superblock_offset - base_offset

        self._pm = (NANDPM if self.__super.is_nand else NORPM)(self.__super, self._file, self.base_offset)

        if log:
            if self.__super.is_nand:
                self._pm.set_log(NANDLog(self.__super, self._file, self.base_offset, self.superblock_start_offset))

            else:
                log = NORLog(self.__super, self._file, self.base_offset, self._pm)
                self._pm.set_log(log)
                while log.do_scan():
                    pass

        self._pm.compute_ptables()

        self.efs_info: EFSInfo = EFSInfo(self.__super.upper_data[UpperDataIndex.FS_INFO], self._pm)
        self._db: Database = Database(self.__super.upper_data[UpperDataIndex.DB_ROOT], self._pm, self.encoding)

        self._cur_db: int = self.efs_info.root_inode
        self.pwd: str = "/"

        self._closed = False

    # Filesystem routines
    def __classify_inode(self, item: DatabaseItem) -> INode:
        if item.inode is not None:
            return INode(item, self._pm, self.encoding)

        elif item.symlink_path is not None:
            return InlineINode(item.name.decode(self.encoding), S_IFLNK | 0o777, 0, datetime.fromtimestamp(0), item.symlink_path)

        elif item.inline is not None:
            if item.inline.is_long:
                return InlineINode(item.name.decode(self.encoding), S_IFREG | item.inline.mode, item.inline.group_id, item.inline.created_time, item.inline.data)

            else:
                return InlineINode(item.name.decode(self.encoding), S_IFREG | item.inline.mode, 0, datetime.fromtimestamp(0), item.inline.data)

    def __resolve(self, pathname: str) -> tuple[INode, list[str]]:
        # 01 - Setup variables
        path = pathname if len(pathname) <= 1 else pathname.rstrip("/")
        resolved_paths = []

        paths = path.split("/")

        # 02 - If root, set to root inode, else, set to cur inode.
        if len(paths[0]) <= 0:
            resolved_paths.append("")
            inode_now = self.efs_info.root_inode
            paths.pop(0)

        else:
            inode_now = self._cur_db

        # 03 - For each path names, lookup until we reached the last path
        for i, p in enumerate(paths):
            if len(p) <= 0: continue
            resolved_paths.append(p)

            expectFile = i >= len(paths) - 1
            match = self._db.lookup(inode_now, p)

            if match is None:
                raise FileNotFoundError(pathname)

            inode = self.__classify_inode(match)

            if expectFile:
                return inode, resolved_paths

            else:
                if not S_ISDIR(inode.mode): raise NotADirectoryError(pathname)
                inode_now = match.inode

        # 04 - If we reached the end of this code, lookup
        return self.__classify_inode(self._db.lookup(inode_now, ".")), resolved_paths

    @staticmethod
    def __format_name(i: INode):
        if S_ISDIR(i.mode) and i.name not in [".", ".."]:
            return i.name + "/"

        return i.name

    def ls(self, pathname: str="") -> list[tuple[str, INode]]:
        if self._closed:
            raise Exception("Cannot perform when closed")

        temp = []

        if len(pathname) <= 0:
            for n in self._db.list(self._cur_db):
                inode = self.__classify_inode(n)
                temp.append((self.__format_name(inode), inode))

        else:
            file, _ = self.__resolve(pathname)

            if not S_ISDIR(file.mode):
                return [(self.__format_name(file), file)]

            for n in self._db.list(file.id):
                inode = self.__classify_inode(n)
                temp.append((self.__format_name(inode), inode))

        return temp

    def ls_recursive(self, pathname: str="") -> list[tuple[str, INode]]:
        if self._closed:
            raise Exception("Cannot perform when closed")

        temp = []
        for name, info in self.ls(pathname):
            if name not in [".", ".."]:
                temp.append((pathname + name, info))
                if S_ISDIR(info.mode):
                    temp.extend(self.ls_recursive(pathname + name))

        return temp

    def cd(self, pathname: str="") -> None:
        if self._closed:
            raise Exception("Cannot perform when closed")

        file, resolved_path = self.__resolve(pathname)
        if not S_ISDIR(file.mode):
            raise NotADirectoryError(pathname)

        else:
            pwd_temp = self.pwd.rstrip("/").split("/")

            if pathname.startswith("/"):
                pwd_temp = []

            for fp in resolved_path:
                if fp == "..":
                    pwd_temp.pop()

                elif fp != ".":
                    pwd_temp.append(fp)

            self.pwd = "/".join(pwd_temp) + "/"
            self._cur_db = file.id

    def stat(self, pathname: str) -> INode:
        if self._closed:
            raise Exception("Cannot perform when closed")

        file, _ = self.__resolve(pathname)
        return file

    def open(self, pathname: str, follow_symlinks: bool=True) -> INode:
        if self._closed:
            raise Exception("Cannot perform when closed")

        file = self.stat(pathname)

        if type(file) == InlineINode:
            if S_ISLNK(file.mode) and follow_symlinks:
                return self.open(file.data.decode(self.encoding))

            return BytesIO(file.data)

        else:
            return INodeReader(file)

    def set_encoding(self, encoding: str) -> None:
        self._db.set_encoding(encoding)
        self.encoding = encoding

    def close(self) -> None:
        if not self._closed:
            del self._db
            del self._pm
            self._file.close()
            self._closed = True

    def __del__(self) -> None:
        if not self._closed:
            self.close()

def compute_efs2_size(data: bytes):
    cur_superblock_offset = 0
    superblock_offsets = []
    superblocks = []
    super = None

    while True:
        try:
            sb = Superblock(data[cur_superblock_offset:cur_superblock_offset+0x4000])

            superblock_offsets.append(cur_superblock_offset)
            superblocks.append(sb)

            if super is None or (sb.age > super.age and sb.computed_checksum == sb.checksum):
                super = sb

        except ConstError:
            pass

        except StreamError:
            break

        cur_superblock_offset += 0x4000

    if len(superblocks) <= 0:
        raise Exception("could not find EFS2 superblock")

    return super.page_total * super.page_size