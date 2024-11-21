from abc import ABCMeta
from abc import abstractmethod
from enum import IntEnum
from io import RawIOBase, SEEK_SET, SEEK_CUR, SEEK_END, BytesIO
import reedsolo as rs
import os

__all__ = [
    'EccHamming20',
    'EccHamming20Bitpack',
    'EccRs',
    'SpareType',
    'ECCFile'
]

ECC_XOR_TABLE = [
    0,85,86,3,89,12,15,90,90,15,12,89,3,86,85,0,              
    101,48,51,102,60,105,106,63,63,106,105,60,102,51,48,101,  
    102,51,48,101,63,106,105,60,60,105,106,63,101,48,51,102,  
    3,86,85,0,90,15,12,89,89,12,15,90,0,85,86,3,              
    105,60,63,106,48,101,102,51,51,102,101,48,106,63,60,105,  
    12,89,90,15,85,0,3,86,86,3,0,85,15,90,89,12,              
    15,90,89,12,86,3,0,85,85,0,3,86,12,89,90,15,              
    106,63,60,105,51,102,101,48,48,101,102,51,105,60,63,106,  
    106,63,60,105,51,102,101,48,48,101,102,51,105,60,63,106,  
    15,90,89,12,86,3,0,85,85,0,3,86,12,89,90,15,              
    12,89,90,15,85,0,3,86,86,3,0,85,15,90,89,12,              
    105,60,63,106,48,101,102,51,51,102,101,48,106,63,60,105,  
    3,86,85,0,90,15,12,89,89,12,15,90,0,85,86,3,             
    102,51,48,101,63,106,105,60,60,105,106,63,101,48,51,102,  
    101,48,51,102,60,105,106,63,63,106,105,60,102,51,48,101,  
    0,85,86,3,89,12,15,90,90,15,12,89,3,86,85,0
]

class ECCError(Exception):
    pass

class EccMeta(metaclass=ABCMeta):
    @abstractmethod
    def encode(self, data: bytes) -> bytes:
        pass

    @abstractmethod
    def decode(self, data: bytes, ecc: bytes) -> bytes:
        pass

    @property
    @abstractmethod
    def size(self) -> int:
        pass

# Qualcomm 20-bit Hamming engine (MSM6100, MSM6250, MSM6500)
# MSM6550 and MSM6275 also uses the ECC, but with bitpack format instead of seperate codes

class EccHamming20(EccMeta):
    def __init__(self, bitpack: bool=False) -> None:
        self.__bitpack = bitpack

    @staticmethod
    def __do_gen_ecc(data: bytes) -> bytes:
        reg1 = reg2 = reg3 = 0

        for i in range(128):
            idx = ECC_XOR_TABLE[data[i]]
            reg1 ^= idx & 0x3f

            if idx & 0x40:
                reg3 ^= i
                reg2 ^= (~i) + 0x100

        tmp1 = (reg3 & 0x40) >> 1
        tmp1 |= (reg2 & 0x40) >> 2
        tmp1 |= (reg3 & 0x20) >> 2
        tmp1 |= (reg2 & 0x20) >> 3
        tmp1 |= (reg3 & 0x10) >> 3
        tmp1 |= (reg2 & 0x10) >> 4

        tmp2 = (reg3 & 0x08) << 4
        tmp2 |= (reg2 & 0x08) << 3
        tmp2 |= (reg3 & 0x04) << 3
        tmp2 |= (reg2 & 0x04) << 2
        tmp2 |= (reg3 & 0x02) << 2
        tmp2 |= (reg2 & 0x02) << 1
        tmp2 |= (reg3 & 0x01) << 1
        tmp2 |= (reg2 & 0x01) << 0

        return bytes([tmp1, tmp2, reg1])

    @staticmethod
    def __do_check_ecc(data: bytes, ecc: bytes, ecc_calc: bytes) -> tuple[bytes, int, int]:
        data = bytearray(data)
        ecc_xor = bytes([x ^ y for x, y in zip(ecc, ecc_calc)])

        if ecc_xor == b"\0\0\0":
            return bytes(data), -1, -1

        check_ecc = bytes([x ^ (x >> 1) for x in ecc_xor])

        def get_bit(d: int, s: int):
            return (d >> s) & 1

        if (check_ecc[0] & 0x15) == 0x15 and (check_ecc[1] & 0x55) == 0x55 and (check_ecc[2] & 0x14) == 0x14:
            err_bitpos = get_bit(ecc_xor[2], 4) << 2 | get_bit(ecc_xor[2], 2) << 1 | get_bit(ecc_xor[2], 0)
            err_bytepos = get_bit(ecc_xor[0], 5) << 6 | get_bit(ecc_xor[0], 3) << 5 | get_bit(ecc_xor[0], 1) << 4 | get_bit(ecc_xor[1], 7) << 3 | get_bit(ecc_xor[1], 5) << 2 | get_bit(ecc_xor[1], 3) << 1 | get_bit(ecc_xor[1], 1)

            err_bitpos_mask = 1 << (7 - err_bitpos)
            if data[err_bytepos] & err_bitpos_mask:
                data[err_bytepos] &= ~err_bitpos_mask

            else:
                data[err_bytepos] |= err_bitpos_mask

            return bytes(data), err_bytepos, err_bitpos

        def bitcount(data: int):
            temp = 0
            while data:
                temp += data & 1
                data >>= 1

            return temp

        if bitcount(ecc_xor[0] | ecc_xor[1] << 8 | ecc_xor[2] << 16) != 1:
            raise ECCError("Uncorrectable multi-bit error")

        return bytes(data), -1, -1

    @staticmethod
    def __bitpack_ecc(ecc: bytes) -> bytes:
        if len(ecc) != 12:
            raise ValueError('ECC array must be atleast 12 bytes')

        bitWrite_Data = ""

        def writeBit(data: int, bit_count: int):
            nonlocal bitWrite_Data

            bit = bin(data & ((2 ** bit_count) - 1))[2:]
            bitWrite_Data += ("0" * (bit_count - len(bit))) + bit

        offset = 0
        while offset < 12:
            writeBit(ecc[offset], 6)
            writeBit(ecc[offset + 1], 8)
            writeBit(ecc[offset + 2], 6)
            offset += 3

        bitWrite_OutTemp = bytearray()
        while len(bitWrite_Data) != 0:
            bitWrite_OutTemp.append(int(bitWrite_Data[:8], 2))
            bitWrite_Data = bitWrite_Data[8:]

        return bytes(bitWrite_OutTemp)

    @staticmethod
    def __bitunpack_ecc(ecc: bytes) -> bytes:
        if len(ecc) != 10:
            raise ValueError('ECC part must be exactly 10 bytes')

        bitRead_Data = ecc[0]
        bitRead_BitOffset = 0
        bitRead_Offset = 0

        def readBit(count):
            nonlocal bitRead_Data, bitRead_Offset, bitRead_BitOffset
            temp = 0

            for i in range(count):
                if bitRead_BitOffset == 8:
                    bitRead_Offset += 1
                    bitRead_BitOffset = 0
                    bitRead_Data = ecc[bitRead_Offset]

                temp |= ((bitRead_Data >> (7 - bitRead_BitOffset)) & 1) << ((count - 1) - i)
                bitRead_BitOffset += 1

            return temp

        temp = bytearray()

        for _ in range(4):
            temp.append(readBit(6))
            temp.append(readBit(8))
            temp.append(readBit(6))

        return bytes(temp)

    def encode(self, data: bytes) -> bytes:
        if len(data) > 512:
            raise ValueError('ECC data larger than 512 bytes')

        if (len(data) % 0x80) != 0:
            raise ValueError('ECC data length must be divisible by 128 bytes')

        temp = bytearray()

        for i in range(len(data) // 0x80):
            temp += self.__do_gen_ecc(data[(i*0x80):(i*0x80)+0x80])

        return self.__bitpack_ecc(temp) if self.__bitpack else bytes(temp)

    def decode(self, data: bytes, ecc: bytes) -> bytes:
        if len(data) > 512:
            raise ValueError('ECC data larger than 512 bytes')

        if (len(data) % 0x80) != 0:
            raise ValueError('ECC data length must be divisible by 128 bytes')

        if self.__bitpack:
            if len(ecc) > 10:
                raise ValueError('ECC parity larger than 10 bytes')

            ecc = self.__bitunpack_ecc(ecc)

        if len(ecc) > 12:
            raise ValueError('ECC parity larger than 12 bytes')

        if (len(ecc) % 0x3) != 0:
            raise ValueError('ECC parity length must be divisible by 3 bytes')

        if (len(ecc) // 3) != (len(data) // 0x80):
            raise ValueError('ECC parity count must be the same as data count')

        temp = bytearray()

        for i in range(len(data) // 0x80):
            calc_ecc = self.__do_gen_ecc(data[(i*0x80):(i*0x80)+0x80])
            temp += self.__do_check_ecc(data[(i*0x80):(i*0x80)+0x80], ecc[(i*3):(i*3)+3], calc_ecc)[0]

        return bytes(temp)

    @property
    def size(self) -> int:
        return 10 if self.__bitpack else 12

# Class version of the bitpack version of ECC
class EccHamming20Bitpack(EccHamming20):
    def __init__(self, bitpack: bool=True):
        super().__init__(bitpack)

# Qualcomm RS engine (QSC6270, QSC6xx5, MSM6246, MSM6290, MSM68xx, MSM72xx, etc.)
class EccRs(EccMeta):
    def __init__(self) -> None:
        rs.init_tables(c_exp=10, prim=0x409)
        self.__gen = rs.rs_generator_poly(8, fcr=1)

    @staticmethod
    def __10bit_ecc_to_bytes(eccpre: list[int]) -> bytes:
        eccbytes = []
        pos = 0
        for i in range(0, 10):
            relpos = i % 5
            if relpos != 0:
                pos += 1

            byte = 0

            shift_cur_byte = 2 * relpos
            if shift_cur_byte != 8:
                byte += eccpre[pos] << shift_cur_byte

            shift_last_byte = 10 - 2 * relpos
            if shift_last_byte != 10:
                byte += eccpre[pos - 1] >> shift_last_byte

            byte &= 0xff
            eccbytes.append(byte)

        return bytes(eccbytes)

    @staticmethod
    def __bytes_to_10bit_ecc(ecc: bytes) -> list[int]:
        if len(ecc) != 10:
            raise ValueError('ECC part must be exactly 10 bytes')

        bitRead_Data = 0x100 | ecc[0]
        bitRead_Offset = 0

        def readBit(count):
            nonlocal bitRead_Data, bitRead_Offset
            temp = 0

            for i in range(count):
                if bitRead_Data == 0x1:
                    bitRead_Offset += 1
                    bitRead_Data = 0x100 | ecc[bitRead_Offset]

                temp |= (bitRead_Data & 0x1) << i
                bitRead_Data >>= 1

            return temp

        return [readBit(10) for _ in range(8)]

    def encode(self, data: bytes) -> bytes:
        if len(data) > 1015:
            raise ValueError('ECC data larger than 1015 bytes')

        padded_data = b'\x00' * (1015 - len(data)) + data
        array_data = [int(x) for x in padded_data]
        eccpre = rs.rs_encode_msg(array_data, 8, gen=self.__gen)

        return self.__10bit_ecc_to_bytes(eccpre[1015:])

    def decode(self, data: bytes, ecc: bytes) -> bytes:
        if len(data) > 1015:
            raise ValueError('Data larger than 1015 bytes')

        if len(ecc) != 10:
            raise ValueError('ECC must be exactly 10 bytes')

        padded_data = b'\x00' * (1015 - len(data)) + data
        array_data = [int(x) for x in padded_data] + self.__bytes_to_10bit_ecc(ecc)

        try:
            return bytes([x for x in rs.rs_correct_msg(array_data, 8, fcr=1)[0]])[-len(data):]

        except rs.ReedSolomonError as e:
            raise ECCError(*e.args)

    @property
    def size(self) -> int:
        return 10

class SpareType(IntEnum):
    RIFF = 0
    STANDARD = 1
    QCOM_2K = 2

class ECCFile(RawIOBase):
    def __init__(self, inp: str | RawIOBase, spare_offset_page_size: int=0, spare_type: int=SpareType.RIFF, bbm: int=5, page_width: int=16, ecc_algo: EccMeta=EccRs) -> None:
        self.__closed: bool = True

        if type(inp) == str:
            self.__fio: RawIOBase = open(inp, "rb")

        else:
            self.__fio: RawIOBase = inp

        self.__fio.seek(0)

        if spare_type == SpareType.RIFF:
            if not spare_offset_page_size:
                raise ValueError("An offset to spare data must be specified")

            self.__fio.seek(spare_offset_page_size)
            self.__eof: int = spare_offset_page_size
            self.__spare_io: BytesIO = BytesIO(self.__fio.read())
            self.__fio.seek(0)

        elif spare_type == SpareType.STANDARD:
            if not spare_offset_page_size:
                raise ValueError("A page size must be specified")

            self.__eof: int = (os.path.getsize(inp) // (spare_offset_page_size + (0x10 * (spare_offset_page_size // 0x200)))) * spare_offset_page_size
            self.__page_size: int = spare_offset_page_size

        elif spare_type == SpareType.QCOM_2K:
            self.__eof: int = (os.path.getsize(inp) // 0x210) * 0x200

        else:
            raise ValueError(f"Unknown spare type: {spare_type}")

        self.__bbm: int = bbm
        self.__page_width: int = page_width
        self.__ecc: EccMeta = ecc_algo()
        self.__cur_offset: int = 0
        self.__ecc_block: bytes = None
        self.__spare_type: int = spare_type
        self.__closed: bool = False

        self.seek(0)

    def __read_page(self) -> tuple[bytes, bytes]:
        if self.__cur_offset >= self.__eof:
            return b"", b""

        if self.__spare_type == SpareType.RIFF:
            return self.__fio.read(0x200), self.__spare_io.read(0x10)

        elif self.__spare_type == SpareType.STANDARD:
            data_offset_floor = (self.__cur_offset // self.__page_size) * (self.__page_size + ((self.__page_size // 0x200) * 0x10))

            data_offset = data_offset_floor + (((self.__cur_offset % self.__page_size) // 0x200) * 0x200)
            spare_offset = data_offset_floor + self.__page_size + (((self.__cur_offset % self.__page_size) // 0x200) * 0x10)

            self.__fio.seek(data_offset)
            a = self.__fio.read(0x200)
            self.__fio.seek(spare_offset)

            return a, self.__fio.read(0x10)

        elif self.__spare_type == SpareType.QCOM_2K:
            a = self.__fio.read(0x1d0 if self.__page_width == 16 else 0x1d1)
            self.__fio.read(2 if self.__page_width == 16 else 1)
            b = self.__fio.read(0x30 if self.__page_width == 16 else 0x2f)

            return a + b, self.__fio.read(0xe if self.__page_width == 16 else 0xf)

    def __update_ecc_block(self) -> None:
        ecc_d, ecc_s = self.__read_page()
        if ecc_d == b"":
            self.__ecc_block = ecc_d
            return

        if self.__spare_type != SpareType.QCOM_2K:
            bbm_mul = (self.__bbm * (2 if self.__page_width == 16 else 1))
            ecc_s = ecc_s[:bbm_mul] + ecc_s[bbm_mul + (2 if self.__page_width == 16 else 1):]

        try:
            self.__ecc_block = self.__ecc.decode(ecc_d, ecc_s[:self.__ecc.size])

        except ECCError:
            if ecc_s[:self.__ecc.size] != (b"\xff"*self.__ecc.size):
                print(f"Uncorrectable at 0x{self.__cur_offset:08x} (custom ecc?)")

            self.__ecc_block = ecc_d

    def seek(self, to: int, where: int=SEEK_SET) -> None:
        if where == SEEK_SET:
            self.__cur_offset = to

        elif where == SEEK_CUR:
            self.__cur_offset += to

        elif where == SEEK_END:
            if to <= 0: raise ValueError("offset in SEEK_END must not be 0")
            self.__cur_offset = self.__eof - to

        if self.__closed:
            return

        if self.__spare_type == SpareType.RIFF:
            self.__fio.seek((to // 0x200) * 0x200)
            self.__spare_io.seek((to // 0x200) * 0x10)

        elif self.__spare_type == SpareType.STANDARD:
            pass

        elif self.__spare_type == SpareType.QCOM_2K:
            self.__fio.seek((self.__cur_offset // 0x200) * 0x210)

        self.__update_ecc_block()

    def tell(self) -> int:
        return self.__cur_offset

    def read(self, count: int=-1) -> bytes:
        if self.__closed:
            return b""

        temp = bytearray()
        while (count < 0 or count > 0) and self.__ecc_block != b"":
            start_offset = (self.__cur_offset % 0x200)
            read_size = min(0x200 - start_offset, count) if count > 0 else 0x200 - start_offset

            temp += self.__ecc_block[start_offset:start_offset+read_size]

            if count != -1:
                count -= read_size

            self.__cur_offset += read_size

            if (start_offset + read_size) == 0x200:
                self.__update_ecc_block()

        return temp

    def close(self) -> None:
        self.__fio.close()
        if self.__spare_type == SpareType.RIFF:
            self.__spare_io.close()

        self.__closed = True

    def __del__(self) -> None:
        if not self.__closed:
            self.close()