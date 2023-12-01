#!/usr/bin/env python
# pylint: disable=logging-format-interpolation
"""
If an instance was launched from an autoscaling group, it will come up with no
Name: tag.  This script assigns an appropriate name tag to the instance.  The
name will have one of the following patterns.

If this instance is an ECS container machine:
    ecs.{asg.name}.{zone-abbr}.{number}

Where {zone-abbr} is the availability zone name of the instance minus the region
name

Otherwise:
    {asg.name}-{number}

In both cases, ${number} will be chosen to be the lowest positive integer that
is not already taken by another instance in the autoscaling group.

In order to run this on an instance, you'll need to have a policy with this body
attached to the instance role::

    {
    "Version": "2012-10-17",
    "Statement": [
        {
        "Effect": "Allow",
        "Action": [
            "ec2:CreateTags",
            "ec2:DeleteTags",
            "ec2:Describe*"
            "autoscaling:Describe*"
        ],
        "Resource": ["*"]
        }
    ]
    }
"""

import logging
import logging.config
from optparse import OptionParser  # pylint: disable=deprecated-module
import os
import re
import sys
from typing import Tuple, Dict, Any, List, Optional, cast

import boto3

from .metadata import EC2Metadata


address: str = "/dev/log"
if sys.platform == "darwin":
    address = "/var/run/syslog"


LOGGING: Dict[str, Any] = {
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
        "autonamer": {
            "handlers": ["syslog", "stderr"],
            "level": logging.DEBUG,
            "propagate": True,
        },
    },
}

logging.config.dictConfig(LOGGING)
logger = logging.getLogger("autonamer")


def parse_arguments(argv):
    usage = """usage: %prog [flags] [<instance-id>]

If an instance was launched from an autoscaling group, it will come up with no
Name: tag.  This script assigns an appropriate name tag to the instance.

If <instance-id> is not supplied, %prog will ask the EC2 instance metadata
endpoint for the instance id.

The name will have one of the following patterns:

If this instance is an ECS container machine:
ecs.{autoscalinggroup_name}.{zone-abbr}.{number}, where {zone-abbr} is the
availability zone name of the instance minus the region name.

Otherwise: {autoscalinggroup_name}-{number}

In both cases, {number} will be chosen to be the lowest positive integer that is
not already taken by another instance in the autoscaling group.
"""
    parser = OptionParser(usage=usage)

    (options, _) = parser.parse_args(argv)

    instance_id = None
    if len(argv) > 1:
        instance_id = argv[1]
    else:
        instance_id = EC2Metadata().get("instance-id")

    if not instance_id:
        parser.print_usage()
        sys.exit(1)
    return (options, instance_id)


class Instance(object):
    """
    This is a wrapper class to boto3.ec2.Instance to mostly make working with
    instance tags more straightforward.
    """

    def __init__(self, instance_id: str) -> None:
        self.ec2 = boto3.resource("ec2")
        self.instance = self.ec2.Instance(instance_id)

    @property
    def instance_id(self) -> str:
        """
        Return the instance id of this instance.
        """
        return self.instance.instance_id

    @property
    def tags(self) -> Dict[str, Optional[str]]:
        """
        Return the tags for this instance as a dictionary.
        """
        tags = {}
        for tag in self.instance.tags:
            tags[tag["Key"]] = tag["Value"]
        return tags

    @property
    def zone(self) -> str:
        """
        Return the availability zone of this instance.
        """
        return self.instance.placement["AvailabilityZone"]

    @property
    def zone_abbr(self) -> str:
        """
        Return the zone name minus the region name.

        Example:
            If the zone is "us-west-2b", return "b".
        """
        return re.sub(boto3.session.Session().region_name, "", self.zone)

    @property
    def name(self) -> Optional[str]:
        """
        Return the current Name tag on this instance.

        Returns:
            The value of the Name tag, or None if there is no Name tag.
        """
        return self.tags.get("Name", None)

    @name.setter
    def name(self, name: str) -> None:
        """
        Set the Name tag on this instance to ``name``.

        Args:
            name: the name to set
        """
        self.instance.create_tags(Tags=[{"Key": "Name", "Value": name}])

    @property
    def autoscaling_group(self) -> Optional[str]:
        """
        Return the autoscaling group name for this instance.
        """
        return self.tags.get("aws:autoscaling:groupName", None)


class GroupNamer(object):
    """
    Set the name for an instance that is part of an autoscaling group but is not
    part of an ECS cluster.  The name will have the pattern
    "{group.name}-{number}".
    """

    def __init__(self, instance_id: str) -> None:
        self.instance = Instance(instance_id)
        logger.info(f"instance.loaded instance_id={self.instance.instance_id}")
        if self.instance.name:
            logger.error(
                "instance.has-name instance_id={} name={}".format(
                    self.instance.instance_id, self.instance.name
                )
            )
            raise ValueError(
                "Instance {} already has a name.".format(self.instance.instance_id)
            )
        if not self.instance.autoscaling_group:
            logger.error(
                "instance.not-in-asg instance_id={}".format(self.instance.instance_id)
            )
            raise KeyError(
                "Instance {} is not in an autoscaling group".format(
                    self.instance.instance_id
                )
            )
        self.asg = boto3.client("autoscaling")
        logger.info(
            "group.loaded group_name={} n_instances={}".format(
                self.group_name, len(self.group["Instances"])
            )
        )

    @property
    def group(self) -> Dict[str, Any]:
        """
        Return the autoscaling group data that we get from
        ``describe_auto_scaling_groups`` for the group :py:attr:`name`.
        """
        return self.asg.describe_auto_scaling_groups(
            AutoScalingGroupNames=[self.instance.autoscaling_group]
        )["AutoScalingGroups"][0]

    @property
    def group_name(self) -> str:
        """
        Return the name of the autoscaling group that this instance is in.
        """
        return self.group["AutoScalingGroupName"]

    @property
    def name_pattern(self) -> str:
        """
        Set the naming pattern for instances in this ASG.  Pattern:
        "{group.name}-{number}".
        """
        return "{}-".format(re.sub("_", "-", self.group_name))

    def get_named_instances(self, instances: List[Instance]) -> List[Instance]:
        """
        Possibly filter the list of named instances.  This exists so that it can
        be overriding in subclasses.

        Args:
            instances: a list of instances in the same ASG as
                :py:attr:`instance` that do have a Name tag.

        Returns:
            A possibly filtered list of instances.
        """
        return instances

    def get_unnamed_instances(self, instances: List[Instance]) -> List[Instance]:
        """
        Possibly filter the list of unnamed instances.  This exists so that it
        can be overriding in subclasses.

        Args:
            instances: a list of instances in the same ASG as
                :py:attr:`instance` that do not have a Name tag.

        Returns:
            A possibly filtered list of instances.
        """
        return instances

    def instances(self, retry: bool = False) -> Tuple[List[Instance], List[Instance]]:
        """
        Return a list of :py:class:`Instance` objects of all the running
        instances in the ASG that are not :py:attr:`instance`, and that have a
        Name tag.

        Keyword Args:
            retry: if True, we've already tried to get the list of instances
                at least once, and this is our second attempt, so don't
                do the sleep to try to avoid naming conflicts.

        Returns:
            A 2-tuple of list of :py:class:`Instance` objects that have a Name tag
            and list of :py:class:`Instance` objects that do not have a Name tag.
        """
        named: List[Instance] = []
        unnamed: List[Instance] = []
        for sibling in self.group["Instances"]:
            # Ignore any instances that are leaving or have left the group
            if sibling["LifecycleState"] in [
                "Terminating",
                "Terminating:Wait",
                "Terminating:Proceed",
                "Terminated",
                "Detaching",
                "Detached",
            ]:
                continue
            # Ignore our own instance
            if sibling["InstanceId"] == self.instance.instance_id:
                continue
            instance = Instance(sibling["InstanceId"])
            # Ignore unnamed instances
            if not instance.name:
                unnamed.append(instance)
                continue
            named.append(instance)
            _unnamed = self.get_unnamed_instances(unnamed)
            _named = self.get_named_instances(named)
        return _named, _unnamed

    def name_instance(self) -> None:
        """
        Set the Name tag on :py:attr:`instance`.
        """
        # get the list of instances in the ASG that both have and do not have a
        # Name tag
        named, unnamed = self.instances()
        # For those instances that do have a Name tag, get the number suffix
        taken = [cast(str, instance.name) for instance in named]
        taken_ids = [name.replace(self.name_pattern, "") for name in taken]
        # Now assign an untaken number suffix to each of the unnamed instances
        # We need to do this determininstically so all the unnamed instances
        # will get the same number suffixes on all the instances in the ASG
        instance_ids = [instance.instance_id for instance in unnamed]
        instance_ids.append(self.instance.instance_id)
        instance_ids.sort()
        _max = len(instance_ids) + len(taken_ids)
        available_ids = [i for i in range(1, _max + 1) if str(i) not in taken_ids]
        # Make a mapping of instance ids to available ids
        mapping = dict(zip(instance_ids, available_ids))
        # Choose the id assigned to our instance_id
        name = f"{self.name_pattern}{mapping[self.instance.instance_id]}"
        # Set the name
        self.instance.name = name
        logger.info(
            "instance.named instance_id={} name={}".format(
                self.instance.instance_id, name
            )
        )


class ECSGroupNamer(GroupNamer):
    """
    Set the name for an instance that is part of an ECS cluster. The name will
    have the pattern "ecs.{group.name}.{zone-abbr}.{number}".
    """

    @property
    def name_pattern(self) -> str:
        """
        Get the naming pattern for instances in this ECS cluster ASG.  Pattern:
        "ecs.{group.name}.{zone-abbr}.{number}".
        """
        return "ecs.{}.{}.".format(self.group_name, self.instance.zone_abbr)

    def get_named_instances(self, instances: List[Instance]) -> List[Instance]:
        """
        For ECS clusters, we only want to consider instances in the same AZ as
        :py:attr:`instance`.

        Args:
            instances: a list of instances in the same ASG as
                :py:attr:`instance` that do have a Name tag.

        Returns:
            A possibly filtered list of instances.
        """
        return [
            instance for instance in instances if instance.zone == self.instance.zone
        ]

    def get_unnamed_instances(self, instances: List[Instance]) -> List[Instance]:
        """
        For ECS clusters, we only want to consider instances in the same AZ as
        :py:attr:`instance`.

        Args:
            instances: the list of instances to filter

        Returns:
            A list of unnamed instances in the same AZ as :py:attr:`instance`.
        """
        return [
            instance for instance in instances if instance.zone == self.instance.zone
        ]

def main(argv=sys.argv):
    """
    argv[1] is the instance id for this instance.
    """
    (_, instance_id) = parse_arguments(argv)

    if os.path.exists("/etc/ecs/ecs.config"):
        logger.info("start instance_id={} type=ecs".format(instance_id))
        namer_class = ECSGroupNamer
    else:
        logger.info("start instance_id={} type=asg".format(instance_id))
        namer_class = GroupNamer

    try:
        namer = namer_class(instance_id)
    except KeyError:
        return 1
    except ValueError:
        return 1
    namer.name_instance()
    logger.info("end instance_id={}".format(instance_id))


if __name__ == "__main__":
    sys.exit(main())
