from crcmod import mkCrcFun
from math import log2

EFS_CRC = mkCrcFun(0x11021, initCrc=0, xorOut=0xffff)

def actual_version(i):
    return i & 0xff

def ilog2(x):
    return int(log2(x))

def by2int(x):
    return int.from_bytes(x, "little")

def by2int_s(x):
    return int.from_bytes(x, "little", signed=True)