#!/usr/bin/env python
from __future__ import print_function

from optparse import OptionParser
import subprocess
import sys

import boto3


def parse_arguments(argv):
    usage = """usage: %prog [flags] <NAME> [<command>]

Look up the private IP address of a running EC2 instance by its Name tag and ssh
into it.

If <command> is supplied, run that shell command on the remote instance and
exit.

If multiple instances have the same Name tag, print info about all found
instances and exit.
"""
    parser = OptionParser(usage=usage)
    parser.add_option(
        "-t",
        "--tag",
        dest="tag",
        help="set TAG to check to find instances via this tag.  Default: Name.",
        metavar="TAG",
        default="Name",
    )
    parser.add_option(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        help="Make ssh print verbose debug messages",
        default=False,
    )

    (options, args) = parser.parse_args(argv)

    if len(args) == 1:
        parser.print_usage()
        sys.exit(1)
    value = args[1]
    cmd = ""
    if len(args) > 1:
        cmd = " ".join(args[2:])
    return (options, value, cmd)


class Instance(object):
    """
    This is a wrapper class to boto3.ec2.Instance to mostly make working with
    instance tags more straightforward.
    """

    def __init__(self, value: str, tag: str = "Name") -> None:
        self.client = boto3.client("ec2")
        # Find any running instances with our desired tag value
        reservations = self.client.describe_instances(
            Filters=[
                {"Name": "tag:{}".format(tag), "Values": [value]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
        instances = []
        for r in reservations["Reservations"]:
            instances.extend(r["Instances"])
        if len(instances) == 0:
            raise KeyError('No instance with {}="{}"'.format(tag, value))
        if len(instances) > 1:
            print('ERROR: Found multiple instances with {}="{}":'.format(tag, value))
            print()
            print("instance-id       private-ip       public-ip")
            print("----------------------------------------------------")
            for i in instances:
                print(
                    "{:<17}  {:<15}  {:<15}".format(
                        i["InstanceId"], i["PrivateIpAddress"], i["PublicIpAddress"]
                    )
                )
            raise ValueError
        self.instance = instances[0]

    def ssh(self, cmd: str = "", verbose: bool = False) -> None:
        """
        Actually ssh into the instance.

        Args:
            cmd: if supplied, run this command on the remote instance and exit.
            verbose: if ``True``, make ssh print verbose debug messages.
        """
        ssh = ["ssh", "-A", "-x", "-t", "-o", "StrictHostKeyChecking=no"]
        if verbose:
            ssh.append("-vv")
        ssh.extend(["ec2-user@{}".format(self.instance["PrivateIpAddress"]), cmd])
        subprocess.call(ssh)


def main(argv=None):
    if not argv:
        argv = sys.argv

    (options, value, cmd) = parse_arguments(argv)
    try:
        instance = Instance(value, tag=options.tag)
    except KeyError as e:
        sys.stderr.write(str(e) + "\n")
        return 1
    except ValueError:
        return 1
    instance.ssh(cmd=cmd, verbose=options.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
