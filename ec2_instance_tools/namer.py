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
import random
import time
from typing import Dict, Any, List

import boto3

from .metadata import EC2Metadata


address: str = '/dev/log'
if sys.platform == "darwin":
    address = '/var/run/syslog'


LOGGING: Dict[str, Any] = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'stderr': {
            'class': 'logging.StreamHandler',
            'stream': sys.stderr,
            'formatter': 'verbose',
        },
        'syslog': {
            'class': 'logging.handlers.SysLogHandler',
            'address': address,
            'facility': "local0",
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'autonamer': {
            'handlers': ['syslog', 'stderr'],
            'level': logging.DEBUG,
            'propagate': True,
        },
    }
}

logging.config.dictConfig(LOGGING)
logger = logging.getLogger('autonamer')


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
        instance_id = EC2Metadata().get('instance-id')

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
        self.ec2 = boto3.resource('ec2')
        self.instance = self.ec2.Instance(instance_id)

    @property
    def instance_id(self) -> str:
        """
        Return the instance id of this instance.
        """
        return self.instance.instance_id

    @property
    def tags(self) -> Dict[str, str]:
        """
        Return the tags for this instance as a dictionary.
        """
        tags = {}
        for tag in self.instance.tags:
            tags[tag['Key']] = tag['Value']
        return tags

    @property
    def zone(self) -> str:
        """
        Return the availability zone of this instance.
        """
        return self.instance.placement['AvailabilityZone']

    @property
    def zone_abbr(self) -> str:
        """
        Return the zone name minus the region name.

        Example:
            If the zone is "us-west-2b", return "b".
        """
        return re.sub(boto3.session.Session().region_name, "", self.zone)

    @property
    def name(self) -> str:
        """
        Return the current Name tag on this instance.

        Returns:
            The value of the Name tag, or None if there is no Name tag.
        """
        return self.tags.get('Name', None)

    @name.setter
    def name(self, name: str) -> None:
        """
        Set the Name tag on this instance to ``name``.

        Args:
            name: the name to set
        """
        self.instance.create_tags(Tags=[{'Key': 'Name', 'Value': name}])

    @property
    def autoscaling_group(self) -> str:
        """
        Return the autoscaling group name for this instance.
        """
        return self.tags.get('aws:autoscaling:groupName', None)


class GroupNamer(object):
    """
    Set the name for an instance that is part of an autoscaling group but is not
    part of an ECS cluster.  The name will have the pattern
    "{group.name}-{number}".
    """

    def __init__(self, instance_id: str) -> None:
        self.instance = Instance(instance_id)
        logger.info(
            'instance.loaded instance_id={}'.format(self.instance.instance_id)
        )
        if self.instance.name:
            logger.error('instance.has-name instance_id={} name={}'.format(
                self.instance.instance_id,
                self.instance.name
            ))
            raise ValueError(
                'Instance {} already has a name.'.format(self.instance.instance_id)
            )
        if not self.instance.autoscaling_group:
            logger.error(
                'instance.not-in-asg instance_id={}'.format(
                    self.instance.instance_id
                )
            )
            raise KeyError(
                'Instance {} is not in an autoscaling group'.format(
                    self.instance.instance_id
                )
            )
        self.asg = boto3.client('autoscaling')
        logger.info(
            'group.loaded group_name={} n_instances={}'.format(
                self.name,
                len(self.group['Instances'])
            )
        )

    @property
    def group(self) -> Dict[str, Any]:
        self.group = self.asg.describe_auto_scaling_groups(
            AutoScalingGroupNames=[self.instance.autoscaling_group]
        )['AutoScalingGroups'][0]

    @property
    def name(self) -> str:
        """
        Return the name of the autoscaling group that this instance is in.
        """
        return self.group['AutoScalingGroupName']

    @property
    def name_pattern(self) -> str:
        """
        Set the naming pattern for instances in this ASG.  Pattern:
        "{group.name}-{number}".
        """
        return "{}-".format(re.sub("_", "-", self.name))

    @property
    def live_instances(self) -> List[Instance]:
        """
        Return a list of :py:class:`Instance` objects of all the running instances
        in the ASG that are not :py:attr:`instance`.
        """
        live: List[Instance] = []
        unnamed: List[Instance] = []
        for sibling in self.group['Instances']:
            # Ignore any instances that are leaving or have left the group
            if sibling['LifecycleState'] in [
                'Terminating',
                'Terminating:Wait',
                'Terminating:Proceed',
                'Terminated',
                'Detaching',
                'Detached'
            ]:
                continue
            # Ignore our own instance
            if sibling['InstanceId'] == self.instance.instance_id:
                continue
            instance = Instance(sibling['InstanceId'])
            # Ignore unnamed instances
            if not instance.name:
                unnamed.append(instance)
                continue
            live.append(instance)
        # If there are any unnamed instances in the same AZ as self.instance,
        # sleep for a random amount of time between 0 and 20 seconds to try
        # to avoid choosing the same name that one of those instances will
        # choose.  We need each instance to choose a unique name so that our
        # graphite and statsd reporting will work correctly.
        unnamed_same_zone = [
            instance for instance in unnamed
            if instance.zone == self.instance.zone
        ]
        if unnamed_same_zone:
            sleep_time = random.uniform(0, 20)
            logger.info(
                'instances.unnamed-same-zone n_instances={} sleeping={}s'.format(
                    len(unnamed_same_zone),
                    sleep_time
                )
            )
            time.sleep(sleep_time)
        return live

    @property
    def existing_names(self) -> List[str]:
        """
        Return a list of Name tag values for all live instances that are not
        self.instance.
        """
        return [instance.name for instance in self.live_instances]

    def name_instance(self) -> None:
        """
        Set the Name tag on :py:attr:`instance`.  Choose a name with the lowest
        number that does not conflict with other running instances in the ASG.
        """
        taken = self.existing_names
        i: int = 1
        while True:
            name = "{}{}".format(self.name_pattern, i)
            if name not in taken:
                break
            i += 1
        self.instance.name = name
        logger.info(
            'instance.named instance_id={} name={}'.format(
                self.instance.instance_id,
                name
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
        return "ecs.{}.{}.".format(self.name, self.instance.zone_abbr)

    @property
    def existing_names(self) -> List[str]:
        """
        Return the list of Name tag values for all live instances in the same AZ
        as self.instance.
        """
        return [
            instance.name
            for instance in self.live_instances
            if instance.zone == self.instance.zone
        ]


def main(argv=sys.argv):
    """
    argv[1] is the instance id for this instance.
    """
    (_, instance_id) = parse_arguments(argv)

    if os.path.exists('/etc/ecs/ecs.config'):
        logger.info('start instance_id={} type=ecs'.format(instance_id))
        namer_class = ECSGroupNamer
    else:
        logger.info('start instance_id={} type=asg'.format(instance_id))
        namer_class = GroupNamer

    try:
        namer = namer_class(instance_id)
    except KeyError:
        return 1
    except ValueError:
        return 1
    namer.name_instance()
    logger.info('end instance_id={}'.format(instance_id))


if __name__ == "__main__":
    sys.exit(main())
