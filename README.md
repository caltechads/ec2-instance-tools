# ec2-instance-tools

This repository contains helper scripts for use on EC2 Amazon Linux instances.


## sshec2 

```
Usage: sshec2 [flags] <NAME> [<command>]

Look up the private IP address of a running EC2 instance by its Name tag and ssh into it.

If <command> is supplied, run that shell command on the remote instance and exit.

If multiple instances have the same Name tag, print info about all found instances
and exit.


Options:
  -h, --help         show this help message and exit
  -t TAG, --tag=TAG  set TAG to check to find instances via this tag.
                     Default: Name.
  -v, --verbose      Make ssh print verbose debug messages
```

## ec2autonamer

```
Usage: ec2autonamer [flags] [<instance-id>]

If an instance was launched from an autoscaling group, it will come up with no
Name: tag.  This script assigns an appropriate name tag to the instance.

If <instance-id> is not supplied, namer.py will look in /etc/instance-id for the
instance id.

The name will have one of the following patterns:

If this instance is an ECS container machine: ecs.{autoscalinggroup_name}.{zone-abbr}.{number},
where {zone-abbr} is the availability zone name of the instance minus the region name.

Otherwise: {autoscalinggroup_name}-{number}

In both cases, `{number}` will be chosen to be the lowest positive integer that
is not already taken by another instance in the autoscaling group.


Options:
  -h, --help  show this help message and exit
```

In order to run this on an instance, the instances IAM instance profile will need to have
the following rights:

```
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
```

## Installing ec2-instance-tools

ec2-instance-tools is a pure python package.  As such, it can be installed in the
usual python ways.  For the following instructions, either install it into your
global python install, or use a python [virtual environment](https://python-guide-pt-br.readthedocs.io/en/latest/dev/virtualenvs/) to install it
without polluting your global python environment.

### Install via pip

```
pip install ec2-instance-tools
```

### Install via `setup.py`

Download a release from [Github](https://github.com/caltechads/ec2-instance-tools/releases), then:

```
unzip ec2-instance-tools-0.29.9.zip
cd ec2-instance-tools-0.29.9
python setup.py install
```

Or:

```
git clone https://github.com/caltechads/ec2-instance-tools.git
cd ec2-instance-tools
python setup.py install
```

### Using pyenv to install into a virtual environment (Recommended)

If you use python and frequently need to install additional python modules,
[pyenv](https://github.com/pyenv/pyenv) and [pyenv-virtualenv](https://github.com/pyenv/pyenv-virtualenv)
are extremely useful.  They allow some very useful things:

* Manage your virtualenvs easily on a per-project basis
* Provide support for per-project Python versions.

To install `pyenv` and `pyenv-virtualenv` and set up your environment for the
first time.
