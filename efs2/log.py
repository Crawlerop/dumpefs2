from abc import abstractmethod, ABCMeta
from .super import Superblock
from io import RawIOBase
from enum import IntEnum
from .utils import ilog2, by2int, EFS_CRC

class UpdateTableType(IntEnum):
    PTABLE_INDEX = 0
    RTABLE_INDEX = 1
    PTABLE_META = 2
    RTABLE_META = 3
    UPPER_DATA = 4
    LOG_ALLOC = 5

class PageLog(metaclass=ABCMeta):
    @abstractmethod
    def get_upper_data(self) -> list[int]:
        pass
    
    @abstractmethod
    def get_ptable_index(self, index: int, fallback_value: int=-1) -> int:
        pass
    
    @abstractmethod
    def get_rtable_index(self, index: int, fallback_value: int=-1) -> int:
        pass
    
    @abstractmethod
    def get_ptable_node(self, level: int, index: int, fallback_value: int=-1) -> int:
        pass
    
    @abstractmethod
    def get_rtable_node(self, level: int, index: int, fallback_value: int=-1) -> int:
        pass
    
    def __repr__(self) -> str:
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items()),
        )
    
class TableUpdateEvent():
    def __init__(self, type: UpdateTableType, level: int, index: int, value: int):
        self.type = type
        self.level = level
        self.index = index
        self.value = value
        
    def __repr__(self):
        temp = f"<update_event type={UpdateTableType(self.type).name}"
        if self.type & 2:
            temp += f" level={self.level}"
            
        return temp + (f" index=0x{self.index:08x} value=0x{self.value:08x}>" if self.type != UpdateTableType.LOG_ALLOC else f" page=0x{self.index:08x}>")

def DoVerifyLog(buf: bytes, log_index: int) -> bool:
    if buf == b"\xff"*len(buf): 
        #print(f"LOG 0x{log_index:04x}: erased page")
        return False
    
    log_offs = 8
    
    while log_offs < len(buf):
        if buf[log_offs] == 0xfe:
            # If we still have data for CRC
            if log_offs + 2 < len(buf):
                # Verify
                crc = by2int(buf[log_offs + 1:log_offs + 3])
                if crc == EFS_CRC(buf[8:log_offs + 1]):
                    return True
                    
                else:
                    print(f"LOG 0x{log_index:04x}: crc mismatch")
                    
            else:
                print(f"LOG 0x{log_index:04x}: no space to verify CRC")
            
            break
            
        elif buf[log_offs] == 0xfd:
            # If we still have enough data for CRC and erase marker
            if log_offs + 3 < len(buf):
                # Check for erase marker
                passNullCheck = True
                
                null_check = log_offs + 3
                while null_check < len(buf):
                    if buf[null_check] != 0x00:
                        passNullCheck = False
                        break
                    
                    null_check += 1
                
                if passNullCheck:
                    # Verify
                    crc = by2int(buf[log_offs + 1:log_offs + 3])
                    if crc == EFS_CRC(buf[:4] + buf[8:log_offs + 1]):
                        return True
                        
                    else:
                        print(f"LOG 0x{log_index:04x}: crc mismatch")
                        
                else:
                    print(f"LOG 0x{log_index:04x}: null check fail")
                        
            else:
                print(f"LOG 0x{log_index:04x}: no space to verify")
                
            break
        
        nargs, _ = (buf[log_offs] >> 6), (buf[log_offs] & 0x3f)
        log_offs += 1 + (4 * nargs)
      
    if log_offs >= len(buf):
        print(f"LOG 0x{log_index:04x}: unexpected EOF")
        
    return False

def DoParseLog(buf: bytes, sb: Superblock, log_index: int) -> list[TableUpdateEvent]:
    # 01 - Verification
    temp = []
    passVerification = DoVerifyLog(buf, log_index)
    
    # 02 - Parse
    if passVerification:
        log_offs = 8
                        
        while log_offs < len(buf):
            if buf[log_offs] in [0xfd, 0xfe]: # EOS Marker
                break
            
            nargs, op = (buf[log_offs] >> 6), (buf[log_offs] & 0x3f)
            args_offset = log_offs + 1
            
            args = [by2int(buf[args_offset + (x * 4):args_offset + (x * 4) + 4]) for x in range(nargs)]
            
            if op in [4, 11]: # Page Move/GC Move
                temp.append(TableUpdateEvent(UpdateTableType.RTABLE_INDEX, 0, args[1], 0xfffffff4))
                temp.append(TableUpdateEvent(UpdateTableType.RTABLE_INDEX, 0, args[2], args[0]))
                temp.append(TableUpdateEvent(UpdateTableType.PTABLE_INDEX, 0, args[0] & 0xffffff, args[2]))
                # self.__override_rtable_index[args[1]] = 0xfffffff4
                # self.__override_rtable_index[args[2]] = args[0]
                # self.__override_ptable_index[args[0] & 0xffffff] = args[2]
                
            elif op == 5: # New Data
                temp.append(TableUpdateEvent(UpdateTableType.RTABLE_INDEX, 0, args[1], args[0]))
                temp.append(TableUpdateEvent(UpdateTableType.PTABLE_INDEX, 0, args[0] & 0xffffff, args[1]))
                # self.__override_rtable_index[args[1]] = args[0]
                # self.__override_ptable_index[args[0] & 0xffffff] = args[1]
            
            elif op == 6: # Page Table Move
                temp.append(TableUpdateEvent(UpdateTableType.RTABLE_INDEX, 0, args[1], 0xfffffff4))
                temp.append(TableUpdateEvent(UpdateTableType.RTABLE_INDEX, 0, args[2], args[0]))
                # self.__override_rtable_index[args[1]] = 0xfffffff4
                # self.__override_rtable_index[args[2]] = args[0]
                
                is_reverse = (args[0] >> 29) & 1
                
                level = sb.page_depth - ((args[0] >> 26) & 7) # (3 - 1) = 2 * 7 = 14, 3 - 2 = 1 * 7 = 7
                index = ((args[0] & 0x3ffffff) << 6) >> sb.depth_shift[level]
                #print(f"index: 0x{index:08x}, now: 0x{args[2]:08x}, args0: 0x{args[0]:08x}, level: {level}, ec_level: {((args[0] >> 26) & 7)}, depth_offset: {sb.depth_shift[level]}")

                temp.append(TableUpdateEvent(UpdateTableType.RTABLE_META if is_reverse else UpdateTableType.PTABLE_META, level, index, args[2]))
                # if level not in (self.__override_rtable_level if table_type else self.__override_ptable_level):
                #     (self.__override_rtable_level if table_type else self.__override_ptable_level)[level] = {}
                    
                # (self.__override_rtable_level if table_type else self.__override_ptable_level)[level][index] = args[2]
                
            elif op == 7: # Update Upper Data
                temp.append(TableUpdateEvent(UpdateTableType.UPPER_DATA, 0, args[0], args[1]))
                # self.__override_upper[args[0]] = args[1]
                
            elif op == 13: # GC Dealloc
                temp.append(TableUpdateEvent(UpdateTableType.RTABLE_INDEX, 0, args[1], 0xfffffff4))
                temp.append(TableUpdateEvent(UpdateTableType.PTABLE_INDEX, 0, args[0], 0xffffffff))
                # self.__override_rtable_index[args[1]] = 0xfffffff4
                # self.__override_ptable_index[args[0]] = 0xffffffff
                
            elif op == 14: # Garbage
                temp.append(TableUpdateEvent(UpdateTableType.RTABLE_INDEX, 0, args[0], 0xfffffff4))
                # self.__override_rtable_index[args[0]] = 0xfffffff4
            
            elif op == 17: # Log Alloc
                temp.append(TableUpdateEvent(UpdateTableType.LOG_ALLOC, 0, args[0], 0))
            
            log_offs += 1 + (4 * nargs)

    return temp