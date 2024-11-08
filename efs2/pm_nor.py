from .pm import PageManager
from .super import Superblock
from io import RawIOBase
from .utils import by2int
from .log import PageLog, DoVerifyLog, DoParseLog, UpdateTableType

class NORLog(PageLog):
    def __init__(self, sb: Superblock, file: RawIOBase, base_offset: int, pm: PageManager) -> None:
        # 01 - Init variables
        self.__override_rtable_index = {}
        self.__override_upper = [x for x in sb.upper_data]
        
        self.__super = sb
        self.__fio = file
        self.__base_offset = base_offset
        self.__pm = pm
        
        self.do_scan()
        
    def do_scan(self) -> None:
        # 02 - Scan log
        reload = False
        log_pages = []
        
        no_log = 0
        self.__fio.seek(self.__base_offset + (self.__super.log_head * self.__super.page_size))
        buf = self.__fio.read(self.__super.page_size)
        
        if DoVerifyLog(buf, self.__super.log_head):
            start = by2int(buf[:4])
            end = start
        
        else:
            no_log = 1
            start = 0
            end = start
            
        for page in range(self.__super.page_total):
            state = self.__override_rtable_index[page] if page in self.__override_rtable_index else self.__pm.get_reverse(page)
            if state == 0xFFFFFFF8:
                self.__fio.seek(self.__base_offset + (page * self.__super.page_size))
                buf = self.__fio.read(self.__super.page_size)

                valid = DoVerifyLog(buf, page)
                logToUse = False
                
                if buf == b"\xff" * self.__super.page_size:
                    logToUse = True
                    
                elif not no_log and by2int(buf[:4]) >= start and valid:
                    logToUse = True
                    
                if logToUse:
                    log_pages.append(page)
                    
                if valid and by2int(buf[:4]) != 0xffffffff and by2int(buf[:4]) >= end:
                    end = by2int(buf[:4])

        # 03 - Iterate logs
        found_log = False
        for i, p in enumerate(log_pages):
            if p == self.__super.log_head:
                found_log = True
                break

        if not found_log:
            print("Something is wrong on log data")
            return False

        cur = i
        end = i
        prev_log_seq = None
        
        while True:
            self.__fio.seek(self.__base_offset + (log_pages[cur] * self.__super.page_size))
            buf = self.__fio.read(self.__super.page_size)

            log_seq = by2int(buf[:4])
            
            if log_seq != 0xffffffff:
                assert prev_log_seq is None or log_seq == 1 or (log_seq - 1) == prev_log_seq, "Log sequence is broken"
                
                prev_log_seq = log_seq
                
                if DoVerifyLog(buf, log_pages[cur]):
                    check_header = by2int(buf[4:8])
                    for f in DoParseLog(buf, self.__super, log_pages[cur]):
                        if f.type == UpdateTableType.RTABLE_INDEX and check_header == 0xffffffff:
                            self.__override_rtable_index[f.index] = f.value
                                
                        elif f.type == UpdateTableType.UPPER_DATA:
                            self.__override_upper[f.index] = f.value
                            
                        elif f.type == UpdateTableType.LOG_ALLOC:
                            state = self.__override_rtable_index[f.index] if f.index in self.__override_rtable_index else self.__pm.get_reverse(f.index)
                            
                            if state not in [0xFFFFFFF8, 0xFFFFFFF4]:
                                found_log = False
                                for p in log_pages:
                                    if p == f.index:
                                        found_log = True
                                        break
                                    
                                if found_log:
                                    reload = True
                                    self.__override_rtable_index[f.index] = 0xFFFFFFF8
                                    
                                else:
                                    self.__fio.seek(self.__base_offset + (f.index * self.__super.page_size))
                                    if self.__fio.read(self.__super.page_size) == b"\xff" * self.__super.page_size:
                                        self.__override_rtable_index[f.index] = 0xFFFFFFF8
                                        
                                    else:
                                        self.__override_rtable_index[f.index] = 0xFFFFFFF4
                
            cur += 1
            if cur == len(log_pages):
                cur = 0
                
            if cur == end:
                break 
            
        return reload

    def get_upper_data(self) -> list[int]:
        return self.__override_upper
    
    def get_ptable_index(self, index: int, fallback_value: int=-1) -> int:
        return fallback_value # Not NAND
    
    def get_rtable_index(self, index: int, fallback_value: int=-1) -> int:
        return self.__override_rtable_index[index] if index in self.__override_rtable_index else fallback_value
    
    def get_ptable_node(self, level: int, index: int, fallback_value: int=-1) -> int:
        return fallback_value # Not NAND
    
    def get_rtable_node(self, level: int, index: int, fallback_value: int=-1) -> int:
        return fallback_value # Not NAND

class NORPM(PageManager):
    def __init__(self, sb: Superblock, file: RawIOBase, base_offset: int) -> None:
        super().__init__(sb, file, base_offset)
        self.write_style = sb.nor_writing_style
        
        field_shift = 2 if self.write_style == 0 else 3
        field_size = sb.page_size >> field_shift
        
        self.__minor_mask = field_size - 1
        temp = self.__minor_mask
        
        self.__major_shift = 0
        while temp != 0:
            temp >>= 1
            self.__major_shift += 1
            
        self.__reserved_offset = sb.block_size - ((sb.block_size + self.__minor_mask) >> self.__major_shift)
        self.__ptables = [0xffffffff] * sb.page_total
        
    @staticmethod
    def __get_paired_bits(paired: int):
        paired = ((paired & 0x44444444) >> 1) | (paired & 0x11111111)
        paired = ((paired & 0x30303030) >> 2) | (paired & 0x03030303)
        paired = ((paired & 0x0f000f00) >> 4) | (paired & 0x000f000f)
        paired = ((paired & 0x00ff0000) >> 8) | (paired & 0x000000ff)
        return paired
        
    def compute_ptables(self) -> None:
        for page in range(self.super.page_total):
            cluster = self.get_reverse(page)
            if (cluster >> 31) == 0:
                assert self.__ptables[cluster] == 0xffffffff, f"Duplicate page: 0x{page:04x}"
                self.__ptables[cluster] = page
        
    def get_forward(self, cluster: int):
        return self.__ptables[cluster]
    
    def get_reverse(self, page: int):
        if self._log is not None and self._log.get_rtable_index(page) != -1:
            temp = self._log.get_rtable_index(page)
            
            if temp == 0:
                return 0xfffffff4
            
            elif temp == 0xffffffff:
                return 0xfffffff1
            
            else:
                if (temp >> 31) == 0:
                    temp &= 0xFFFFFF
                    
                return temp
        
        current_block = page & self.super.block_mask
        current_offset = page & ~self.super.block_mask
        last_offset = self.super.block_size - 1
        
        if current_offset >= self.__reserved_offset:
            return 0xfffffff9
        
        current_major = self.__reserved_offset + (current_offset >> self.__major_shift)
        current_minor = current_offset & self.__minor_mask
        
        last_major = self.__reserved_offset + (last_offset >> self.__major_shift)
        last_minor = last_offset & self.__minor_mask
        
        if self.write_style == 0: # Simple
            header_check_offset = ((current_block + last_major) * self.super.page_size) + (last_minor * 4)
            cur_rtable_offset = ((current_block + current_major) * self.super.page_size) + (current_minor * 4)
            
            self.file.seek(self._base_offset + header_check_offset)
            if self.file.read(4) != b"\xe1\xe1\xf0\xf0":
                return 0xfffffff4
            
            self.file.seek(self._base_offset + cur_rtable_offset)
            temp = by2int(self.file.read(4))
        
        else:
            header_check_offset = ((current_block + last_major) * self.super.page_size) + ((2 * last_minor) * 4)
            cur_rtable_offset = ((current_block + current_major) * self.super.page_size) + ((2 * current_minor) * 4)
            
            self.file.seek(self._base_offset + header_check_offset)
            if self.file.read(8) != b"\x03\xfc\x03\xfc\x00\xff\x00\xff":
                return 0xfffffff4
            
            self.file.seek(self._base_offset + cur_rtable_offset)
            t1 = self.__get_paired_bits(by2int(self.file.read(4)))
            t2 = self.__get_paired_bits(by2int(self.file.read(4)))
            
            temp = t2 << 16 | t1
            
        if temp == 0:
            return 0xfffffff4
        
        elif temp == 0xffffffff:
            return 0xfffffff1
        
        else:
            if (temp >> 31) == 0:
                temp &= 0xFFFFFF
                
            return temp