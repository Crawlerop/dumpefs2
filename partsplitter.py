from efs2 import *

if __name__ == "__main__":
    import argparse
    import os

    def intorhex(d):
        try:
            return int(d)

        except ValueError:
            return int(d, 16)

    ap = argparse.ArgumentParser("QC dump fixer")
    ap.add_argument("in_filename", help="Source file")
    ap.add_argument("out_folder", help="Destination folder")
    ap.add_argument("block_size", type=intorhex, help="Block size (0x4000 for 512 bytes, 0x20000 for 2k bytes)")

    args = ap.parse_args()
    partTable = None

    in_file = open(args.in_filename, "rb")
    os.makedirs(args.out_folder, exist_ok=True)

    while True:
        a = in_file.read(args.block_size)

        try:
            if a[0x200:0x208] == b"\xAA\x73\xEE\x55\xDB\xBD\x5E\xE3":
                partTable = PartitionTable(a[0x200:], args.block_size)
                break

            elif a[0x800:0x808] == b"\xAA\x73\xEE\x55\xDB\xBD\x5E\xE3":
                partTable = PartitionTable(a[0x800:], args.block_size)
                break

            elif a[0x1000:0x1008] == b"\xAA\x73\xEE\x55\xDB\xBD\x5E\xE3":
                partTable = PartitionTable(a[0x1000:], args.block_size)
                break

        except Exception:
            pass

    for p in partTable.partitions:
        in_file.seek(p.start)
        
        if p.name in ["EFS2", "EFS2APPS"] and p.length == -1:
            data = in_file.read()
            data = data[:compute_efs2_size(data)]
            
        else:
            data = in_file.read(p.length if p.length >= 0 else None)
        
        open(os.path.join(args.out_folder, f"{p.name}.bin"), "wb").write(data)