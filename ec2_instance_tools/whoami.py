#!/usr/bin/env python
# pylint: disable=logging-format-interpolation
import logging
import logging.config
from optparse import OptionParser  # pylint: disable=deprecated-module
import os
import sys
from typing import Dict, cast

import boto3

from ec2_instance_tools.metadata import EC2Metadata


address: str = "/dev/log"
if sys.platform == "darwin":
    address = "/var/run/syslog"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "stderr": {
            "class": "logging.StreamHandler",
            "stream": sys.stderr,
            "formatter": "verbose",
        },
        "syslog": {
            "class": "logging.handlers.SysLogHandler",
            "address": address,
            "facility": "local0",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "whoami": {
            "handlers": ["syslog", "stderr"],
            "level": logging.DEBUG,
            "propagate": True,
        },
    },
}

logging.config.dictConfig(LOGGING)
logger = logging.getLogger("whoami")

METADATA: EC2Metadata = EC2Metadata()
os.environ["AWS_DEFAULT_REGION"] = cast(str, METADATA.get("region"))


def parse_arguments(argv):
    usage = """usage: %prog [flags]

Get this instance's name tag, and save it to /etc/aws-instance-name for use by
other programs.

%prog will ask the EC2 instance metadata endpoint for the instance id.
"""
    parser = OptionParser(usage=usage)
    (options, args) = parser.parse_args(argv)
    if len(argv) > 1:
        parser.print_usage()
        sys.exit(1)
    return (options, args)


class Instance(object):
    """
    This is a wrapper class to boto3.ec2.Instance to mostly make working with
    instance tags more straightforward.
    """

    def __init__(self) -> None:
        self.ec2 = boto3.resource("ec2")
        instance_id: str = cast(str, METADATA.get("instance-id"))
        self.instance = self.ec2.Instance(instance_id)

    @property
    def instance_id(self) -> str:
        return self.instance.instance_id

    @property
    def tags(self) -> Dict[str, str]:
        tags = {}
        for tag in self.instance.tags:
            tags[tag["Key"]] = tag["Value"]
        return tags

    @property
    def name(self):
        return self.tags.get("Name", None)


def main(argv=sys.argv):
    parse_arguments(argv)

    logger.info("start")
    instance = Instance()
    name = instance.name
    with open("/etc/aws-instance-name", "w", encoding="utf-8") as fd:
        fd.write(name)
    logger.info(
        "end instance_id={} name={} file=/etc/aws-instance-name".format(
            instance.instance_id, name
        )
    )


if __name__ == "__main__":
    sys.exit(main())
