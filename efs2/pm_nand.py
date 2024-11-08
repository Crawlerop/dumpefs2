from .pm import PageManager
from .log import PageLog, DoParseLog, UpdateTableType
from .super import Superblock, Regions
from io import RawIOBase
from .log import PageLog
from .utils import by2int

class NANDLog(PageLog):
    def __init__(self, sb: Superblock, file: RawIOBase, base_offset: int, sb_start_page: int) -> None:
        # 01 - Init variables
        self.__override_ptable_index = {}
        self.__override_rtable_index = {}
        self.__override_upper = [x for x in sb.upper_data]
        
        self.__override_ptable_level = {}
        self.__override_rtable_level = {}
        
        # 02 - Find free LOG space
        log_uppermost = (sb.regions[Regions.SUPER_LOG_START] * sb.block_size)
        log_lowermost = (sb.regions[Regions.SUPER_LOG_END] * sb.block_size)
        
        log_start = sb.log_head
        log_end = log_start
        
        file.seek(base_offset + (log_start * sb.page_size))
        
        while file.read(sb.page_size) != (b"\xff" * sb.page_size):
            log_end += 1
            
            if log_end >= log_lowermost:
                file.seek(base_offset + (log_uppermost * sb.page_size))
                log_end = log_uppermost
                
            elif log_end == sb.log_head:
                raise Exception("cannot find free space")
        
        log_end_block = log_end >> sb.block_shift
        log_end_page = log_end & ~sb.block_mask
            
        if log_end_block != (sb_start_page >> sb.block_shift) and log_end_page == 1:
            log_end -= 1
            
        print(f"log_start: 0x{log_start:08x}, log_end: 0x{log_end:08x}")
        
        # 03 - Parse Logs
        log_index = log_start
        prev_log_seq = None
        
        while log_index != log_end:
            if log_index & ~sb.block_mask != 0:
                if file.tell() != base_offset + (log_index * sb.page_size):
                    file.seek(base_offset + (log_index * sb.page_size))
                    
                buf = file.read(sb.page_size)
                
                log_seq = by2int(buf[:4])
                if log_seq != 0xffffffff:
                    assert prev_log_seq is None or log_seq == 1 or (log_seq - 1) == prev_log_seq, "Log sequence is broken"
                    
                    prev_log_seq = log_seq
                    
                    for l in DoParseLog(buf, sb, log_index):
                        if l.type == UpdateTableType.PTABLE_INDEX:
                            self.__override_ptable_index[l.index] = l.value
                            
                        elif l.type == UpdateTableType.RTABLE_INDEX:
                            self.__override_rtable_index[l.index] = l.value
                            
                        elif l.type == UpdateTableType.PTABLE_META:
                            if l.level not in self.__override_ptable_level:
                                self.__override_ptable_level[l.level] = {}
                                
                            self.__override_ptable_level[l.level][l.index] = l.value
                            
                        elif l.type == UpdateTableType.RTABLE_META:
                            if l.level not in self.__override_rtable_level:
                                self.__override_rtable_level[l.level] = {}
                                
                            self.__override_rtable_level[l.level][l.index] = l.value
                            
                        elif l.type == UpdateTableType.UPPER_DATA:
                            self.__override_upper[l.index] = l.value

            log_index += 1
            
            if log_index >= log_lowermost:
                log_index = log_uppermost

    def get_upper_data(self) -> list[int]:
        return self.__override_upper
    
    def get_ptable_index(self, index: int, fallback_value: int=-1) -> int:
        return self.__override_ptable_index[index] if index in self.__override_ptable_index else fallback_value
    
    def get_rtable_index(self, index: int, fallback_value: int=-1) -> int:
        return self.__override_rtable_index[index] if index in self.__override_rtable_index else fallback_value
    
    def get_ptable_node(self, level: int, index: int, fallback_value: int=-1) -> int:
        return self.__override_ptable_level[level][index] if level in self.__override_ptable_level and index in self.__override_ptable_level[level] else fallback_value
    
    def get_rtable_node(self, level: int, index: int, fallback_value: int=-1) -> int:
        return self.__override_rtable_level[level][index] if level in self.__override_rtable_level and index in self.__override_rtable_level[level] else fallback_value

class NANDPM(PageManager):
    def __recurse_nodes(self, curNode: int, depth: int, nodenum: int, table_type: int) -> int:
        node_offset = (nodenum & self.super.depth_masks[depth]) >> self.super.depth_shift[depth]

        self.file.seek(self._base_offset + (self.super.page_size * curNode) + (4 * node_offset))
        node = by2int(self.file.read(4))

        if table_type == 0 and self._log is not None:
            node = self._log.get_ptable_node(depth, nodenum >> self.super.depth_shift[depth], node)

        elif table_type == 1 and self._log is not None:
            node = self._log.get_rtable_node(depth, nodenum >> self.super.depth_shift[depth], node)

        if depth > 0:
            if node >= self.super.page_total: return node
            return self.__recurse_nodes(node, depth - 1, nodenum, table_type)

        else:
            return node
        
    def get_forward(self, cluster: int) -> int:
        if self._log is not None and self._log.get_ptable_index(cluster) != -1:
            return self._log.get_ptable_index(cluster)

        if self.super.page_depth == 1:
            failover = self.super.ptables[cluster]
            return self._log.get_ptable_node(0, cluster, failover) if self._log is not None else failover

        else:
            pt_start = cluster >> self.super.depth_shift[self.super.page_depth - 1]
            failover = self.super.ptables[pt_start]

            start = self._log.get_ptable_node(self.super.page_depth - 1, pt_start, failover) if self._log is not None else failover
            return self.__recurse_nodes(start, self.super.page_depth - 2, cluster, 0)

    def get_reverse(self, page: int) -> int:
        if self._log is not None and self._log.get_rtable_index(page) != -1:
            temp = self._log.get_rtable_index(page)
            if (temp >> 31) == 0:
                temp &= 0xffffff

            return temp

        if self.super.page_depth == 1:
            failover = self.super.rtables[page]
            temp = self._log.get_rtable_node(0, page, failover) if self._log is not None else failover

        else:
            pt_start = page >> self.super.depth_shift[self.super.page_depth - 1]
            failover = self.super.rtables[pt_start]

            start = self._log.get_rtable_node(self.super.page_depth - 1, pt_start, failover) if self._log is not None else failover
            temp = self.__recurse_nodes(start, self.super.page_depth - 2, page, 1)

        if (temp >> 31) == 0:
            temp &= 0xffffff

        return temp
