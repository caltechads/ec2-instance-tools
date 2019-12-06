#!/usr/bin/env python
from ec2_instance_tools import __version__
from setuptools import setup, find_packages  # @UnresolvedImport

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(name="ec2-instance-tools",
      version=__version__,
      description="Useful instrumentation for EC2 instances",
      author="Caltech IMSS ADS",
      author_email="imss-ads-staff@caltech.edu",
      url="https://github.com/caltechads/ec2-instance-tools",
      long_description=long_description,
      long_description_content_type="text/markdown",
      keywords=['aws', 'devops'],
      classifiers=[
          "Programming Language :: Python :: 2.7",
          "Programming Language :: Python :: 3"
      ],
      packages=find_packages(),
      include_package_data=True,
      install_requires=[
          "boto3 >= 1.7.55",
      ],
      entry_points={'console_scripts': [
          'sshec2 = ec2_instance_tools.sshec2:main',
          'ec2autonamer = ec2_instance_tools.namer:main'
          'ec2whoami = ec2_instance_tools.whoami:main'
      ]}
      )
