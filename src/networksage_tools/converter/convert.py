"""
    Copyright 2021-2022 SeclarityIO, LLC
    Code created by David Pearson (david@seclarity.io).
    The functions in this file handle PCAP, PCPANG, Zeek, and Interflow files. They remove all local-to-local traffic,
    then convert them into a Secflow format (which is similar to but more lightweight than Zeek flows).

    For license information, please see the accompanying LICENSE file in the top-level directory of this repository.
"""
import argparse
import sys
import platform
import pathlib
from networksage_tools.converter import pcaputils
from networksage_tools.converter import generic_flowutils
from networksage_tools.converter import zeekutils
from networksage_tools.converter import interflowutils
from networksage_tools.common_utilities import utilities
from networksage_tools.common_utilities import dnsservice


def finish_conversion(dns, utils):
    """Handle final conversion of inputs that don't depend on input-specific information.
    """
    # get passive DNS
    dns.get_passive_dns()
    # print("Found", len( utils.passive_dns_names_dict), "passive dns names")

    # use domain names instead of IP addresses wherever possible
    dns.map_destination_ips_to_names()

    # add current file's DNS to the PDNS file (for PCAPs).
    dns.update_passive_dns_repository()

    # save secFlows to file for hashing and to prepare final format
    utils.save_secflows_to_file()
    uuid = utils.get_random_uuid()
    utils.set_hash_value_for_sample(uuid)

    # capture secFlows in JSON format, and store with all information for final transmission
    utils.prepare_final_output_file()

    # check if output file looks sane
    utils.check_output_sanity()

    print("Cleaning up temporary files")
    utils.cleanup_files()

    if utils.output_dir is not None:
        # relocate the file
        utils.output_dir = pathlib.Path(utils.output_dir) # make sure it's a real Path object
        # create the directory if it doesn't exist
        utils.output_dir.mkdir(parents=True, exist_ok=True)
        start_path = pathlib.Path(utils.secflow_output_filepath)
        filename = start_path.stem + start_path.suffix
        utils.secflow_output_filepath = str(start_path.rename(pathlib.PurePath(utils.output_dir, filename)))
    print("Conversion complete! Final Secflow Output stored at", utils.secflow_output_filepath)


def convert_zeek(zeekfile_location, zeek_dnsfile_location=None, output_dir=None):
    """Handles all of the Zeek-specific conversion needs. Takes an optional DNS log.
    """
    my_platform = platform.system().lower()
    utils = utilities.Utilities(str(zeekfile_location), my_platform, output_dir=output_dir, sample_type="Zeek")  # create an instance of utils to use
    dns = dnsservice.DnsService(utils)  # create an instance of the DnsService class to use

    if zeek_dnsfile_location is not None:
        # store it if it exists
        dns.dns_logfile_path = str(zeek_dnsfile_location)

    # there's no filtered file in Zeek, so just grab name from original file.
    utils.filtered_filepath = utils.original_filepath

    # make sure the file is a valid Zeek conn log
    generic_flowutils.validate_file_format(utils)
    #zeekutils.validate_file_format(utils)

    # most of the heavy lifting happens here
    success = zeekutils.zeek_2_secflows(utils)
    if success and len(utils.secflows) > 0:
        finish_conversion(dns, utils)
    else:
        print("No traffic was converted to Secflows.")
        utils.cleanup_files()


def convert_interflow(interflow_location, output_dir=None):
    """Handles all of the Interflow-specific conversion needs.
    """
    my_platform = platform.system().lower()
    utils = utilities.Utilities(str(interflow_location), my_platform, output_dir=output_dir, sample_type="Interflow")  # create an instance of utils to use
    dns = dnsservice.DnsService(utils)  # create an instance of the DnsService class to use

    # there's no filtered file in Interflow, so just grab name from original file.
    utils.filtered_filepath = utils.original_filepath

    # make sure the file is a valid Interflow log
    generic_flowutils.validate_file_format(utils)

    # most of the heavy lifting happens here
    success = interflowutils.interflow_2_secflows(utils, dns)
    if success and len(utils.secflows) > 0:
        finish_conversion(dns, utils)
    else:
        print("No traffic was converted to Secflows.")
        utils.cleanup_files()


def convert_pcap(pcapfile_location, output_dir=None):
    """Handles all of the PCAP-specific conversion needs. Supports PCAPNG as well.
    """
    my_platform = platform.system().lower()
    utils = utilities.Utilities(str(pcapfile_location), my_platform, output_dir=output_dir, sample_type="PCAP")  # create an instance of utils to use
    dns = dnsservice.DnsService(utils)  # create an instance of the DnsService class to use

    # make sure the file is a valid capture file
    pcaputils.validate_file_format(utils)

    # most of the heavy lifting happens here
    pcaputils.pcap_to_secflow_converter(utils, dns)

    """ we only know how long a secFlow lasted when we've captured it all, so go back through the dictionary and update this now.
    """
    utils.set_secflow_durations()
    if len(utils.secflows) > 0:
        finish_conversion(dns, utils)
    else:
        print("No traffic was converted to Secflows.")
        utils.cleanup_files()



if __name__ == "__main__":
    # handle all arguments
    parser = argparse.ArgumentParser()
    zeek_group = parser.add_argument_group("zeek", "arguments available when analyzing Zeek files")
    zeek_group.add_argument("-z", "--zeekConnLog", help="a valid Zeek conn.log file", type=str)
    zeek_group.add_argument("-d", "--zeekDNSLog", help="a valid Zeek dns.log file")

    cap_group = parser.add_argument_group("pcap", "arguments available when analyzing capture (CAP, PCAP, PCAPNG) files")
    cap_group.add_argument("-p", "--pcap"
                          , help="indicates that a capture file (usually PCAP or PCAPNG) will be the input file to parse"
                          , type=str)

    interflow_group = parser.add_argument_group("interflow", "arguments available when analyzing Interflow files")
    interflow_group.add_argument("--interflowLog", help="a valid Interflow JSON log file", type=str)

    args = parser.parse_args()

    pcapfile_location = None
    zeekfile_location = None
    zeek_dnsfile_location = None
    interflow_location = None

    if (args.zeekConnLog and args.pcap) or (args.pcap and args.interflowLog) or (args.zeekConnLog and args.interflowLog):
        """
        Check if multiple input types were inputted 
        """
        print("Error: can only parse Zeek OR PCAP OR Interflow, not many at same time.")
        sys.exit(1)
    elif args.zeekConnLog:
        zeekfile_location = pathlib.Path(args.zeekConnLog)
        if not zeekfile_location.is_file():
            print("Error:", zeekfile_location, "does not exist.")
            sys.exit(1)
        if args.zeekDNSLog:
            zeek_dnsfile_location = pathlib.Path(args.zeekDNSLog)
            if not zeek_dnsfile_location.is_file():
                print("Error:", zeek_dnsfile_location, "does not exist.")
                sys.exit(1)
        else:
            print("No Zeek DnsService log specified. Naming of secFlows may be suboptimal.")
            zeek_dnsfile_location = None
    elif args.pcap:
        pcapfile_location = pathlib.Path(args.pcap)
        if not pcapfile_location.is_file():
            print("Error:", pcapfile_location, "does not exist.")
            sys.exit(1)
    elif args.interflowLog:
        interflow_location = pathlib.Path(args.interflowLog)
    else:
        print("Missing -p, -z, or --interflowLog argument.")
        sys.exit(1)

    """
        Input type-specific file processing in this section
    """
    if args.zeekConnLog:
        convert_zeek(zeekfile_location, zeek_dnsfile_location)
    elif args.pcap:
        convert_pcap(pcapfile_location)
    elif args.interflowLog:
        convert_interflow(interflow_location)
