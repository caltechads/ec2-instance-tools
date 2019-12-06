#!/usr/bin/env python
"""
If an instance was launched from an autoscaling group, it will come up with no Name: tag.
This script assigns an appropriate name tag to the instance.  The name will have one
of the following patterns.

If this instance is an ECS container machine:
    ecs.{asg.name}.{zone-abbr}.{number}

Where {zone-abbr} is the availability zone name of the instance minus the region name

Otherwise:
    {asg.name}-{number}

In both cases, ${number} will be chosen to be the lowest positive integer that is
not already taken by another instance in the autoscaling group.

In order to run this on an instance, you'll need to have a policy with this body attached to the instance
role::


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
from optparse import OptionParser
import os
import re
import sys

import boto3

from ec2_instance_tools.metadata import EC2Metadata


address = '/dev/log'
if sys.platform == "darwin":
    address = '/var/run/syslog'

LOGGING = {
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

If <instance-id> is not supplied, %prog will ask the EC2 instance metadata endpoint for the
instance id.

The name will have one of the following patterns:

If this instance is an ECS container machine: ecs.{autoscalinggroup_name}.{zone-abbr}.{number},
where {zone-abbr} is the availability zone name of the instance minus the region name.

Otherwise: {autoscalinggroup_name}-{number}

In both cases, {number} will be chosen to be the lowest positive integer that
is not already taken by another instance in the autoscaling group.
"""
    parser = OptionParser(usage=usage)

    (options, args) = parser.parse_args(argv)

    instance_id = None
    if len(argv) > 1:
        instance_id = argv[1]
    else:
        instance_id = EC2Metadata().get('instance-id')

    if not instance_id:
        print(usage)
        sys.exit(1)
    return (options, instance_id)


class Instance(object):
    """
    This is a wrapper class to boto3.ec2.Instance to mostly make working with instance tags more straightforward.
    """

    def __init__(self, instance_id):
        self.ec2 = boto3.resource('ec2')
        self.instance = self.ec2.Instance(instance_id)

    @property
    def instance_id(self):
        return self.instance.instance_id

    @property
    def tags(self):
        tags = {}
        for tag in self.instance.tags:
            tags[tag['Key']] = tag['Value']
        return tags

    @property
    def zone(self):
        return self.instance.placement['AvailabilityZone']

    @property
    def zone_abbr(self):
        """
        Return the zone name minus the region name.

        If the zone is "us-west-2b", return "b".
        """
        return re.sub(boto3.session.Session().region_name, "", self.zone)

    @property
    def name(self):
        return self.tags.get('Name', None)

    @name.setter
    def name(self, name):
        self.instance.create_tags(Tags=[{'Key': 'Name', 'Value': name}])

    @property
    def autoscaling_group(self):
        return self.tags.get('aws:autoscaling:groupName', None)


class GroupNamer(object):

    def __init__(self, instance_id):
        self.instance = Instance(instance_id)
        logger.info('instance.loaded instance_id={}'.format(self.instance.instance_id))
        if self.instance.name:
            logger.error('instance.has-name instance_id={} name={}'.format(
                self.instance.instance_id,
                self.instance.name
            ))
            raise ValueError('Instance {} already has a name.'.format(self.instance.instance_id))
        if not self.instance.autoscaling_group:
            logger.error('instance.not-in-asg instance_id={}'.format(self.instance.instance_id, self.instance.name))
            raise KeyError('Instance {} is not in an autoscaling group'.format(self.instance.instance_id))
        asg = boto3.client('autoscaling')
        self.group = asg.describe_auto_scaling_groups(
            AutoScalingGroupNames=[self.instance.autoscaling_group]
        )['AutoScalingGroups'][0]
        logger.info('group.loaded group_name={} n_instances={}'.format(self.name, len(self.group['Instances'])))

    @property
    def name(self):
        return self.group['AutoScalingGroupName']

    @property
    def name_pattern(self):
        """
        Set the naming pattern for instances in this ASG.  Pattern: "{group.name}-{number}".
        """
        return "{}-".format(re.sub("_", "-", self.name))

    @property
    def live_instances(self):
        """
        Return a list of boto3.ec2.Instance objects of all the running instances in the ASG that
        are not self.instance.
        """
        live = []
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
                continue
            live.append(instance)
        return live

    @property
    def existing_names(self):
        """
        Return a list of Name tag values for all live instances that are not self.instance.
        """
        return [instance.name for instance in self.live_instances]

    def name_instance(self):
        """
        Set the Name tag on self.instance.  Choose a name with the lowest number that does not conflict with other
        running instances in the ASG.
        """
        taken = self.existing_names
        i = 1
        while True:
            name = "{}{}".format(self.name_pattern, i)
            if name not in taken:
                break
            i += 1
        self.instance.name = name
        logger.info('instance.named instance_id={} name={}'.format(self.instance.instance_id, name))


class ECSGroupNamer(GroupNamer):

    @property
    def name_pattern(self):
        """
        Set the naming pattern for instances in this ECS cluster ASG.  Pattern: "ecs.{group.name}.{zone-abbr}.{number}".
        """
        return "ecs.{}.{}.".format(self.name, self.instance.zone_abbr)

    @property
    def existing_names(self):
        """
        Return the list of Name tag values for all live instances in the same AZ as self.instance.
        """
        return [instance.name for instance in self.live_instances if instance.zone == self.instance.zone]


def main(argv=sys.argv):
    """
    argv[1] is the instance id for this instance.
    """
    (options, instance_id) = parse_arguments(argv)

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
