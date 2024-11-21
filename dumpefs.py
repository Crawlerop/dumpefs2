from efs2 import *
from stat import filemode, S_ISDIR
from io import RawIOBase

def _do_efs_shell(s: EFS2, name: str):
    import shlex
    import os
    import sys
    import hexdump

    print("EFS2 shell")
    print(f"source file: {name} @ 0x{s.base_offset:08x}")

    while True:
        cmd = shlex.split(input(f"[{s.pwd}]> "))

        try:
            if len(cmd) > 0:
                if cmd[0] == "exit":
                    break

                elif cmd[0] in ["ls", "dir"]:
                    def print_info(l, info):
                        info_str = f"{filemode(info.mode)}  {info.modified_time.strftime('%Y-%m-%d %H:%M:%S')}  {info.created_time.strftime('%Y-%m-%d %H:%M:%S')}"
                        pad_num = (os.get_terminal_size().columns // 2) - len(l)
                        print(f"{l}{' '*pad_num}{info_str}")

                    if len(cmd) == 1:
                        for l, info in s.ls(""):
                            if l not in [".", ".."]: print_info(l, info)

                    elif len(cmd) == 2:
                        for l, info in s.ls(cmd[1]):
                            if l not in [".", ".."]: print_info(l, info)

                    else:
                        for k in cmd[1:]:
                            print(f"{k}:")
                            for l, info in s.ls(k):
                                if l not in [".", ".."]: print_info(l, info)

                elif cmd[0] == "cd":
                    if len(cmd) > 2:
                        print(f"{cmd[0]}: too many arguments")

                    elif len(cmd) == 2:
                        s.cd(cmd[1])

                elif cmd[0] == "dump":
                    if len(cmd) != 3:
                        print(f"{cmd[0]}: usage: {cmd[0]} filename destination")

                    elif cmd[1].endswith("*"):
                        def sf_recurse(p, h="", k=""):
                            for f in s.ls(h + p):
                                if f.endswith("/"):
                                    sf_recurse(f, h + p, p + k)

                                elif f not in [".", ".."]:
                                    t = s.open(h + p + f)
                                    os.makedirs(os.path.split(os.path.join(cmd[2], k, f))[0], exist_ok=True)
                                    open(os.path.join(cmd[2], k, f), "wb").write(t.read())

                        sf_recurse(cmd[1].rstrip("*"))

                    else:
                        t = s.open(cmd[1])
                        os.makedirs(os.path.split(cmd[2])[0], exist_ok=True)
                        open(cmd[2], "wb").write(t.read())

                elif cmd[0] == "pwd":
                    print(s.pwd)

                elif cmd[0] == "encoding":
                    if len(cmd) == 1:
                        print(s.encoding)

                    elif len(cmd) > 2:
                        print(f"{cmd[0]}: too many arguments")

                    else:
                        s.set_encoding(cmd[1])

                elif cmd[0] == "cat":
                    if len(cmd) == 1:
                        print(f"{cmd[0]}: usage: {cmd[0]} files...")

                    else:
                        for f in cmd[1:]:
                            t = s.open(f)
                            sys.stdout.buffer.write(t.read())

                elif cmd[0] in ["hd", "hexdump"]:
                    if len(cmd) == 1:
                        print(f"{cmd[0]}: usage: {cmd[0]} files...")

                    else:
                        for f in cmd[1:]:
                            t = s.open(f)
                            hexdump.hexdump(t.read())

                elif cmd[0] == "file":
                    if len(cmd) == 1:
                        print(f"{cmd[0]}: usage: {cmd[0]} files...")

                    else:
                        for f in cmd[1:]:
                            t = s.stat(f)
                            print(f"{f}: ")
                            print(f"    size: {t.file_size} bytes")
                            print(f"    modified time: {t.modified_time}")
                            print(f"    created time: {t.created_time}")
                            print(f"    number of blocks: {t.blocks}")
                            print(f"    generation: {t.generation}")

                elif cmd[0] == "help":
                    print("ls [files...] (list all files and folders in this directory)")
                    print("dir [files...] (ditto)")
                    print("cd [dir] (change the working directory)")
                    print("dump [files...] (read files and save)")
                    print("pwd (get the current working directory)")
                    print("encoding [encoding] (set the encoding used to read node filenames)")
                    print("cat files... (read files and output to console)")
                    print("hexdump files... (read files and output in hexdump)")
                    print("hd files... (short for hexdump)")
                    print("file files... (get file info)")
                    print("help (show this help message)")

                else:
                    print(f"{cmd[0]}: command not found")

        except Exception as e:
            print(f"{cmd[0]}: {type(e).__name__}: {e}")

if __name__ == "__main__":
    import zipfile
    import argparse

    def intorhex(d):
        try:
            return int(d)

        except ValueError:
            return int(d, 16)

    ap = argparse.ArgumentParser("dumpefs")
    ap.add_argument("in_filename", help="Source file")
    ap.add_argument("out_filename", help="Destination file (to zip, leave blank to enter shell)", nargs="?")

    ap.add_argument("-e", "--ecc", action="store_true", help="Enable ECC engine")
    ap.add_argument("-es", "--ecc-spare-offset", default=0, type=intorhex, help="Offset to spare (RIFF) or Page size (standard) when using ECC, use 0x prefix to parse as hexadecimal")
    ap.add_argument("-et", "--ecc-spare-type", choices=["riff", "standard", "qcom", "seperate"], default="riff", help="Specify which NAND format to parse: (riff = RIFF Box/Spare at end, standard = Data/Spare interleaved, qcom = QCOM NANDC 2k format, seperate = Seperate Data/NAND)")
    ap.add_argument("-eb", "--ecc-bbm", type=intorhex, default=5, help="Bad blocks offset (ineffective on QCOM nandc mode)")
    ap.add_argument("-ew", "--ecc-width", choices=[8, 16], default=16, type=int, help="Page width")
    ap.add_argument("-ea", "--ecc-algo", choices=["rs", "hamming20", "hamming20_bitpack"], default="rs", help="Error correction algorithm (rs = Reed-Solomon, hamming20 = Qualcomm 20-bit hamming code)")

    mg = ap.add_mutually_exclusive_group()
    mg.add_argument("-s", "--start-offset", type=intorhex, default=-1, help="Pointer to EFS2 filesystem (default: autodetect, use 0x prefix to parse as hexadecimal)")
    mg.add_argument("-p", "--partition", help="Specify the partition name as base offset")

    ap.add_argument("-sb", "--superblock", type=intorhex, default=-1, help="Superblock to use (default: latest)")
    ap.add_argument("-f", "--cefs", action="store_true", help="Open as CEFS (gang image)")
    ap.add_argument("-c", "--encoding", default="latin-1", help="Text encoding to use")
    ap.add_argument("-nl", "--no-log", default=False, help="Do not parse log journal (you shouldn't use this flag unless the file doesn't want to open)", action="store_true")
    ap.add_argument("-bs", "--block-size", default=0x20000, help="Block size (only applicable when using partition to determine offset)")

    args = ap.parse_args()
    s = None

    def lookup_partition(in_file: RawIOBase, part_name: str, block_size: int):
        partTable = None

        while True:
            a = in_file.read(block_size)

            try:
                if a[0x200:0x208] == b"\xAA\x73\xEE\x55\xDB\xBD\x5E\xE3":
                    partTable = PartitionTable(a[0x200:], block_size)
                    break

                elif a[0x800:0x808] == b"\xAA\x73\xEE\x55\xDB\xBD\x5E\xE3":
                    partTable = PartitionTable(a[0x800:], block_size)
                    break

                elif a[0x1000:0x1008] == b"\xAA\x73\xEE\x55\xDB\xBD\x5E\xE3":
                    partTable = PartitionTable(a[0x1000:], block_size)
                    break

            except Exception:
                pass

        if partTable is None:
            raise Exception("Could not find partition table")

        for p in partTable.partitions:
            if p.name == part_name:
                return p.start, p.end

        ap.error(f"Could not find partition with the name {part_name}")

    if args.cefs:
        if args.partition is not None:
            start = lookup_partition(open(args.in_filename, "rb"), args.partition, args.block_size)[0]

        else:
            start = 0 if args.start_offset == -1 else args.start_offset

        s = CEFS(open(args.in_filename, "rb"), start, args.encoding)

    else:
        if args.ecc:
            ecc_spare_type_map = {"riff": SpareType.RIFF, "standard": SpareType.STANDARD, "qcom": SpareType.QCOM_2K}
            ecc_algo_map = {"rs": EccRs, "hamming20": EccHamming20, "hamming20_bitpack": EccHamming20Bitpack}

            if args.partition is not None:
                start, end = lookup_partition(ECCFile(args.in_filename, args.ecc_spare_offset, ecc_spare_type_map[args.ecc_spare_type], args.ecc_bbm, args.ecc_width, ecc_algo_map[args.ecc_algo]), args.partition, args.block_size)

            else:
                start = args.start_offset
                end = -1

            try:
                s = EFS2(open(args.in_filename, "rb"), start, args.superblock, io_wrapper=lambda x: ECCFile(x, args.ecc_spare_offset, ecc_spare_type_map[args.ecc_spare_type], args.ecc_bbm, args.ecc_width, ecc_algo_map[args.ecc_algo]), log=not args.no_log, encoding=args.encoding, end_offset=end)

            except ValueError as e:
                ap.error(e)

        else:
            if args.partition is not None:
                start, end = lookup_partition(open(args.in_filename, "rb"), args.partition, args.block_size)

            else:
                start = args.start_offset
                end = -1

            s = EFS2(open(args.in_filename, "rb"), start, args.superblock, io_wrapper=None, log=not args.no_log, encoding=args.encoding, end_offset=end)

    if args.out_filename is None:
        _do_efs_shell(s, args.in_filename)

    else:
        with zipfile.ZipFile(args.out_filename, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for f, inode in s.ls_recursive("/"):
                print(f)
                try:
                    date = inode.modified_time.timetuple()[:6]
                    info = zipfile.ZipInfo(filename=f.lstrip("/"), date_time=date if date[0] >= 1980 else (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    if S_ISDIR(inode.mode):
                        zf.open(info, "w").write(b"")

                    else:
                        zf.open(info, "w").write(s.open(f).read())

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"error: {e}")