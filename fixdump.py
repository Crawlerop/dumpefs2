from efs2 import *

if __name__ == "__main__":
    import argparse

    def intorhex(d):
        try:
            return int(d)

        except ValueError:
            return int(d, 16)

    ap = argparse.ArgumentParser("QC dump fixer")
    ap.add_argument("in_filename", help="Source file")
    ap.add_argument("out_filename", help="Destination file")
    ap.add_argument("spare_offset", nargs="?", type=intorhex, help="Offset to spare (RIFF) or Page size (standard)")
    ap.add_argument("-s", "--spare-type", choices=["riff", "standard", "qcom", "seperate"], default="riff", help="Specify which NAND format to parse: (riff = RIFF Box/Spare at end, standard = Data/Spare interleaved, qcom = QCOM NANDC 2k format, seperate = Seperate Data/NAND)")
    ap.add_argument("-b", "--bbm", type=intorhex, default=5, help="Bad blocks offset (ineffective on QCOM nandc mode)")
    ap.add_argument("-w", "--width", choices=[8, 16], default=16, type=int, help="Page width")
    ap.add_argument("-e", "--ecc-algo", choices=["rs", "hamming20"], default="rs", help="Error correction algorithm (rs = Reed-Solomon, hamming20 = Qualcomm 20-bit hamming code)")

    args = ap.parse_args()

    ecc_spare_type_map = {"riff": SpareType.RIFF, "standard": SpareType.STANDARD, "qcom": SpareType.QCOM_2K}
    ecc_algo_map = {"rs": EccRs, "hamming20": EccHamming20}

    nand = ECCFile(open(args.in_filename, "rb"), args.spare_offset, ecc_spare_type_map[args.spare_type], args.bbm, args.width, ecc_algo_map[args.ecc_algo])
    nand_decoded = open(args.out_filename, "wb")

    while True:
        temp = nand.read(0x200)
        if temp == b"":
            break

        nand_decoded.write(temp)
